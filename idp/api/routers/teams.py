"""
idp/api/routers/teams.py
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from idp.core.services.project_service import TeamService


class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=64)
    description: str | None = None
    email: str | None = None
    slack_channel: str | None = None
    github_team: str | None = None
    cost_center: str | None = None


class TeamUpdateRequest(BaseModel):
    description: str | None = None
    email: str | None = None
    slack_channel: str | None = None
    github_team: str | None = None
    cost_center: str | None = None


def _serialize_team(t) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "slug": t.slug,
        "description": t.description,
        "email": t.email,
        "slack_channel": t.slack_channel,
        "github_team": t.github_team,
        "cost_center": t.cost_center,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def build_router(svc: TeamService) -> APIRouter:
    router = APIRouter(prefix="/teams", tags=["teams"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_team(data: TeamCreateRequest) -> dict:
        team = svc.create_team(
            name=data.name,
            description=data.description,
            email=data.email,
            slack_channel=data.slack_channel,
            github_team=data.github_team,
            cost_center=data.cost_center,
        )
        return _serialize_team(team)

    @router.get("")
    async def list_teams() -> list[dict]:
        return [_serialize_team(t) for t in svc.list_teams()]

    @router.get("/{team_id}")
    async def get_team(team_id: str) -> dict:
        return _serialize_team(svc.get_team(team_id))

    @router.patch("/{team_id}")
    async def update_team(team_id: str, data: TeamUpdateRequest) -> dict:
        team = svc.update_team(
            team_id,
            description=data.description,
            email=data.email,
            slack_channel=data.slack_channel,
            github_team=data.github_team,
            cost_center=data.cost_center,
        )
        return _serialize_team(team)

    @router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_team(team_id: str) -> None:
        svc.deactivate_team(team_id)

    return router
