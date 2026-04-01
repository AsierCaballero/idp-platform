"""
idp/core/domain/models.py
Modelos de dominio del IDP. Puro Python, sin dependencias externas.
"""
from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def to_slug(value: str) -> str:
    slug = value.lower().strip()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


# ── Enums ─────────────────────────────────────────────────────────

class ProjectStatus(str, enum.Enum):
    PENDING      = "pending"
    PROVISIONING = "provisioning"
    ACTIVE       = "active"
    FAILED       = "failed"
    DELETING     = "deleting"
    DELETED      = "deleted"


class EnvironmentTier(str, enum.Enum):
    DEV     = "dev"
    STAGING = "staging"
    PROD    = "prod"


class ProvisioningStep(str, enum.Enum):
    GITHUB_REPO    = "github_repo"
    GITHUB_BRANCH  = "github_branch_protection"
    GITHUB_ACTIONS = "github_actions"
    K8S_NAMESPACE  = "k8s_namespace"
    K8S_QUOTA      = "k8s_resource_quota"
    K8S_RBAC       = "k8s_rbac"
    K8S_NETPOL     = "k8s_network_policy"
    ARGOCD_APP     = "argocd_application"
    SECRETS        = "secrets_store"


class AuditAction(str, enum.Enum):
    CREATE      = "create"
    UPDATE      = "update"
    DELETE      = "delete"
    REPROVISION = "reprovision"


# ── Value Objects ─────────────────────────────────────────────────

_CPU_RE = re.compile(r"^\d+m?$")
_MEM_RE = re.compile(r"^\d+(Mi|Gi)$")


def _parse_cpu(v: str) -> float:
    return float(v[:-1]) / 1000 if v.endswith("m") else float(v)


def _parse_mem(v: str) -> float:
    return float(v[:-2]) * (1024 if v.endswith("Gi") else 1)


@dataclass(frozen=True)
class ResourceQuota:
    cpu_request: str    = "100m"
    cpu_limit: str      = "500m"
    memory_request: str = "128Mi"
    memory_limit: str   = "512Mi"
    storage_limit: str  = "5Gi"
    max_replicas: int   = 3

    def __post_init__(self):
        for attr, val, pattern in [
            ("cpu_request",    self.cpu_request,    _CPU_RE),
            ("cpu_limit",      self.cpu_limit,      _CPU_RE),
            ("memory_request", self.memory_request, _MEM_RE),
            ("memory_limit",   self.memory_limit,   _MEM_RE),
            ("storage_limit",  self.storage_limit,  _MEM_RE),
        ]:
            if not pattern.match(val):
                raise ValueError(f"{attr} inválido: {val!r}")
        if not (1 <= self.max_replicas <= 100):
            raise ValueError(f"max_replicas debe estar entre 1 y 100, got {self.max_replicas}")
        if _parse_cpu(self.cpu_limit) < _parse_cpu(self.cpu_request):
            raise ValueError("cpu_limit debe ser >= cpu_request")
        if _parse_mem(self.memory_limit) < _parse_mem(self.memory_request):
            raise ValueError("memory_limit debe ser >= memory_request")

    @classmethod
    def for_prod(cls) -> "ResourceQuota":
        return cls(
            cpu_request="500m", cpu_limit="2000m",
            memory_request="512Mi", memory_limit="2Gi",
            storage_limit="20Gi", max_replicas=10,
        )

    @classmethod
    def for_dev(cls) -> "ResourceQuota":
        return cls(
            cpu_request="50m", cpu_limit="200m",
            memory_request="64Mi", memory_limit="256Mi",
            storage_limit="2Gi", max_replicas=2,
        )


# ── Entities ──────────────────────────────────────────────────────

_TEAM_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 _-]{1,62}[a-zA-Z0-9]$")
_PROJECT_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9 _-]{1,62}[a-zA-Z0-9]$")


@dataclass
class Team:
    name: str
    id: str = field(default_factory=_new_id)
    slug: str = field(default="")
    description: Optional[str] = None
    email: Optional[str] = None
    slack_channel: Optional[str] = None
    github_team: Optional[str] = None
    cost_center: Optional[str] = None
    is_active: bool = True
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self):
        self.name = self.name.strip()
        if len(self.name) < 3:
            raise ValueError(f"Team name demasiado corto: {self.name!r}")
        if not _TEAM_NAME_RE.match(self.name):
            raise ValueError(f"Team name inválido: {self.name!r}")
        if not self.slug:
            self.slug = to_slug(self.name)
        if self.email and "@" not in self.email:
            raise ValueError(f"Email inválido: {self.email!r}")

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = _utcnow()

    def update(self, **kwargs) -> None:
        allowed = {"description", "email", "slack_channel", "github_team", "cost_center"}
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                setattr(self, k, v)
        self.updated_at = _utcnow()

    def __repr__(self) -> str:
        return f"<Team {self.slug} active={self.is_active}>"


@dataclass
class ProjectEnvironment:
    tier: EnvironmentTier
    quota: ResourceQuota = field(default_factory=ResourceQuota)
    k8s_namespace: Optional[str] = None
    argocd_app_name: Optional[str] = None
    is_active: bool = True
    created_at: datetime = field(default_factory=_utcnow)

    def set_namespace(self, ns: str) -> None:
        self.k8s_namespace = ns


@dataclass
class Project:
    name: str
    team_id: str
    id: str = field(default_factory=_new_id)
    slug: str = field(default="")
    description: Optional[str] = None
    owner_email: Optional[str] = None
    status: ProjectStatus = ProjectStatus.PENDING
    environments: list[ProjectEnvironment] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)

    # External refs
    github_repo_url: Optional[str] = None
    github_repo_name: Optional[str] = None
    k8s_namespace: Optional[str] = None
    argocd_app_name: Optional[str] = None

    # Provisioning state
    provisioning_steps: dict[str, str] = field(default_factory=dict)
    error_message: Optional[str] = None
    provisioning_started_at: Optional[datetime] = None
    provisioning_completed_at: Optional[datetime] = None

    # Lifecycle
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self):
        self.name = self.name.strip()
        if len(self.name) < 3:
            raise ValueError(f"Project name demasiado corto: {self.name!r}")
        if not _PROJECT_NAME_RE.match(self.name):
            raise ValueError(
                f"Project name inválido: {self.name!r} — debe empezar por letra"
            )
        if not self.slug:
            self.slug = to_slug(self.name)
        if len(self.environments) == 0:
            self.environments = [
                ProjectEnvironment(tier=EnvironmentTier.DEV)
            ]
        # Validar tiers únicos
        tiers = [e.tier for e in self.environments]
        if len(tiers) != len(set(tiers)):
            raise ValueError("Cada tier solo puede aparecer una vez")

    @property
    def is_provisionable(self) -> bool:
        return self.status in (ProjectStatus.PENDING, ProjectStatus.FAILED)

    @property
    def provisioning_duration_seconds(self) -> Optional[float]:
        if self.provisioning_started_at and self.provisioning_completed_at:
            return (
                self.provisioning_completed_at - self.provisioning_started_at
            ).total_seconds()
        return None

    def start_provisioning(self) -> None:
        if not self.is_provisionable:
            raise ValueError(
                f"No se puede provisionar en estado {self.status.value}"
            )
        self.status = ProjectStatus.PROVISIONING
        self.provisioning_started_at = _utcnow()
        self.error_message = None
        self.provisioning_steps = {
            step.value: "pending" for step in ProvisioningStep
        }

    def set_step(self, step: ProvisioningStep, status: str) -> None:
        self.provisioning_steps[step.value] = status
        self.updated_at = _utcnow()

    def mark_active(self) -> None:
        self.status = ProjectStatus.ACTIVE
        self.provisioning_completed_at = _utcnow()

    def mark_failed(self, error: str) -> None:
        self.status = ProjectStatus.FAILED
        self.error_message = error[:1000]

    def soft_delete(self) -> None:
        self.status = ProjectStatus.DELETED
        self.is_deleted = True
        self.deleted_at = _utcnow()

    def add_tag(self, key: str, value: str) -> None:
        if len(self.tags) >= 20:
            raise ValueError("Máximo 20 tags por proyecto")
        self.tags[key] = value

    def get_environment(self, tier: EnvironmentTier) -> Optional[ProjectEnvironment]:
        return next((e for e in self.environments if e.tier == tier), None)

    def __repr__(self) -> str:
        return f"<Project {self.slug} [{self.status.value}]>"


@dataclass
class AuditLog:
    project_id: str
    action: AuditAction
    actor: str
    id: str = field(default_factory=_new_id)
    success: bool = True
    details: dict = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: datetime = field(default_factory=_utcnow)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action.value} on {self.project_id} by {self.actor}>"


# ── Result types ──────────────────────────────────────────────────

@dataclass
class GitHubRepoResult:
    name: str
    html_url: str
    clone_url: str
    ssh_url: str = ""


@dataclass
class K8sNamespaceResult:
    name: str
    uid: str
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ProvisioningResult:
    project: Project
    completed_steps: list[str]
    failed_step: Optional[str] = None
    duration_ms: int = 0

    @property
    def success(self) -> bool:
        return self.failed_step is None
