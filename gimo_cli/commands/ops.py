"""Operational commands: diff, rollback, config, audit."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.api import api_request
from gimo_cli.config import YAML_AVAILABLE, yaml, load_config, project_root, save_config
from gimo_cli.stream import emit_output, git_command


def _detect_default_branch() -> str:
    """Detect the repository's default branch (main/master/etc).

    Strategy: git symbolic-ref → main fallback → master fallback.
    """
    result = git_command(["symbolic-ref", "refs/remotes/origin/HEAD"])
    if result.returncode == 0:
        ref = result.stdout.strip()
        # refs/remotes/origin/main → main
        return ref.rsplit("/", 1)[-1] if "/" in ref else ref
    # Fallback: check if main or master exists locally
    for branch in ("main", "master"):
        check = git_command(["rev-parse", "--verify", branch])
        if check.returncode == 0:
            return branch
    return "main"


def _require_git_repo() -> None:
    probe = git_command(["rev-parse", "--is-inside-work-tree"])
    if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
        console.print("[red]Current workspace is not a git repository.[/red]")
        raise typer.Exit(1)


def _ensure_clean_worktree() -> None:
    st = git_command(["status", "--porcelain"])
    if st.returncode != 0:
        console.print(f"[red]Unable to inspect git status:[/red] {st.stderr.strip() or st.stdout.strip()}")
        raise typer.Exit(1)
    if st.stdout.strip():
        console.print("[red]Rollback requires a clean worktree. Commit or stash pending changes first.[/red]")
        raise typer.Exit(1)


@app.command()
def diff(
    base: str = typer.Option("", help="Base git ref (auto-detects default branch if omitted)."),
    head: str = typer.Option("HEAD", help="Head git ref."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show backend diff summary for the active repository."""
    if not base:
        base = _detect_default_branch()
    cfg = load_config()
    status_code, payload = api_request(cfg, "GET", "/ops/files/diff", params={"base": base, "head": head})
    if status_code != 200:
        console.print(f"[red]Diff failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output({"base": base, "head": head, "diff": payload}, json_output=True)
        return
    if isinstance(payload, (dict, list)):
        console.print_json(data=payload)
    elif payload:
        console.print(str(payload))
    else:
        console.print("[dim]No diff output.[/dim]")


@app.command()
def rollback(
    commit_hash: str | None = typer.Argument(None, help="Commit to revert or reset to."),
    mode: str = typer.Option("revert", "--mode", help="Rollback mode: revert, soft-reset, hard-reset."),
    mainline: int | None = typer.Option(None, "--mainline", min=1, help="Parent number for reverting a merge commit."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Rollback the last AI-generated change using safe git defaults."""
    load_config()
    _require_git_repo()
    _ensure_clean_worktree()

    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"revert", "soft-reset", "hard-reset"}:
        console.print("[red]Invalid rollback mode. Use revert, soft-reset, or hard-reset.[/red]")
        raise typer.Exit(1)

    default_target = "HEAD" if normalized_mode == "revert" else "HEAD~1"
    target = (commit_hash or default_target).strip()

    effective_mainline = mainline
    if normalized_mode == "revert" and mainline is None:
        parents = git_command(["rev-list", "--parents", "-n", "1", target])
        if parents.returncode == 0:
            tokens = parents.stdout.strip().split()
            if len(tokens) > 2:
                effective_mainline = 1

    if not yes and sys.stdin.isatty():
        descriptor = f"{normalized_mode} {target}"
        if effective_mainline is not None and normalized_mode == "revert":
            descriptor += f" (mainline {effective_mainline})"
        if not typer.confirm(f"Proceed with {descriptor}?", default=False):
            console.print("[yellow]Rollback aborted by user.[/yellow]")
            raise typer.Exit(1)

    if normalized_mode == "revert":
        git_args = ["revert", "--no-edit"]
        if effective_mainline is not None:
            git_args.extend(["-m", str(effective_mainline)])
        git_args.append(target)
    elif normalized_mode == "soft-reset":
        git_args = ["reset", "--soft", target]
    else:
        git_args = ["reset", "--hard", target]

    proc = git_command(git_args)
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        console.print(f"[red]Rollback failed:[/red] {message}")
        raise typer.Exit(1)

    head_proc = git_command(["rev-parse", "--short", "HEAD"])
    payload = {
        "mode": normalized_mode,
        "target": target,
        "mainline": effective_mainline,
        "head": head_proc.stdout.strip() if head_proc.returncode == 0 else None,
        "stdout": proc.stdout.strip(),
    }

    if json_output:
        emit_output(payload, json_output=True)
        return

    console.print(
        Panel(
            "\n".join([
                "[bold green]Rollback completed.[/bold green]",
                f"Mode: {normalized_mode}",
                f"Target: {target}",
                f"HEAD: {payload.get('head') or 'unknown'}",
            ]),
            title="GIMO Rollback",
            border_style="yellow",
        )
    )


@app.command("config")
def config_cmd(
    show: bool = typer.Option(False, "--show", help="Print the current local CLI config."),
    api_url: str | None = typer.Option(None, "--api-url", help="Set backend base URL."),
    model: str | None = typer.Option(None, "--model", help="Set preferred model."),
    budget: float | None = typer.Option(None, "--budget", help="Set budget limit in USD."),
    verbose: bool | None = typer.Option(None, "--verbose/--no-verbose", help="Set verbose mode."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Read or update local .gimo/config.yaml."""
    config_data = load_config()
    changed = False

    if api_url is not None:
        config_data.setdefault("api", {})["base_url"] = api_url.rstrip("/")
        changed = True
    if model is not None:
        config_data.setdefault("orchestrator", {})["preferred_model"] = model
        changed = True
    if budget is not None:
        config_data.setdefault("orchestrator", {})["budget_limit_usd"] = budget
        changed = True
    if verbose is not None:
        config_data.setdefault("orchestrator", {})["verbose"] = bool(verbose)
        changed = True

    if changed:
        save_config(config_data)

    if json_output:
        emit_output(config_data, json_output=True)
        return

    if show or changed:
        if YAML_AVAILABLE and yaml:
            console.print(Panel(yaml.safe_dump(config_data, sort_keys=False), title="GIMO Config", border_style="cyan"))
        else:
            import json
            console.print(Panel(json.dumps(config_data, indent=2), title="GIMO Config", border_style="cyan"))
        return

    console.print("[yellow]No changes requested. Use --show to print config.[/yellow]")


@app.command()
def audit(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Aggregate lightweight audit signals from backend endpoints."""
    cfg = load_config()
    endpoints = {
        "alerts": ("/ops/observability/alerts", None),
        "dependencies": ("/ops/system/dependencies", None),
        "audit_tail": ("/ui/audit", {"limit": 20}),
    }
    result: dict[str, Any] = {}

    for key, (path, params) in endpoints.items():
        status_code, payload = api_request(cfg, "GET", path, params=params)
        result[key] = {"status_code": status_code, "payload": payload}

    if json_output:
        emit_output(result, json_output=True)
        return

    table = Table(title="GIMO Audit", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Summary", style="white")

    alerts_payload = result["alerts"]["payload"] if isinstance(result["alerts"]["payload"], dict) else {}
    deps_payload = result["dependencies"]["payload"] if isinstance(result["dependencies"]["payload"], dict) else {}
    audit_payload = result["audit_tail"]["payload"] if isinstance(result["audit_tail"]["payload"], dict) else {}

    table.add_row("Alerts", str(result["alerts"]["status_code"]), f"{alerts_payload.get('count', 'n/a')} alerts")
    table.add_row("Dependencies", str(result["dependencies"]["status_code"]), f"{deps_payload.get('count', 'n/a')} dependencies")
    lines = audit_payload.get("lines") or []
    last_line = lines[-1] if lines else "no audit lines"
    table.add_row("Audit Tail", str(result["audit_tail"]["status_code"]), str(last_line)[:120])
    console.print(table)


@app.command()
def graph(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Display the orchestration graph."""
    cfg = load_config()
    status_code, payload = api_request(cfg, "GET", "/ops/graph")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    console.print_json(data=payload) if isinstance(payload, (dict, list)) else console.print(f"[dim]{payload}[/dim]")


@app.command()
def capabilities(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Display server capabilities."""
    cfg = load_config()
    status_code, payload = api_request(cfg, "GET", "/ops/capabilities")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    console.print_json(data=payload) if isinstance(payload, (dict, list)) else console.print(f"[dim]{payload}[/dim]")
