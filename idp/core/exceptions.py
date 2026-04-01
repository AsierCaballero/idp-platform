"""
idp/core/exceptions.py
Jerarquía de excepciones del IDP.
"""
from __future__ import annotations


class IDPError(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFoundError(IDPError):
    status_code = 404
    error_code = "NOT_FOUND"


class ProjectNotFoundError(NotFoundError):
    error_code = "PROJECT_NOT_FOUND"


class TeamNotFoundError(NotFoundError):
    error_code = "TEAM_NOT_FOUND"


class ConflictError(IDPError):
    status_code = 409
    error_code = "CONFLICT"


class ProjectAlreadyExistsError(ConflictError):
    error_code = "PROJECT_ALREADY_EXISTS"


class TeamAlreadyExistsError(ConflictError):
    error_code = "TEAM_ALREADY_EXISTS"


class ValidationError(IDPError):
    status_code = 422
    error_code = "VALIDATION_ERROR"


class ProvisioningError(IDPError):
    status_code = 500
    error_code = "PROVISIONING_ERROR"


class PartialProvisioningError(ProvisioningError):
    error_code = "PARTIAL_PROVISIONING_ERROR"

    def __init__(self, message: str, completed_steps: list[str], failed_step: str):
        super().__init__(message)
        self.completed_steps = completed_steps
        self.failed_step = failed_step


class GitHubError(IDPError):
    status_code = 502
    error_code = "GITHUB_ERROR"


class GitHubRateLimitError(GitHubError):
    status_code = 429
    error_code = "GITHUB_RATE_LIMIT"


class KubernetesError(IDPError):
    status_code = 502
    error_code = "KUBERNETES_ERROR"


class ArgoCDError(IDPError):
    status_code = 502
    error_code = "ARGOCD_ERROR"
