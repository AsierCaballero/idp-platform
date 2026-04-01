"""
idp/api/main.py
FastAPI app del IDP Platform.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from idp.adapters.github.github_adapter import GitHubAdapter, MockGitHubAdapter
from idp.adapters.k8s.k8s_adapter import KubernetesAdapter, MockKubernetesAdapter
from idp.api.routers.projects import build_router as build_projects_router
from idp.api.routers.teams import build_router as build_teams_router
from idp.core.exceptions import IDPError
from idp.core.ports.in_memory import InMemoryProjectRepository, InMemoryTeamRepository
from idp.core.services.project_service import (
    ProjectService,
    ProvisioningService,
    TeamService,
)

logger = logging.getLogger(__name__)

# ── Wiring ────────────────────────────────────────────────────────

def _build_dependencies():
    team_repo = InMemoryTeamRepository()
    project_repo = InMemoryProjectRepository()

    github_token = os.getenv("GITHUB_TOKEN")
    github_org = os.getenv("GITHUB_ORG", "myorg")

    if github_token:
        github = GitHubAdapter(token=github_token, org=github_org)
    else:
        github = MockGitHubAdapter(org=github_org)

    k8s_in_cluster = os.getenv("K8S_IN_CLUSTER", "false").lower() == "true"
    k8s_kubeconfig = os.getenv("KUBECONFIG")
    if k8s_in_cluster or k8s_kubeconfig:
        k8s = KubernetesAdapter(
            in_cluster=k8s_in_cluster, kubeconfig=k8s_kubeconfig
        )
    else:
        k8s = MockKubernetesAdapter()

    team_svc = TeamService(repo=team_repo)
    project_svc = ProjectService(project_repo=project_repo, team_repo=team_repo)
    provisioning_svc = ProvisioningService(
        project_repo=project_repo,
        team_repo=team_repo,
        github=github,
        k8s=k8s,
        argocd_enabled=bool(os.getenv("ARGOCD_SERVER")),
    )
    return team_svc, project_svc, provisioning_svc


team_svc, project_svc, provisioning_svc = _build_dependencies()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("IDP Platform starting")
    yield
    logger.info("IDP Platform stopped")


app = FastAPI(
    title="IDP Platform",
    version="1.0.0",
    description="Internal Developer Platform — self-service de infraestructura",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IDPError)
async def idp_error_handler(request: Request, exc: IDPError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message, "detail": exc.detail},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error_code": "VALIDATION_ERROR", "message": str(exc)},
    )


# Routers
app.include_router(build_teams_router(team_svc), prefix="/api/v1")
app.include_router(
    build_projects_router(project_svc, provisioning_svc),
    prefix="/api/v1",
)


@app.get("/health", tags=["health"])
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "version": "1.0.0",
        "github": await (provisioning_svc.github.check_health()),
        "k8s": await (provisioning_svc.k8s.check_health()),
    }


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"name": "IDP Platform", "docs": "/docs"}
