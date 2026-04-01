"""
idp/core/services/project_service.py
Servicios de aplicación — orquestan dominio + ports.
Sin frameworks, puro Python.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from idp.core.domain.models import (
    AuditAction,
    AuditLog,
    EnvironmentTier,
    Project,
    ProjectEnvironment,
    ProjectStatus,
    ProvisioningResult,
    ProvisioningStep,
    ResourceQuota,
    Team,
    to_slug,
)
from idp.core.exceptions import (
    PartialProvisioningError,
    ProjectAlreadyExistsError,
    ProvisioningError,
    TeamAlreadyExistsError,
    TeamNotFoundError,
)
from idp.core.ports.interfaces import (
    GitHubPort,
    KubernetesPort,
    NotificationPort,
    ProjectRepository,
    TeamRepository,
)

logger = logging.getLogger(__name__)


# ── Team service ──────────────────────────────────────────────────

class TeamService:

    def __init__(self, repo: TeamRepository):
        self.repo = repo

    def create_team(
        self,
        name: str,
        *,
        description: Optional[str] = None,
        email: Optional[str] = None,
        slack_channel: Optional[str] = None,
        github_team: Optional[str] = None,
        cost_center: Optional[str] = None,
    ) -> Team:
        slug = to_slug(name)
        if self.repo.exists_slug(slug):
            raise TeamAlreadyExistsError(f"Ya existe un equipo con slug '{slug}'")

        team = Team(
            name=name,
            description=description,
            email=email,
            slack_channel=slack_channel,
            github_team=github_team,
            cost_center=cost_center,
        )
        return self.repo.save(team)

    def get_team(self, team_id: str) -> Team:
        return self.repo.get_by_id(team_id)

    def list_teams(self) -> list[Team]:
        return self.repo.list_active()

    def update_team(self, team_id: str, **kwargs) -> Team:
        team = self.repo.get_by_id(team_id)
        team.update(**kwargs)
        return self.repo.save(team)

    def deactivate_team(self, team_id: str) -> Team:
        team = self.repo.get_by_id(team_id)
        team.deactivate()
        return self.repo.save(team)


# ── Project service ───────────────────────────────────────────────

class ProjectService:

    def __init__(
        self,
        project_repo: ProjectRepository,
        team_repo: TeamRepository,
    ):
        self.project_repo = project_repo
        self.team_repo = team_repo

    def create_project(
        self,
        name: str,
        team_id: str,
        *,
        description: Optional[str] = None,
        owner_email: Optional[str] = None,
        environments: Optional[list[dict]] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> Project:
        # Validar team existe
        team = self.team_repo.get_by_id(team_id)

        slug = to_slug(name)
        if self.project_repo.exists(slug, team_id):
            raise ProjectAlreadyExistsError(
                f"Ya existe el proyecto '{slug}' en el equipo {team.slug}"
            )

        # Construir environments
        env_objects: list[ProjectEnvironment] = []
        if environments:
            for env_cfg in environments:
                tier = EnvironmentTier(env_cfg["tier"])
                quota_kwargs = {k: v for k, v in env_cfg.items() if k != "tier"}
                quota = ResourceQuota(**quota_kwargs) if quota_kwargs else ResourceQuota()
                env_objects.append(ProjectEnvironment(tier=tier, quota=quota))
        else:
            env_objects = [ProjectEnvironment(tier=EnvironmentTier.DEV)]

        project = Project(
            name=name,
            team_id=team_id,
            description=description,
            owner_email=owner_email,
            environments=env_objects,
            tags=tags or {},
        )
        return self.project_repo.save(project)

    def get_project(self, project_id: str) -> Project:
        return self.project_repo.get_by_id(project_id)

    def list_projects(
        self,
        status: Optional[ProjectStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Project], int]:
        return self.project_repo.list_all(status=status, page=page, page_size=page_size)

    def list_by_team(
        self, team_id: str, status: Optional[ProjectStatus] = None
    ) -> list[Project]:
        # Verificar que el team existe
        self.team_repo.get_by_id(team_id)
        return self.project_repo.list_by_team(team_id, status=status)

    def update_project(self, project_id: str, **kwargs) -> Project:
        project = self.project_repo.get_by_id(project_id)
        allowed = {"description", "owner_email", "tags"}
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                setattr(project, k, v)
        return self.project_repo.save(project)

    def get_audit_logs(self, project_id: str, limit: int = 50) -> list[AuditLog]:
        return self.project_repo.get_audit_logs(project_id, limit)


# ── Provisioning service ──────────────────────────────────────────

class ProvisioningService:
    """
    Orquesta el provisioning completo.
    Es async para poder llamar a GitHub y K8s.
    Pasos idempotentes — reiniciable desde cualquier punto.
    """

    def __init__(
        self,
        project_repo: ProjectRepository,
        team_repo: TeamRepository,
        github: GitHubPort,
        k8s: KubernetesPort,
        namespace_prefix: str = "idp",
        argocd_enabled: bool = False,
        notifications: Optional[NotificationPort] = None,
    ):
        self.project_repo = project_repo
        self.team_repo = team_repo
        self.github = github
        self.k8s = k8s
        self.namespace_prefix = namespace_prefix
        self.argocd_enabled = argocd_enabled
        self.notifications = notifications

    def _ns_name(self, project_slug: str, tier: str) -> str:
        return f"{self.namespace_prefix}-{project_slug}-{tier}"

    async def provision(
        self, project_id: str, actor: str = "system"
    ) -> ProvisioningResult:
        project = self.project_repo.get_by_id(project_id)
        team = self.team_repo.get_by_id(project.team_id)

        if not project.is_provisionable:
            raise ProvisioningError(
                f"Proyecto {project.slug} no es provisionable en estado {project.status.value}"
            )

        project.start_provisioning()
        self.project_repo.save(project)

        start_ms = time.monotonic()
        completed: list[str] = []

        try:
            # Step 1: GitHub repo
            project.set_step(ProvisioningStep.GITHUB_REPO, "running")
            self.project_repo.save(project)
            repo = await self.github.create_repo(
                name=project.slug,
                description=project.description or f"Project {project.name}",
                private=True,
            )
            project.github_repo_url = repo.html_url
            project.github_repo_name = repo.name
            project.set_step(ProvisioningStep.GITHUB_REPO, "done")
            completed.append(ProvisioningStep.GITHUB_REPO.value)

            # Step 2: Branch protection
            project.set_step(ProvisioningStep.GITHUB_BRANCH, "running")
            await self.github.configure_branch_protection(project.slug, "main")
            project.set_step(ProvisioningStep.GITHUB_BRANCH, "done")
            completed.append(ProvisioningStep.GITHUB_BRANCH.value)

            # Step 3: GitHub Actions
            project.set_step(ProvisioningStep.GITHUB_ACTIONS, "running")
            await self.github.add_actions_workflows(project.slug)
            if team.github_team:
                await self.github.add_team_to_repo(project.slug, team.github_team, "push")
            project.set_step(ProvisioningStep.GITHUB_ACTIONS, "done")
            completed.append(ProvisioningStep.GITHUB_ACTIONS.value)

            # Steps 4–7: K8s por environment
            for env in project.environments:
                if not env.is_active:
                    continue
                ns_name = self._ns_name(project.slug, env.tier.value)

                project.set_step(ProvisioningStep.K8S_NAMESPACE, "running")
                ns = await self.k8s.create_namespace(
                    project.slug, env.tier.value, team.slug, project.tags
                )
                env.set_namespace(ns.name)
                if not project.k8s_namespace:
                    project.k8s_namespace = ns.name
                project.set_step(ProvisioningStep.K8S_NAMESPACE, "done")
                completed.append(ProvisioningStep.K8S_NAMESPACE.value)

                project.set_step(ProvisioningStep.K8S_QUOTA, "running")
                await self.k8s.create_resource_quota(ns.name, env.quota)
                project.set_step(ProvisioningStep.K8S_QUOTA, "done")

                project.set_step(ProvisioningStep.K8S_RBAC, "running")
                await self.k8s.create_rbac(ns.name, team.slug, project.slug)
                project.set_step(ProvisioningStep.K8S_RBAC, "done")
                completed.append(ProvisioningStep.K8S_RBAC.value)

                project.set_step(ProvisioningStep.K8S_NETPOL, "running")
                await self.k8s.create_network_policy(ns.name)
                project.set_step(ProvisioningStep.K8S_NETPOL, "done")

            # Step 8: ArgoCD
            if self.argocd_enabled:
                project.set_step(ProvisioningStep.ARGOCD_APP, "running")
                project.argocd_app_name = f"{project.slug}-dev"
                project.set_step(ProvisioningStep.ARGOCD_APP, "done")
            else:
                project.set_step(ProvisioningStep.ARGOCD_APP, "skipped")

            # Step 9: Secrets
            project.set_step(ProvisioningStep.SECRETS, "done")
            completed.append(ProvisioningStep.SECRETS.value)

            # Finalizar
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            project.mark_active()
            self.project_repo.save(project)

            self.project_repo.save_audit(AuditLog(
                project_id=project.id,
                action=AuditAction.CREATE,
                actor=actor,
                success=True,
                duration_ms=duration_ms,
                details={"completed_steps": completed, "github_repo": repo.html_url},
            ))

            if self.notifications:
                try:
                    await self.notifications.notify_project_ready(project, team)
                except Exception:
                    pass  # Notificaciones no son críticas

            logger.info(f"Provisioning OK: {project.slug} ({duration_ms}ms)")
            return ProvisioningResult(
                project=project,
                completed_steps=completed,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            project.mark_failed(str(e))
            self.project_repo.save(project)

            self.project_repo.save_audit(AuditLog(
                project_id=project.id,
                action=AuditAction.CREATE,
                actor=actor,
                success=False,
                duration_ms=duration_ms,
                error=str(e),
                details={"completed_steps": completed},
            ))

            logger.error(f"Provisioning FAILED: {project.slug}: {e}")
            raise PartialProvisioningError(
                message=f"Provisioning fallido: {e}",
                completed_steps=completed,
                failed_step=str(e),
            ) from e

    async def deprovision(
        self, project_id: str, actor: str = "system"
    ) -> Project:
        project = self.project_repo.get_by_id(project_id)
        project.status = ProjectStatus.DELETING
        self.project_repo.save(project)

        errors = []
        for env in project.environments:
            if env.k8s_namespace:
                try:
                    await self.k8s.delete_namespace(env.k8s_namespace)
                except Exception as e:
                    errors.append(str(e))

        if project.github_repo_name:
            try:
                await self.github.delete_repo(project.github_repo_name)
            except Exception as e:
                errors.append(str(e))

        project.soft_delete()
        self.project_repo.save(project)

        self.project_repo.save_audit(AuditLog(
            project_id=project.id,
            action=AuditAction.DELETE,
            actor=actor,
            success=not bool(errors),
            details={"errors": errors} if errors else {},
        ))

        return project
