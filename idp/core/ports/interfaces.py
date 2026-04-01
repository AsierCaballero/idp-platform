"""
idp/core/ports/interfaces.py
Puertos (interfaces) del dominio. El core define QUÉ necesita,
los adapters implementan CÓMO.
Usa ABC + Protocol para máxima flexibilidad.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Protocol, runtime_checkable

from idp.core.domain.models import (
    AuditLog,
    GitHubRepoResult,
    K8sNamespaceResult,
    Project,
    ProjectStatus,
    ResourceQuota,
    Team,
)


# ── Storage ports ─────────────────────────────────────────────────

class TeamRepository(ABC):

    @abstractmethod
    def save(self, team: Team) -> Team: ...

    @abstractmethod
    def get_by_id(self, team_id: str) -> Team: ...

    @abstractmethod
    def get_by_slug(self, slug: str) -> Team: ...

    @abstractmethod
    def list_active(self) -> list[Team]: ...

    @abstractmethod
    def exists_slug(self, slug: str) -> bool: ...


class ProjectRepository(ABC):

    @abstractmethod
    def save(self, project: Project) -> Project: ...

    @abstractmethod
    def get_by_id(self, project_id: str) -> Project: ...

    @abstractmethod
    def list_by_team(
        self, team_id: str,
        status: Optional[ProjectStatus] = None
    ) -> list[Project]: ...

    @abstractmethod
    def list_all(
        self,
        status: Optional[ProjectStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Project], int]: ...

    @abstractmethod
    def exists(self, slug: str, team_id: str) -> bool: ...

    @abstractmethod
    def save_audit(self, log: AuditLog) -> None: ...

    @abstractmethod
    def get_audit_logs(self, project_id: str, limit: int = 50) -> list[AuditLog]: ...


# ── External service ports ─────────────────────────────────────────

@runtime_checkable
class GitHubPort(Protocol):
    """Operaciones de GitHub necesarias por el dominio."""

    async def create_repo(
        self,
        name: str,
        description: str,
        private: bool,
    ) -> GitHubRepoResult: ...

    async def configure_branch_protection(
        self, repo_name: str, branch: str
    ) -> None: ...

    async def add_actions_workflows(self, repo_name: str) -> None: ...

    async def add_team_to_repo(
        self, repo_name: str, team_slug: str, permission: str
    ) -> None: ...

    async def delete_repo(self, repo_name: str) -> None: ...

    async def check_health(self) -> bool: ...


@runtime_checkable
class KubernetesPort(Protocol):
    """Operaciones de Kubernetes necesarias por el dominio."""

    async def create_namespace(
        self,
        project_slug: str,
        tier: str,
        team_slug: str,
        labels: dict,
    ) -> K8sNamespaceResult: ...

    async def create_resource_quota(
        self, namespace: str, quota: ResourceQuota
    ) -> None: ...

    async def create_rbac(
        self, namespace: str, team_slug: str, project_slug: str
    ) -> None: ...

    async def create_network_policy(self, namespace: str) -> None: ...

    async def delete_namespace(self, namespace: str) -> None: ...

    async def check_health(self) -> bool: ...


@runtime_checkable
class NotificationPort(Protocol):
    """Notificaciones (Slack, email, etc.)."""

    async def notify_project_ready(
        self, project: Project, team: Team
    ) -> None: ...

    async def notify_provisioning_failed(
        self, project: Project, team: Team, error: str
    ) -> None: ...
