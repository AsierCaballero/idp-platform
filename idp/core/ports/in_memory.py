"""
idp/core/ports/in_memory.py
Implementaciones en memoria de los repositorios.
Perfectas para tests unitarios y modo --local del CLI.
"""
from __future__ import annotations

from typing import Optional

from idp.core.domain.models import (
    AuditLog,
    Project,
    ProjectStatus,
    Team,
)
from idp.core.exceptions import (
    ProjectNotFoundError,
    TeamNotFoundError,
)
from idp.core.ports.interfaces import ProjectRepository, TeamRepository


class InMemoryTeamRepository(TeamRepository):

    def __init__(self):
        self._teams: dict[str, Team] = {}

    def save(self, team: Team) -> Team:
        self._teams[team.id] = team
        return team

    def get_by_id(self, team_id: str) -> Team:
        team = self._teams.get(team_id)
        if not team or not team.is_active:
            raise TeamNotFoundError(f"Equipo {team_id} no encontrado")
        return team

    def get_by_slug(self, slug: str) -> Team:
        for team in self._teams.values():
            if team.slug == slug and team.is_active:
                return team
        raise TeamNotFoundError(f"Equipo con slug '{slug}' no encontrado")

    def list_active(self) -> list[Team]:
        return sorted(
            [t for t in self._teams.values() if t.is_active],
            key=lambda t: t.name,
        )

    def exists_slug(self, slug: str) -> bool:
        return any(t.slug == slug and t.is_active for t in self._teams.values())

    def clear(self) -> None:
        self._teams.clear()


class InMemoryProjectRepository(ProjectRepository):

    def __init__(self):
        self._projects: dict[str, Project] = {}
        self._audit_logs: list[AuditLog] = []

    def save(self, project: Project) -> Project:
        self._projects[project.id] = project
        return project

    def get_by_id(self, project_id: str) -> Project:
        p = self._projects.get(project_id)
        if not p or p.is_deleted:
            raise ProjectNotFoundError(f"Proyecto {project_id} no encontrado")
        return p

    def list_by_team(
        self,
        team_id: str,
        status: Optional[ProjectStatus] = None,
    ) -> list[Project]:
        results = [
            p for p in self._projects.values()
            if p.team_id == team_id and not p.is_deleted
        ]
        if status:
            results = [p for p in results if p.status == status]
        return sorted(results, key=lambda p: p.created_at, reverse=True)

    def list_all(
        self,
        status: Optional[ProjectStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Project], int]:
        results = [p for p in self._projects.values() if not p.is_deleted]
        if status:
            results = [p for p in results if p.status == status]
        results.sort(key=lambda p: p.created_at, reverse=True)
        total = len(results)
        start = (page - 1) * page_size
        return results[start: start + page_size], total

    def exists(self, slug: str, team_id: str) -> bool:
        return any(
            p.slug == slug and p.team_id == team_id and not p.is_deleted
            for p in self._projects.values()
        )

    def save_audit(self, log: AuditLog) -> None:
        self._audit_logs.append(log)

    def get_audit_logs(self, project_id: str, limit: int = 50) -> list[AuditLog]:
        logs = [l for l in self._audit_logs if l.project_id == project_id]
        return sorted(logs, key=lambda l: l.created_at, reverse=True)[:limit]

    def clear(self) -> None:
        self._projects.clear()
        self._audit_logs.clear()
