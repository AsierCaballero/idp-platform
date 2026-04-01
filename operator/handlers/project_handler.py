"""
operator/handlers/project_handler.py
K8s Operator para el CRD Project.idp.company.io usando kopf.
Sincroniza el estado deseado (spec) con el estado real (GitHub + K8s).

Deploy:
  kubectl apply -f operator/crds/project-crd.yaml
  kubectl apply -f k8s/base/operator.yaml
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

try:
    import kopf
    HAS_KOPF = True
except ImportError:
    HAS_KOPF = False
    # Stub para que el módulo sea importable sin kopf
    class kopf:  # type: ignore
        @staticmethod
        def on(*a, **kw): return lambda f: f
        @staticmethod
        def timer(*a, **kw): return lambda f: f

from idp.adapters.github.github_adapter import GitHubAdapter, MockGitHubAdapter
from idp.adapters.k8s.k8s_adapter import KubernetesAdapter, MockKubernetesAdapter
from idp.core.domain.models import (
    EnvironmentTier, Project, ProjectEnvironment, ResourceQuota, Team
)
from idp.core.ports.in_memory import InMemoryProjectRepository, InMemoryTeamRepository
from idp.core.services.project_service import ProvisioningService, TeamService


def _get_services():
    github_token = os.getenv("GITHUB_TOKEN")
    github = GitHubAdapter(github_token, os.getenv("GITHUB_ORG", "myorg")) \
        if github_token else MockGitHubAdapter()
    k8s = KubernetesAdapter(in_cluster=True)

    team_repo = InMemoryTeamRepository()
    project_repo = InMemoryProjectRepository()
    svc = ProvisioningService(
        project_repo=project_repo,
        team_repo=team_repo,
        github=github,
        k8s=k8s,
    )
    return team_repo, project_repo, svc


if HAS_KOPF:

    @kopf.on.create("idp.company.io", "v1alpha1", "projects")
    async def on_project_create(spec, name, namespace, patch, **_):
        """Triggered cuando se crea un Project CR."""
        logger.info(f"Project CR created: {name}")
        team_repo, project_repo, svc = _get_services()

        # Crear team si no existe
        team_slug = spec.get("teamSlug", "default")
        try:
            team = team_repo.get_by_slug(team_slug)
        except Exception:
            team = Team(name=team_slug.replace("-", " ").title())
            team_repo.save(team)

        # Construir envs
        envs = []
        for e in spec.get("environments", [{"tier": "dev"}]):
            tier = EnvironmentTier(e["tier"])
            quota = ResourceQuota(
                cpu_request=e.get("cpuRequest", "100m"),
                cpu_limit=e.get("cpuLimit", "500m"),
                memory_request=e.get("memoryRequest", "128Mi"),
                memory_limit=e.get("memoryLimit", "512Mi"),
            )
            envs.append(ProjectEnvironment(tier=tier, quota=quota))

        project = Project(
            name=spec["name"],
            team_id=team.id,
            description=spec.get("description"),
            owner_email=spec.get("ownerEmail"),
            environments=envs,
            tags=dict(spec.get("tags", {})),
        )
        project_repo.save(project)

        patch.status["phase"] = "Provisioning"

        try:
            result = await svc.provision(project.id, actor="k8s-operator")
            patch.status.update({
                "phase": "Active",
                "githubRepoUrl": result.project.github_repo_url,
                "k8sNamespace": result.project.k8s_namespace,
                "provisioningSteps": result.project.provisioning_steps,
            })
            logger.info(f"Project {name} provisioned successfully")
        except Exception as e:
            patch.status.update({"phase": "Failed", "errorMessage": str(e)})
            raise kopf.PermanentError(f"Provisioning failed: {e}")

    @kopf.on.delete("idp.company.io", "v1alpha1", "projects")
    async def on_project_delete(spec, name, **_):
        """Triggered cuando se elimina un Project CR."""
        logger.info(f"Project CR deleted: {name}")
        _, project_repo, svc = _get_services()
        # Best-effort cleanup
        for p in project_repo.list_all()[0]:
            if p.slug == name:
                try:
                    await svc.deprovision(p.id, actor="k8s-operator")
                except Exception as e:
                    logger.warning(f"Deprovision partial: {e}")
                break

    @kopf.timer("idp.company.io", "v1alpha1", "projects", interval=300)
    async def reconcile(spec, status, name, patch, **_):
        """Reconciliación periódica cada 5 minutos."""
        phase = status.get("phase", "Pending")
        if phase == "Failed":
            logger.info(f"Auto-retrying failed project: {name}")
            # Mismo handler que create
            await on_project_create(
                spec=spec, name=name, namespace=None, patch=patch
            )
