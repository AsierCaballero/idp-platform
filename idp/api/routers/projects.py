"""
idp/api/routers/projects.py
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Query, status
from pydantic import BaseModel, Field

from idp.core.domain.models import ProjectStatus
from idp.core.services.project_service import ProjectService, ProvisioningService


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=128)
    team_id: str
    description: Optional[str] = None
    owner_email: Optional[str] = None
    environments: list[dict] = Field(default_factory=lambda: [{"tier": "dev"}])
    tags: Optional[dict[str, str]] = None


class ProjectUpdateRequest(BaseModel):
    description: Optional[str] = None
    owner_email: Optional[str] = None
    tags: Optional[dict[str, str]] = None


def _serialize_project(p) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "description": p.description,
        "status": p.status.value,
        "team_id": p.team_id,
        "owner_email": p.owner_email,
        "github_repo_url": p.github_repo_url,
        "github_repo_name": p.github_repo_name,
        "k8s_namespace": p.k8s_namespace,
        "argocd_app_name": p.argocd_app_name,
        "provisioning_steps": p.provisioning_steps,
        "error_message": p.error_message,
        "provisioning_started_at": (
            p.provisioning_started_at.isoformat() if p.provisioning_started_at else None
        ),
        "provisioning_completed_at": (
            p.provisioning_completed_at.isoformat() if p.provisioning_completed_at else None
        ),
        "provisioning_duration_seconds": p.provisioning_duration_seconds,
        "tags": p.tags,
        "environments": [
            {
                "tier": e.tier.value,
                "k8s_namespace": e.k8s_namespace,
                "cpu_request": e.quota.cpu_request,
                "cpu_limit": e.quota.cpu_limit,
                "memory_request": e.quota.memory_request,
                "memory_limit": e.quota.memory_limit,
                "max_replicas": e.quota.max_replicas,
                "is_active": e.is_active,
            }
            for e in p.environments
        ],
        "is_deleted": p.is_deleted,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def build_router(svc: ProjectService, provisioning: ProvisioningService) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["projects"])

    @router.post("", status_code=status.HTTP_202_ACCEPTED)
    async def create_project(
        data: ProjectCreateRequest,
        background_tasks: BackgroundTasks,
    ) -> dict:
        project = svc.create_project(
            name=data.name,
            team_id=data.team_id,
            description=data.description,
            owner_email=data.owner_email,
            environments=data.environments,
            tags=data.tags,
        )

        async def _provision():
            try:
                await provisioning.provision(project.id, actor=data.owner_email or "api")
            except Exception as e:
                pass  # Estado ya guardado en repo como FAILED

        background_tasks.add_task(_provision)
        return _serialize_project(project)

    @router.get("")
    async def list_projects(
        status_filter: Optional[str] = Query(None, alias="status"),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        st = ProjectStatus(status_filter) if status_filter else None
        items, total = svc.list_projects(status=st, page=page, page_size=page_size)
        return {
            "items": [_serialize_project(p) for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": (page * page_size) < total,
        }

    @router.get("/{project_id}")
    async def get_project(project_id: str) -> dict:
        return _serialize_project(svc.get_project(project_id))

    @router.patch("/{project_id}")
    async def update_project(project_id: str, data: ProjectUpdateRequest) -> dict:
        project = svc.update_project(
            project_id,
            description=data.description,
            owner_email=data.owner_email,
            tags=data.tags,
        )
        return _serialize_project(project)

    @router.get("/{project_id}/status")
    async def get_status(project_id: str) -> dict:
        p = svc.get_project(project_id)
        return {
            "project_id": p.id,
            "status": p.status.value,
            "steps": p.provisioning_steps,
            "error_message": p.error_message,
            "started_at": p.provisioning_started_at.isoformat() if p.provisioning_started_at else None,
            "completed_at": p.provisioning_completed_at.isoformat() if p.provisioning_completed_at else None,
            "duration_seconds": p.provisioning_duration_seconds,
        }

    @router.post("/{project_id}/reprovision", status_code=status.HTTP_202_ACCEPTED)
    async def reprovision(project_id: str, background_tasks: BackgroundTasks) -> dict:
        p = svc.get_project(project_id)
        if not p.is_provisionable:
            from idp.core.exceptions import IDPError
            raise IDPError(
                f"No se puede re-provisionar en estado {p.status.value}",
                detail="Solo es posible en estado PENDING o FAILED",
            )

        async def _reprovision():
            try:
                await provisioning.provision(project_id, actor="api-reprovision")
            except Exception:
                pass

        background_tasks.add_task(_reprovision)
        return {"project_id": project_id, "status": "reprovisioning"}

    @router.get("/{project_id}/audit")
    async def get_audit(
        project_id: str,
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict]:
        logs = svc.get_audit_logs(project_id, limit=limit)
        return [
            {
                "id": l.id,
                "project_id": l.project_id,
                "action": l.action.value,
                "actor": l.actor,
                "success": l.success,
                "details": l.details,
                "error": l.error,
                "duration_ms": l.duration_ms,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ]

    @router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_project(project_id: str) -> None:
        await provisioning.deprovision(project_id, actor="api")

    return router
