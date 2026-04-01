"""
idp/adapters/github/github_adapter.py
Adaptador GitHub. Mock cuando no hay token (dev/tests).
Real con httpx async en producción.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from idp.core.domain.models import GitHubRepoResult
from idp.core.exceptions import GitHubError, GitHubRateLimitError

logger = logging.getLogger(__name__)

_CI_TEMPLATE = """\
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: echo "Add tests here"
"""

_DEPLOY_TEMPLATE = """\
name: Deploy
on:
  workflow_dispatch:
    inputs:
      environment:
        type: choice
        options: [dev, staging, prod]
        default: dev
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ github.event.inputs.environment }}
    steps:
      - uses: actions/checkout@v4
      - name: Deploy
        run: echo "Deploying to ${{ github.event.inputs.environment }}"
"""


class MockGitHubAdapter:
    """GitHub adapter en modo mock. No hace llamadas reales."""

    def __init__(self, org: str = "myorg"):
        self.org = org
        self._created_repos: list[str] = []
        self._deleted_repos: list[str] = []

    async def create_repo(
        self, name: str, description: str = "", private: bool = True
    ) -> GitHubRepoResult:
        logger.debug(f"[MOCK] GitHub create_repo: {name}")
        self._created_repos.append(name)
        return GitHubRepoResult(
            name=name,
            html_url=f"https://github.com/{self.org}/{name}",
            clone_url=f"https://github.com/{self.org}/{name}.git",
            ssh_url=f"git@github.com:{self.org}/{name}.git",
        )

    async def configure_branch_protection(
        self, repo_name: str, branch: str = "main"
    ) -> None:
        logger.debug(f"[MOCK] GitHub branch protection: {repo_name}:{branch}")

    async def add_actions_workflows(self, repo_name: str) -> None:
        logger.debug(f"[MOCK] GitHub add workflows: {repo_name}")

    async def add_team_to_repo(
        self, repo_name: str, team_slug: str, permission: str = "push"
    ) -> None:
        logger.debug(f"[MOCK] GitHub add team {team_slug} → {repo_name}")

    async def delete_repo(self, repo_name: str) -> None:
        logger.debug(f"[MOCK] GitHub delete_repo: {repo_name}")
        self._deleted_repos.append(repo_name)

    async def check_health(self) -> bool:
        return True


class GitHubAdapter:
    """
    GitHub adapter real usando httpx.
    Requiere GITHUB_TOKEN con permisos repo + admin:org.
    """

    def __init__(self, token: str, org: str, api_url: str = "https://api.github.com"):
        self.token = token
        self.org = org
        self.api_url = api_url
        self._client: Any = None

    async def __aenter__(self) -> "GitHubAdapter":
        try:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github.v3+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
        except ImportError:
            raise ImportError("httpx es necesario para el adapter real de GitHub")
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    async def _req(self, method: str, path: str, **kwargs) -> dict:
        r = await self._client.request(method, path, **kwargs)
        if r.status_code == 429:
            raise GitHubRateLimitError("GitHub rate limit exceeded")
        if r.status_code >= 400:
            raise GitHubError(
                f"GitHub API error {r.status_code}",
                detail=r.text[:500],
            )
        if r.status_code == 204:
            return {}
        return r.json()

    async def create_repo(
        self, name: str, description: str = "", private: bool = True
    ) -> GitHubRepoResult:
        data = await self._req("POST", f"/orgs/{self.org}/repos", json={
            "name": name,
            "description": description,
            "private": private,
            "auto_init": True,
            "delete_branch_on_merge": True,
            "allow_squash_merge": True,
            "allow_merge_commit": False,
        })
        return GitHubRepoResult(
            name=data["name"],
            html_url=data["html_url"],
            clone_url=data["clone_url"],
            ssh_url=data.get("ssh_url", ""),
        )

    async def configure_branch_protection(
        self, repo_name: str, branch: str = "main"
    ) -> None:
        await self._req(
            "PUT",
            f"/repos/{self.org}/{repo_name}/branches/{branch}/protection",
            json={
                "required_status_checks": {"strict": True, "contexts": ["CI / test"]},
                "enforce_admins": True,
                "required_pull_request_reviews": {
                    "required_approving_review_count": 1,
                    "dismiss_stale_reviews": True,
                },
                "restrictions": None,
                "allow_force_pushes": False,
                "allow_deletions": False,
            },
        )

    async def add_actions_workflows(self, repo_name: str) -> None:
        for filename, content in [
            (".github/workflows/ci.yml", _CI_TEMPLATE),
            (".github/workflows/deploy.yml", _DEPLOY_TEMPLATE),
        ]:
            encoded = base64.b64encode(content.encode()).decode()
            await self._req(
                "PUT",
                f"/repos/{self.org}/{repo_name}/contents/{filename}",
                json={"message": f"chore: add {filename}", "content": encoded},
            )

    async def add_team_to_repo(
        self, repo_name: str, team_slug: str, permission: str = "push"
    ) -> None:
        await self._req(
            "PUT",
            f"/orgs/{self.org}/teams/{team_slug}/repos/{self.org}/{repo_name}",
            json={"permission": permission},
        )

    async def delete_repo(self, repo_name: str) -> None:
        await self._req("DELETE", f"/repos/{self.org}/{repo_name}")

    async def check_health(self) -> bool:
        try:
            await self._req("GET", "/rate_limit")
            return True
        except Exception:
            return False
