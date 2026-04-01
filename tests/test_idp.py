"""
tests/test_idp.py
Tests del IDP Platform — ~35 tests con unittest puro, sin dependencias externas.
"""
from __future__ import annotations

import asyncio, sys, os, unittest
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from idp.core.domain.models import (
    EnvironmentTier, Project, ProjectEnvironment,
    ProjectStatus, ResourceQuota, Team, to_slug,
)
from idp.core.exceptions import (
    GitHubError, KubernetesError, PartialProvisioningError,
    ProjectAlreadyExistsError, ProjectNotFoundError, ProvisioningError,
    TeamAlreadyExistsError, TeamNotFoundError,
)
from idp.core.ports.in_memory import InMemoryProjectRepository, InMemoryTeamRepository
from idp.core.services.project_service import ProjectService, ProvisioningService, TeamService
from idp.adapters.github.github_adapter import MockGitHubAdapter
from idp.adapters.k8s.k8s_adapter import MockKubernetesAdapter

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

# ── ResourceQuota ─────────────────────────────────────────────────
class TestResourceQuota(unittest.TestCase):
    def test_defaults_valid(self):
        self.assertEqual(ResourceQuota().cpu_request, "100m")
    def test_for_prod_preset(self):
        self.assertEqual(ResourceQuota.for_prod().max_replicas, 10)
    def test_cpu_limit_less_than_request_raises(self):
        with self.assertRaises(ValueError): ResourceQuota(cpu_request="500m", cpu_limit="100m")
    def test_memory_limit_less_than_request_raises(self):
        with self.assertRaises(ValueError): ResourceQuota(memory_request="512Mi", memory_limit="128Mi")
    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError): ResourceQuota(cpu_request="500MB")
    def test_max_replicas_out_of_range_raises(self):
        with self.assertRaises(ValueError): ResourceQuota(max_replicas=0)

# ── Team model ────────────────────────────────────────────────────
class TestTeam(unittest.TestCase):
    def test_slug_auto_generated(self):
        self.assertEqual(Team(name="Platform Eng").slug, "platform-eng")
    def test_name_too_short_raises(self):
        with self.assertRaises(ValueError): Team(name="AB")
    def test_deactivate(self):
        t = Team(name="Old Team")
        t.deactivate()
        self.assertFalse(t.is_active)

# ── Project model ─────────────────────────────────────────────────
class TestProject(unittest.TestCase):
    def _make(self, **kw): return Project(**{"name": "My Service", "team_id": "t-1", **kw})
    def test_slug_generated(self):
        self.assertEqual(self._make().slug, "my-service")
    def test_name_must_start_with_letter(self):
        with self.assertRaises(ValueError): self._make(name="123bad")
    def test_duplicate_tiers_raises(self):
        with self.assertRaises(ValueError):
            self._make(environments=[ProjectEnvironment(tier=EnvironmentTier.DEV),
                                      ProjectEnvironment(tier=EnvironmentTier.DEV)])
    def test_is_provisionable(self):
        self.assertTrue(self._make(status=ProjectStatus.PENDING).is_provisionable)
        self.assertFalse(self._make(status=ProjectStatus.ACTIVE).is_provisionable)
    def test_lifecycle(self):
        p = self._make()
        p.start_provisioning(); self.assertEqual(p.status, ProjectStatus.PROVISIONING)
        p.mark_active(); self.assertEqual(p.status, ProjectStatus.ACTIVE)
        p.soft_delete(); self.assertTrue(p.is_deleted)

# ── Exceptions ────────────────────────────────────────────────────
class TestExceptions(unittest.TestCase):
    def test_status_codes(self):
        self.assertEqual(ProjectNotFoundError("x").status_code, 404)
        self.assertEqual(ProjectAlreadyExistsError("x").status_code, 409)
        self.assertEqual(GitHubError("x").status_code, 502)
    def test_partial_provisioning_attrs(self):
        e = PartialProvisioningError("fail", ["github_repo"], "k8s_namespace")
        self.assertEqual(e.completed_steps, ["github_repo"])

# ── Services ──────────────────────────────────────────────────────
class TestServices(unittest.TestCase):
    def setUp(self):
        self.team_repo = InMemoryTeamRepository()
        self.project_repo = InMemoryProjectRepository()
        self.team_svc = TeamService(self.team_repo)
        self.project_svc = ProjectService(self.project_repo, self.team_repo)
        self.team = self.team_svc.create_team("Backend")

    def test_create_team_duplicate_raises(self):
        with self.assertRaises(TeamAlreadyExistsError): self.team_svc.create_team("Backend")
    def test_deactivate_team(self):
        self.team_svc.deactivate_team(self.team.id)
        self.assertEqual(len(self.team_svc.list_teams()), 0)
    def test_create_project(self):
        p = self.project_svc.create_project("My API", self.team.id)
        self.assertEqual(p.slug, "my-api")
    def test_create_project_duplicate_raises(self):
        self.project_svc.create_project("My API", self.team.id)
        with self.assertRaises(ProjectAlreadyExistsError):
            self.project_svc.create_project("My API", self.team.id)
    def test_create_project_bad_team_raises(self):
        with self.assertRaises(TeamNotFoundError):
            self.project_svc.create_project("X", "bad-id")
    def test_list_paginated(self):
        for i in range(5): self.project_svc.create_project(f"App {i}", self.team.id)
        items, total = self.project_svc.list_projects(page=1, page_size=3)
        self.assertEqual(total, 5); self.assertEqual(len(items), 3)

# ── Provisioning ──────────────────────────────────────────────────
class TestProvisioning(unittest.TestCase):
    def setUp(self):
        self.team_repo = InMemoryTeamRepository()
        self.project_repo = InMemoryProjectRepository()
        self.github = MockGitHubAdapter(org="testorg")
        self.k8s = MockKubernetesAdapter()
        self.svc = ProvisioningService(
            project_repo=self.project_repo, team_repo=self.team_repo,
            github=self.github, k8s=self.k8s,
        )
        self.team = Team(name="Backend", github_team="backend")
        self.team_repo.save(self.team)
        self.project = Project(name="My App", team_id=self.team.id)
        self.project_repo.save(self.project)

    def test_provision_success(self):
        result = run(self.svc.provision(self.project.id))
        self.assertTrue(result.success)
        self.assertEqual(result.project.status, ProjectStatus.ACTIVE)
    def test_provision_sets_github_url(self):
        run(self.svc.provision(self.project.id))
        p = self.project_repo.get_by_id(self.project.id)
        self.assertIn("testorg/my-app", p.github_repo_url)
    def test_provision_sets_k8s_namespace(self):
        run(self.svc.provision(self.project.id))
        p = self.project_repo.get_by_id(self.project.id)
        self.assertIn("my-app", p.k8s_namespace)
    def test_provision_creates_audit_log(self):
        run(self.svc.provision(self.project.id))
        self.assertTrue(self.project_repo.get_audit_logs(self.project.id)[0].success)
    def test_provision_already_active_raises(self):
        self.project.status = ProjectStatus.ACTIVE; self.project_repo.save(self.project)
        with self.assertRaises(ProvisioningError): run(self.svc.provision(self.project.id))
    def test_provision_github_failure_marks_failed(self):
        self.github.create_repo = AsyncMock(side_effect=GitHubError("down"))
        with self.assertRaises(PartialProvisioningError): run(self.svc.provision(self.project.id))
        self.assertEqual(self.project_repo.get_by_id(self.project.id).status, ProjectStatus.FAILED)
    def test_failed_project_can_retry(self):
        self.project.status = ProjectStatus.FAILED; self.project_repo.save(self.project)
        self.assertTrue(run(self.svc.provision(self.project.id)).success)
    def test_deprovision_soft_deletes(self):
        run(self.svc.provision(self.project.id))
        p = run(self.svc.deprovision(self.project.id))
        self.assertTrue(p.is_deleted)

if __name__ == "__main__":
    unittest.main(verbosity=2)
