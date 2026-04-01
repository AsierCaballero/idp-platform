"""
idp/cli/main.py
CLI del IDP Platform — idp project create/list/status/delete
                        idp team create/list
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Optional

try:
    import httpx
    import typer
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

if HAS_DEPS:
    app     = typer.Typer(name="idp", help="🏗️  IDP Platform CLI", no_args_is_help=True)
    proj    = typer.Typer(help="Gestión de proyectos", no_args_is_help=True)
    team    = typer.Typer(help="Gestión de equipos",   no_args_is_help=True)
    app.add_typer(proj, name="project")
    app.add_typer(team, name="team")
    console = Console()
    err     = Console(stderr=True, style="bold red")

    def _api() -> str:
        return os.getenv("IDP_API_URL", "http://localhost:8000/api/v1")

    def _client() -> "httpx.AsyncClient":
        hdrs = {"Content-Type": "application/json"}
        if key := os.getenv("IDP_API_KEY"):
            hdrs["X-API-Key"] = key
        return httpx.AsyncClient(base_url=_api(), headers=hdrs, timeout=30.0)

    def _run(coro):
        return asyncio.run(coro)

    def _color(s: str) -> str:
        return {"active": "green", "pending": "yellow", "provisioning": "blue",
                "failed": "red", "deleted": "grey50"}.get(s, "white")

    # ── project create ────────────────────────────────────────────
    @proj.command("create")
    def project_create(
        name:    str           = typer.Argument(...),
        team_id: str           = typer.Option(..., "--team", "-t"),
        desc:    str           = typer.Option("", "--desc", "-d"),
        envs:    str           = typer.Option("dev", "--envs", "-e",
                                              help="dev,staging,prod"),
        owner:   Optional[str] = typer.Option(None, "--owner", "-o"),
        as_json: bool          = typer.Option(False, "--json"),
    ):
        """Crea un proyecto y lanza el provisioning."""
        payload = {
            "name": name, "team_id": team_id, "description": desc,
            "environments": [{"tier": t.strip()} for t in envs.split(",")],
        }
        if owner:
            payload["owner_email"] = owner

        async def _go():
            async with _client() as c:
                r = await c.post("/projects", json=payload)
                if r.status_code not in (200, 201, 202):
                    err.print(f"Error {r.status_code}: {r.text}"); raise typer.Exit(1)
                return r.json()

        with Progress(SpinnerColumn(), TextColumn("Creando..."), transient=True):
            data = _run(_go())

        if as_json:
            console.print_json(json.dumps(data))
        else:
            console.print(f"[green]✓[/green] Proyecto [bold]{name}[/bold] creado — ID: {data['id']}")
            console.print(f"  [dim]idp project status {data['id']}[/dim]")

    # ── project list ──────────────────────────────────────────────
    @proj.command("list")
    def project_list(as_json: bool = typer.Option(False, "--json")):
        """Lista todos los proyectos."""
        async def _go():
            async with _client() as c:
                r = await c.get("/projects"); r.raise_for_status(); return r.json()

        data = _run(_go())
        if as_json:
            console.print_json(json.dumps(data)); return

        t = Table(title=f"Proyectos ({data['total']})")
        for col in ["ID", "Name", "Status", "GitHub", "K8s NS", "Created"]:
            t.add_column(col)
        for p in data["items"]:
            s = p["status"]
            t.add_row(
                p["id"][:8]+"…", p["name"],
                f"[{_color(s)}]{s}[/{_color(s)}]",
                "✓" if p.get("github_repo_url") else "—",
                p.get("k8s_namespace") or "—",
                p["created_at"][:10],
            )
        console.print(t)

    # ── project status ────────────────────────────────────────────
    @proj.command("status")
    def project_status(project_id: str = typer.Argument(...)):
        """Estado de provisioning."""
        async def _go():
            async with _client() as c:
                r = await c.get(f"/projects/{project_id}/status")
                if r.status_code == 404:
                    err.print("Proyecto no encontrado"); raise typer.Exit(1)
                r.raise_for_status(); return r.json()

        d = _run(_go())
        s = d["status"]; c2 = _color(s)
        console.print(f"\nStatus: [{c2}]{s}[/{c2}]")
        t = Table(title="Steps")
        t.add_column("Step"); t.add_column("Status")
        icons = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌", "skipped": "⏭️"}
        for step, st in (d.get("steps") or {}).items():
            t.add_row(step, f"{icons.get(st,'?')} {st}")
        console.print(t)
        if d.get("error_message"):
            console.print(f"[red]Error: {d['error_message']}[/red]")

    # ── project delete ────────────────────────────────────────────
    @proj.command("delete")
    def project_delete(
        project_id: str  = typer.Argument(...),
        yes:        bool = typer.Option(False, "--yes", "-y"),
    ):
        """Elimina un proyecto y sus recursos."""
        if not yes:
            typer.confirm(f"¿Eliminar {project_id} y TODOS sus recursos?", abort=True)

        async def _go():
            async with _client() as c:
                r = await c.delete(f"/projects/{project_id}")
                if r.status_code not in (200, 204):
                    err.print(f"Error {r.status_code}: {r.text}"); raise typer.Exit(1)

        _run(_go())
        console.print(f"[green]✓[/green] Proyecto {project_id} eliminado.")

    # ── team create ───────────────────────────────────────────────
    @team.command("create")
    def team_create(
        name:        str           = typer.Argument(...),
        email:       Optional[str] = typer.Option(None, "--email"),
        slack:       Optional[str] = typer.Option(None, "--slack"),
        github_team: Optional[str] = typer.Option(None, "--github-team"),
        as_json:     bool          = typer.Option(False, "--json"),
    ):
        """Crea un equipo."""
        payload = {"name": name}
        if email:        payload["email"] = email
        if slack:        payload["slack_channel"] = slack
        if github_team:  payload["github_team"] = github_team

        async def _go():
            async with _client() as c:
                r = await c.post("/teams", json=payload)
                if r.status_code not in (200, 201):
                    err.print(f"Error {r.status_code}: {r.text}"); raise typer.Exit(1)
                return r.json()

        data = _run(_go())
        if as_json:
            console.print_json(json.dumps(data))
        else:
            console.print(f"[green]✓[/green] Equipo [bold]{data['name']}[/bold] — ID: {data['id']}")

    # ── team list ─────────────────────────────────────────────────
    @team.command("list")
    def team_list(as_json: bool = typer.Option(False, "--json")):
        """Lista todos los equipos."""
        async def _go():
            async with _client() as c:
                r = await c.get("/teams"); r.raise_for_status(); return r.json()

        teams = _run(_go())
        if as_json:
            console.print_json(json.dumps(teams)); return

        t = Table(title="Equipos")
        for col in ["ID", "Name", "Email", "Slack"]:
            t.add_column(col)
        for tm in teams:
            t.add_row(tm["id"][:8]+"…", tm["name"],
                      tm.get("email") or "—", tm.get("slack_channel") or "—")
        console.print(t)


def main():
    if not HAS_DEPS:
        print("Instala dependencias: pip install typer rich httpx")
        sys.exit(1)
    app()

if __name__ == "__main__":
    main()
