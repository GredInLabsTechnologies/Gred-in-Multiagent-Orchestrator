from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

DEFAULT_API_BASE_URL = os.environ.get("GIMO_API_URL") or os.environ.get("ORCH_BASE_URL") or "http://127.0.0.1:9325"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_WATCH_TIMEOUT_SECONDS = 30.0
ACTIVE_RUN_STATUSES = {
    "pending",
    "running",
    "awaiting_subagents",
    "awaiting_review",
    "MERGE_LOCKED",
    "WORKER_CRASHED_RECOVERABLE",
    "HUMAN_APPROVAL_REQUIRED",
}
TERMINAL_RUN_STATUSES = {
    "done",
    "error",
    "cancelled",
    "MERGE_CONFLICT",
    "VALIDATION_FAILED_TESTS",
    "VALIDATION_FAILED_LINT",
    "RISK_SCORE_TOO_HIGH",
    "BASELINE_TAMPER_DETECTED",
    "PIPELINE_TIMEOUT",
    "WORKTREE_CORRUPTED",
    "ROLLBACK_EXECUTED",
}

app = typer.Typer(
    name="gimo",
    help="GIMO: Generalized Intelligent Multi-agent Orchestrator",
    add_completion=True,
    invoke_without_command=True,
)
console = Console()


def _project_root() -> Path:
    return Path.cwd()


def _gimo_dir() -> Path:
    return _project_root() / ".gimo"


def _config_path() -> Path:
    return _gimo_dir() / "config.yaml"


def _plans_dir() -> Path:
    return _gimo_dir() / "plans"


def _history_dir() -> Path:
    return _gimo_dir() / "history"


def _runs_dir() -> Path:
    return _gimo_dir() / "runs"


def _ensure_project_dirs() -> None:
    for path in (_gimo_dir(), _plans_dir(), _history_dir(), _runs_dir()):
        path.mkdir(parents=True, exist_ok=True)


def _default_config() -> dict[str, Any]:
    return {
        "orchestrator": {
            "preferred_model": "claude-3-5-sonnet-20241022",
            "budget_limit_usd": 10.0,
            "verbose": False,
            "auto_run_eligible": True,
        },
        "repository": {
            "name": _project_root().name,
            "workspace_root": str(_project_root()),
            "index_depth": 3,
            "exclude_dirs": [
                ".git",
                "node_modules",
                ".venv",
                "__pycache__",
                "dist",
                "build",
            ],
        },
        "api": {
            "base_url": DEFAULT_API_BASE_URL,
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        "providers": {
            "anthropic": {"enabled": True},
            "openai": {"enabled": False},
        },
    }


def _save_config(config: dict[str, Any]) -> None:
    _ensure_project_dirs()
    _config_path().write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def _load_config() -> dict[str, Any]:
    _ensure_project_dirs()
    if not _config_path().exists():
        console.print("[red]Project not initialized. Run 'gimo init' first.[/red]")
        raise typer.Exit(1)
    content = yaml.safe_load(_config_path().read_text(encoding="utf-8")) or {}
    if not isinstance(content, dict):
        console.print("[red]Invalid .gimo/config.yaml format.[/red]")
        raise typer.Exit(1)
    return content


def _read_token_from_env_file() -> str | None:
    env_path = _project_root() / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key.strip() in {"GIMO_TOKEN", "ORCH_TOKEN"}:
            return value.strip().strip('"').strip("'")
    return None


def _resolve_token() -> str | None:
    for env_name in ("GIMO_TOKEN", "ORCH_TOKEN"):
        token = os.environ.get(env_name)
        if token:
            return token.strip()

    token_path = _project_root() / "tools" / "gimo_server" / ".orch_token"
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()

    return _read_token_from_env_file()


def _api_settings(config: dict[str, Any]) -> tuple[str, float]:
    api_cfg = dict(config.get("api") or {})
    base_url = str(api_cfg.get("base_url") or DEFAULT_API_BASE_URL).rstrip("/")
    timeout_seconds = float(api_cfg.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    return base_url, timeout_seconds


def _api_request(
    config: dict[str, Any],
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    base_url, timeout_seconds = _api_settings(config)
    token = _resolve_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{base_url}{path}"

    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.request(method, url, params=params, headers=headers)

    payload: Any
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    return response.status_code, payload


def _stream_events(
    config: dict[str, Any],
    *,
    path: str = "/ops/stream",
    timeout_seconds: float = DEFAULT_WATCH_TIMEOUT_SECONDS,
):
    base_url, connect_timeout_seconds = _api_settings(config)
    token = _resolve_token()
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{base_url}{path}"
    timeout = httpx.Timeout(
        connect=connect_timeout_seconds,
        read=timeout_seconds if timeout_seconds > 0 else None,
        write=connect_timeout_seconds,
        pool=connect_timeout_seconds,
    )

    with httpx.Client(timeout=timeout) as client:
        with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    yield raw


def _emit_output(payload: Any, *, json_output: bool) -> None:
    if json_output:
        console.print_json(data=payload)
        return
    console.print(payload)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _latest_run_summary(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runs:
        return None
    return runs[0]


def _terminal_status(status: str) -> bool:
    return status in TERMINAL_RUN_STATUSES or (status and status not in ACTIVE_RUN_STATUSES)


def _poll_run(
    config: dict[str, Any],
    run_id: str,
    *,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    announce: bool = True,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds if timeout_seconds > 0 else None
    latest_payload: dict[str, Any] | None = None
    last_snapshot: tuple[str, str] | None = None

    while True:
        status_code, payload = _api_request(config, "GET", f"/ops/runs/{run_id}")
        if status_code != 200 or not isinstance(payload, dict):
            return {
                "id": run_id,
                "status": "unknown",
                "poll_error": payload,
                "poll_http_status": status_code,
            }

        latest_payload = payload
        status = str(payload.get("status") or "unknown")
        stage = str(payload.get("stage") or "")
        snapshot = (status, stage)
        if announce and snapshot != last_snapshot:
            stage_suffix = f" [{stage}]" if stage else ""
            console.print(f"[cyan]Run {run_id}[/cyan] -> [bold]{status}[/bold]{stage_suffix}")
            last_snapshot = snapshot

        if _terminal_status(status):
            return latest_payload

        if deadline is not None and time.time() >= deadline:
            latest_payload["poll_timeout"] = True
            return latest_payload

        time.sleep(max(poll_interval_seconds, 0.1))


def _git_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=_project_root(),
        text=True,
        capture_output=True,
        check=False,
    )


def _require_git_repo() -> None:
    probe = _git_command(["rev-parse", "--is-inside-work-tree"])
    if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
        console.print("[red]Current workspace is not a git repository.[/red]")
        raise typer.Exit(1)


def _ensure_clean_worktree() -> None:
    status = _git_command(["status", "--porcelain"])
    if status.returncode != 0:
        console.print(f"[red]Unable to inspect git status:[/red] {status.stderr.strip() or status.stdout.strip()}")
        raise typer.Exit(1)
    if status.stdout.strip():
        console.print("[red]Rollback requires a clean worktree. Commit or stash pending changes first.[/red]")
        raise typer.Exit(1)


def _default_rollback_target(mode: str) -> str:
    return "HEAD" if mode == "revert" else "HEAD~1"


def _maybe_merge_mainline(commit_hash: str, mainline: int | None) -> int | None:
    if mainline is not None:
        return mainline
    parents = _git_command(["rev-list", "--parents", "-n", "1", commit_hash])
    if parents.returncode != 0:
        return mainline
    tokens = parents.stdout.strip().split()
    if len(tokens) > 2:
        return 1
    return mainline


def _preflight_check(config: dict[str, Any]) -> tuple[bool, str]:
    """Check server health and orchestrator configuration.

    Returns (ok, error_message).
    """
    try:
        status_code, _ = _api_request(config, "GET", "/health")
        if status_code != 200:
            return False, f"Server returned HTTP {status_code}. Is GIMO running?"
    except Exception as exc:
        return False, f"Cannot reach GIMO server: {exc}\nStart it with: GIMO_LAUNCHER.cmd"

    try:
        status_code, payload = _api_request(config, "GET", "/ops/providers")
        if status_code != 200:
            return False, "Cannot fetch provider config."
        if isinstance(payload, dict):
            orch_provider = payload.get("orchestrator_provider") or payload.get("active")
            if not orch_provider:
                return False, "No orchestrator provider configured.\nConfigure one in the UI: Settings > Providers"
    except Exception as exc:
        return False, f"Provider check failed: {exc}"

    return True, ""


def _interactive_chat(config: dict[str, Any]) -> None:
    """Run the interactive agentic chat session."""
    from gimo_cli_renderer import ChatRenderer

    renderer = ChatRenderer(console)
    workspace_root = str(_project_root())

    # Preflight
    ok, err = _preflight_check(config)
    if not ok:
        renderer.render_preflight_error(err, hint="Run 'gimo status' for diagnostics.")
        raise typer.Exit(1)

    # Fetch provider info for header
    _, providers_payload = _api_request(config, "GET", "/ops/providers")
    provider_id = "unknown"
    model = "unknown"
    if isinstance(providers_payload, dict):
        provider_id = str(providers_payload.get("orchestrator_provider") or providers_payload.get("active") or "unknown")
        model = str(providers_payload.get("orchestrator_model") or providers_payload.get("model_id") or "unknown")

    # Create thread
    with console.status("[dim]Creating session...[/dim]"):
        status_code, thread_payload = _api_request(
            config,
            "POST",
            "/ops/threads",
            params={"workspace_root": workspace_root, "title": "CLI Agentic Session"},
        )
    if status_code != 201 or not isinstance(thread_payload, dict):
        renderer.render_error(f"Failed to create thread ({status_code}): {thread_payload}")
        raise typer.Exit(1)

    thread_id = str(thread_payload.get("id") or "")
    if not thread_id:
        renderer.render_error("No thread id returned.")
        raise typer.Exit(1)

    # Session header
    renderer.render_session_header(
        provider_id=provider_id,
        model=model,
        workspace=workspace_root,
        thread_id=thread_id,
    )

    # History file
    history_path = _history_dir() / f"{thread_id}.log"
    _ensure_project_dirs()

    # Main loop
    while True:
        user_input = renderer.get_user_input()
        if not user_input:
            continue
        if user_input.lower() in {"/exit", "/quit"}:
            console.print("[dim]Session ended.[/dim]")
            break

        # Save to history
        with history_path.open("a", encoding="utf-8") as f:
            f.write(f"> {user_input}\n")

        # Call chat endpoint
        with renderer.render_thinking():
            try:
                base_url, timeout_seconds = _api_settings(config)
                token = _resolve_token()
                headers = {"Authorization": f"Bearer {token}"} if token else {}

                with httpx.Client(timeout=max(timeout_seconds, 300.0)) as client:
                    response = client.post(
                        f"{base_url}/ops/threads/{thread_id}/chat",
                        params={"content": user_input},
                        headers=headers,
                    )

                if response.status_code != 200:
                    renderer.render_error(f"HTTP {response.status_code}: {response.text[:200]}")
                    continue

                payload = response.json()
            except httpx.TimeoutException:
                renderer.render_error("Request timed out. The LLM may need more time.")
                continue
            except Exception as exc:
                renderer.render_error(f"Request failed: {exc}")
                continue

        # Render tool calls
        tool_calls = payload.get("tool_calls", [])
        if tool_calls:
            renderer.render_tool_calls(tool_calls)

        # Render response
        chat_response = payload.get("response", "")
        renderer.render_response(chat_response)

        # Render footer
        usage = payload.get("usage", {})
        renderer.render_footer(usage)

        # Save to history
        with history_path.open("a", encoding="utf-8") as f:
            f.write(f"{chat_response}\n---\n")


@app.callback()
def main(ctx: typer.Context) -> None:
    """GIMO: Generalized Intelligent Multi-agent Orchestrator.

    Run without a subcommand to start an interactive agentic chat session.
    """
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand -> interactive chat
    try:
        config = _load_config()
    except typer.Exit:
        # Not initialized: auto-init
        _ensure_project_dirs()
        if not _config_path().exists():
            _save_config(_default_config())
        config = _load_config()

    _interactive_chat(config)


@app.command()
def init(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Initialize the current workspace for GIMO CLI usage."""
    _ensure_project_dirs()

    if _config_path().exists():
        payload = {
            "initialized": True,
            "config_path": str(_config_path()),
            "plans_dir": str(_plans_dir()),
            "history_dir": str(_history_dir()),
            "runs_dir": str(_runs_dir()),
            "already_exists": True,
        }
        if json_output:
            _emit_output(payload, json_output=True)
            return
        console.print(Panel(f"Config already exists at {_config_path()}", title="GIMO Init", border_style="yellow"))
        return

    config = _default_config()
    _save_config(config)
    payload = {
        "initialized": True,
        "config_path": str(_config_path()),
        "plans_dir": str(_plans_dir()),
        "history_dir": str(_history_dir()),
        "runs_dir": str(_runs_dir()),
        "already_exists": False,
    }
    if json_output:
        _emit_output(payload, json_output=True)
        return
    console.print(
        Panel(
            "\n".join(
                [
                    "[bold green]Workspace initialized.[/bold green]",
                    f"Config: {_config_path()}",
                    f"Plans: {_plans_dir()}",
                    f"History: {_history_dir()}",
                    f"Runs: {_runs_dir()}",
                ]
            ),
            title="GIMO Init",
            border_style="green",
        )
    )


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show local project state plus backend run status."""
    table = Table(title="GIMO Status", show_header=False)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="magenta")
    result_payload: dict[str, Any] = {
        "workspace_initialized": False,
        "backend_online": False,
    }

    try:
        config = _load_config()
    except typer.Exit:
        config = {}
        table.add_row("Workspace", "[red]Not initialized[/red]")
    else:
        repo_cfg = dict(config.get("repository") or {})
        orch_cfg = dict(config.get("orchestrator") or {})
        result_payload["workspace_initialized"] = True
        result_payload["workspace"] = str(repo_cfg.get("name") or _project_root().name)
        result_payload["preferred_model"] = str(orch_cfg.get("preferred_model") or "n/a")
        result_payload["budget_limit_usd"] = orch_cfg.get("budget_limit_usd", "n/a")
        table.add_row("Workspace", str(repo_cfg.get("name") or _project_root().name))
        table.add_row("Preferred Model", str(orch_cfg.get("preferred_model") or "n/a"))
        table.add_row("Budget Limit", f"${orch_cfg.get('budget_limit_usd', 'n/a')}")

    if not config:
        if json_output:
            _emit_output(result_payload, json_output=True)
            return
        console.print(table)
        return

    try:
        status_code, status_payload = _api_request(config, "GET", "/status")
        runs_code, runs_payload = _api_request(config, "GET", "/ops/runs")
    except Exception as exc:
        result_payload["backend_error"] = str(exc)
        table.add_row("Backend", f"[red]Offline[/red] ({exc})")
        if json_output:
            _emit_output(result_payload, json_output=True)
            return
        console.print(table)
        return

    if status_code == 200 and isinstance(status_payload, dict):
        result_payload["backend_online"] = True
        result_payload["version"] = str(status_payload.get("version") or "unknown")
        result_payload["uptime_seconds"] = status_payload.get("uptime_seconds", 0)
        table.add_row("Backend", "[green]ONLINE[/green]")
        table.add_row("Version", str(status_payload.get("version") or "unknown"))
        table.add_row("Uptime", f"{status_payload.get('uptime_seconds', 0)}s")
    else:
        result_payload["backend_http_status"] = status_code
        table.add_row("Backend", f"[red]HTTP {status_code}[/red]")

    runs = runs_payload if runs_code == 200 and isinstance(runs_payload, list) else []
    active_runs = [run for run in runs if str(run.get("status") or "") in ACTIVE_RUN_STATUSES]
    latest = _latest_run_summary(runs)
    result_payload["runs_total"] = len(runs)
    result_payload["runs_active"] = len(active_runs)
    result_payload["latest_run"] = latest

    table.add_row("Runs (total)", str(len(runs)))
    table.add_row("Runs (active)", str(len(active_runs)))
    if latest:
        table.add_row("Latest Run", f"{latest.get('id')} ({latest.get('status')})")

    supplemental_endpoints = {
        "drafts": "/ops/drafts",
        "approved": "/ops/approved",
        "health": "/health/deep",
        "mastery": "/ops/mastery/status",
        "realtime": "/ops/realtime/metrics",
    }
    supplemental: dict[str, Any] = {}

    for key, path in supplemental_endpoints.items():
        try:
            endpoint_status, endpoint_payload = _api_request(config, "GET", path)
        except Exception as exc:
            supplemental[key] = {"status_code": None, "error": str(exc)}
            continue
        supplemental[key] = {"status_code": endpoint_status, "payload": endpoint_payload}

    result_payload["supplemental"] = supplemental

    drafts_payload = supplemental.get("drafts", {}).get("payload") if isinstance(supplemental.get("drafts"), dict) else None
    if supplemental.get("drafts", {}).get("status_code") == 200 and isinstance(drafts_payload, list):
        result_payload["drafts_total"] = len(drafts_payload)
        table.add_row("Drafts", str(len(drafts_payload)))
        if drafts_payload:
            table.add_row("Latest Draft", str(drafts_payload[0].get("id") or "unknown"))

    approved_payload = supplemental.get("approved", {}).get("payload") if isinstance(supplemental.get("approved"), dict) else None
    if supplemental.get("approved", {}).get("status_code") == 200 and isinstance(approved_payload, list):
        result_payload["approved_total"] = len(approved_payload)
        table.add_row("Approved", str(len(approved_payload)))
        if approved_payload:
            table.add_row("Latest Approved", str(approved_payload[0].get("id") or "unknown"))

    health_payload = supplemental.get("health", {}).get("payload") if isinstance(supplemental.get("health"), dict) else None
    if supplemental.get("health", {}).get("status_code") == 200 and isinstance(health_payload, dict):
        health_status = str(health_payload.get("status") or "unknown")
        checks = dict(health_payload.get("checks") or {})
        provider_health = checks.get("provider_health", "n/a")
        table.add_row("Health", health_status)
        table.add_row("Provider", str(provider_health))

    mastery_payload = supplemental.get("mastery", {}).get("payload") if isinstance(supplemental.get("mastery"), dict) else None
    if supplemental.get("mastery", {}).get("status_code") == 200 and isinstance(mastery_payload, dict):
        table.add_row("Hardware", str(mastery_payload.get("hardware_state") or "unknown"))
        savings = mastery_payload.get("total_savings_usd")
        if savings is not None:
            table.add_row("Savings (30d)", f"${float(savings):.2f}")
        efficiency = mastery_payload.get("efficiency_score")
        if efficiency is not None:
            table.add_row("Efficiency", str(efficiency))

    realtime_payload = supplemental.get("realtime", {}).get("payload") if isinstance(supplemental.get("realtime"), dict) else None
    if supplemental.get("realtime", {}).get("status_code") == 200 and isinstance(realtime_payload, dict):
        if "published" in realtime_payload:
            table.add_row("Events Published", str(realtime_payload.get("published")))
        if "dropped" in realtime_payload:
            table.add_row("Events Dropped", str(realtime_payload.get("dropped")))

    if json_output:
        _emit_output(result_payload, json_output=True)
        return
    console.print(table)


@app.command()
def plan(
    description: str = typer.Argument(..., help="Goal or task description"),
    confirm: bool = typer.Option(True, "--confirm/--no-confirm", help="Confirm local persistence when interactive."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Create a structured draft plan and persist it under .gimo/plans."""
    config = _load_config()

    with console.status("[bold green]Generating plan..."):
        status_code, payload = _api_request(
            config,
            "POST",
            "/ops/generate-plan",
            params={"prompt": description},
        )

    if status_code != 201 or not isinstance(payload, dict):
        console.print(f"[red]Plan generation failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)

    draft_id = str(payload.get("id") or "")
    if not draft_id:
        console.print("[red]Backend returned a draft without id.[/red]")
        raise typer.Exit(1)

    should_save = True
    if confirm and sys.stdin.isatty():
        preview = payload.get("content")
        if isinstance(preview, str) and preview.strip():
            console.print(Panel(preview[:800] + ("..." if len(preview) > 800 else ""), title="Plan Preview", border_style="cyan"))
        should_save = typer.confirm("Save this draft under .gimo/plans?", default=True)

    draft_path = _plans_dir() / f"{draft_id}.json"
    if should_save:
        _write_json(draft_path, payload)

    if json_output:
        _emit_output(
            {"draft": payload, "saved_path": str(draft_path) if should_save else None, "saved": should_save},
            json_output=True,
        )
        return

    console.print(
        Panel(
            "\n".join(
                [
                    "[bold green]Plan generated successfully.[/bold green]",
                    f"Draft ID: [bold]{draft_id}[/bold]",
                    f"Status: {payload.get('status', 'draft')}",
                    f"Saved: {draft_path if should_save else 'not persisted locally'}",
                ]
            ),
            title="GIMO Plan",
            border_style="green",
        )
    )

    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        preview = content[:600]
        if len(content) > 600:
            preview += "..."
        console.print(preview)


@app.command()
def run(
    plan_id: str = typer.Argument(..., help="Draft id to approve and execute"),
    auto: bool = typer.Option(
        True,
        "--auto/--approve-only",
        help="Spawn the backend run immediately after approval.",
    ),
    confirm: bool = typer.Option(True, "--confirm/--no-confirm", help="Confirm before approval when interactive."),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Poll the run until it reaches a terminal status."),
    poll_interval: float = typer.Option(DEFAULT_POLL_INTERVAL_SECONDS, "--poll-interval", min=0.1, help="Polling interval in seconds."),
    timeout_seconds: float = typer.Option(300.0, "--timeout", min=1.0, help="Maximum wait time when polling."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Approve a draft and optionally start its backend run."""
    config = _load_config()
    if confirm and sys.stdin.isatty():
        action = "approve and execute" if auto else "approve without execution"
        if not typer.confirm(f"Proceed to {action} draft {plan_id}?", default=True):
            console.print("[yellow]Run aborted by user.[/yellow]")
            raise typer.Exit(1)

    query = {"auto_run": "true" if auto else "false"}

    with console.status("[bold green]Approving draft..."):
        status_code, payload = _api_request(
            config,
            "POST",
            f"/ops/drafts/{plan_id}/approve",
            params=query,
        )

    if status_code != 200 or not isinstance(payload, dict):
        console.print(f"[red]Run start failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)

    approved = payload.get("approved") if isinstance(payload.get("approved"), dict) else {}
    run_payload = payload.get("run") if isinstance(payload.get("run"), dict) else None

    run_path = _runs_dir() / f"{plan_id}.json"
    _write_json(run_path, payload)

    final_run_payload = run_payload
    if auto and wait and isinstance(run_payload, dict) and run_payload.get("id"):
        final_run_payload = _poll_run(
            config,
            str(run_payload["id"]),
            poll_interval_seconds=poll_interval,
            timeout_seconds=timeout_seconds,
            announce=not json_output,
        )
        payload["run"] = final_run_payload
        _write_json(run_path, payload)

    if json_output:
        _emit_output(payload, json_output=True)
        return

    if final_run_payload:
        console.print(
            Panel(
                "\n".join(
                    [
                        "[bold green]Run started.[/bold green]",
                        f"Draft ID: [bold]{plan_id}[/bold]",
                        f"Approved ID: {approved.get('id', 'unknown')}",
                        f"Run ID: [bold]{final_run_payload.get('id', 'unknown')}[/bold]",
                        f"Status: {final_run_payload.get('status', 'unknown')}",
                        f"Stage: {final_run_payload.get('stage', 'n/a')}",
                    ]
                ),
                title="GIMO Run",
                border_style="blue",
            )
        )
        return

    console.print(
        Panel(
            "\n".join(
                [
                    "[bold yellow]Draft approved but not executed.[/bold yellow]",
                    f"Draft ID: [bold]{plan_id}[/bold]",
                    f"Approved ID: {approved.get('id', 'unknown')}",
                ]
            ),
            title="GIMO Approval",
            border_style="yellow",
        )
    )


@app.command()
def chat(
    thread_id: str | None = typer.Option(None, help="Existing thread id"),
) -> None:
    """Open a minimal conversational session against /ops/threads."""
    config = _load_config()
    workspace_root = str(_project_root())

    if thread_id is None:
        with console.status("[bold green]Creating conversation..."):
            status_code, payload = _api_request(
                config,
                "POST",
                "/ops/threads",
                params={"workspace_root": workspace_root, "title": "CLI Session"},
            )
        if status_code != 201 or not isinstance(payload, dict):
            console.print(f"[red]Failed to create thread ({status_code}): {payload}[/red]")
            raise typer.Exit(1)
        thread_id = str(payload.get("id") or "")

    if not thread_id:
        console.print("[red]No thread id available.[/red]")
        raise typer.Exit(1)

    history_path = _history_dir() / f"{thread_id}.log"
    console.print(
        Panel(
            f"Conversation ID: [bold]{thread_id}[/bold]\nType /exit to quit.",
            title="GIMO Chat",
            border_style="magenta",
        )
    )

    while True:
        user_input = console.input("[bold blue]You> [/bold blue]").strip()
        if not user_input:
            continue
        if user_input.lower() in {"/exit", "/quit", "exit", "quit"}:
            break

        with console.status("[bold green]Sending message..."):
            status_code, payload = _api_request(
                config,
                "POST",
                f"/ops/threads/{thread_id}/messages",
                params={"content": user_input},
            )

        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(f"You: {user_input}\n")
            handle.write(f"Result: {payload}\n")

        if status_code == 200 and isinstance(payload, dict):
            console.print(
                f"[green]Message delivered.[/green] Turn ID: {payload.get('turn_id', 'unknown')}"
            )
            continue

        console.print(f"[red]Chat failed ({status_code}): {payload}[/red]")


@app.command()
def diff(
    base: str = typer.Option("main", help="Base git ref."),
    head: str = typer.Option("HEAD", help="Head git ref."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show backend diff summary for the active repository."""
    config = _load_config()
    status_code, payload = _api_request(
        config,
        "GET",
        "/ops/files/diff",
        params={"base": base, "head": head},
    )
    if status_code != 200:
        console.print(f"[red]Diff failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)

    if json_output:
        _emit_output({"base": base, "head": head, "diff": payload}, json_output=True)
        return
    console.print(payload)


@app.command()
def rollback(
    commit_hash: str | None = typer.Argument(None, help="Commit to revert or reset to."),
    mode: str = typer.Option("revert", "--mode", help="Rollback mode: revert, soft-reset, hard-reset."),
    mainline: int | None = typer.Option(None, "--mainline", min=1, help="Parent number for reverting a merge commit."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Rollback the last AI-generated change using safe git defaults."""
    _load_config()
    _require_git_repo()
    _ensure_clean_worktree()

    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"revert", "soft-reset", "hard-reset"}:
        console.print("[red]Invalid rollback mode. Use revert, soft-reset, or hard-reset.[/red]")
        raise typer.Exit(1)

    target = (commit_hash or _default_rollback_target(normalized_mode)).strip()
    effective_mainline = _maybe_merge_mainline(target, mainline) if normalized_mode == "revert" else None

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

    proc = _git_command(git_args)
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        console.print(f"[red]Rollback failed:[/red] {message}")
        raise typer.Exit(1)

    head_proc = _git_command(["rev-parse", "--short", "HEAD"])
    payload = {
        "mode": normalized_mode,
        "target": target,
        "mainline": effective_mainline,
        "head": head_proc.stdout.strip() if head_proc.returncode == 0 else None,
        "stdout": proc.stdout.strip(),
    }

    if json_output:
        _emit_output(payload, json_output=True)
        return

    console.print(
        Panel(
            "\n".join(
                [
                    "[bold green]Rollback completed.[/bold green]",
                    f"Mode: {normalized_mode}",
                    f"Target: {target}",
                    f"HEAD: {payload.get('head') or 'unknown'}",
                ]
            ),
            title="GIMO Rollback",
            border_style="yellow",
        )
    )


@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Print the current local CLI config."),
    api_url: str | None = typer.Option(None, "--api-url", help="Set backend base URL."),
    model: str | None = typer.Option(None, "--model", help="Set preferred model."),
    budget: float | None = typer.Option(None, "--budget", help="Set budget limit in USD."),
    verbose: bool | None = typer.Option(None, "--verbose/--no-verbose", help="Set verbose mode."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Read or update local .gimo/config.yaml."""
    config_data = _load_config()
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
        _save_config(config_data)

    if json_output:
        _emit_output(config_data, json_output=True)
        return

    if show or changed:
        console.print(Panel(yaml.safe_dump(config_data, sort_keys=False), title="GIMO Config", border_style="cyan"))
        return

    console.print("[yellow]No changes requested. Use --show to print config.[/yellow]")


@app.command()
def audit(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Aggregate lightweight audit signals from backend endpoints."""
    config = _load_config()
    endpoints = {
        "alerts": ("/ops/observability/alerts", None),
        "dependencies": ("/ops/system/dependencies", None),
        "audit_tail": ("/ui/audit", {"limit": 20}),
    }
    result: dict[str, Any] = {}

    for key, (path, params) in endpoints.items():
        status_code, payload = _api_request(config, "GET", path, params=params)
        result[key] = {
            "status_code": status_code,
            "payload": payload,
        }

    if json_output:
        _emit_output(result, json_output=True)
        return

    table = Table(title="GIMO Audit", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Summary", style="white")

    alerts_payload = result["alerts"]["payload"] if isinstance(result["alerts"]["payload"], dict) else {}
    deps_payload = result["dependencies"]["payload"] if isinstance(result["dependencies"]["payload"], dict) else {}
    audit_payload = result["audit_tail"]["payload"] if isinstance(result["audit_tail"]["payload"], dict) else {}

    table.add_row(
        "Alerts",
        str(result["alerts"]["status_code"]),
        f"{alerts_payload.get('count', 'n/a')} alerts",
    )
    table.add_row(
        "Dependencies",
        str(result["dependencies"]["status_code"]),
        f"{deps_payload.get('count', 'n/a')} dependencies",
    )
    lines = audit_payload.get("lines") or []
    last_line = lines[-1] if lines else "no audit lines"
    table.add_row("Audit Tail", str(result["audit_tail"]["status_code"]), str(last_line)[:120])
    console.print(table)


@app.command()
def watch(
    limit: int = typer.Option(10, "--limit", min=1, help="Maximum number of events to consume before exiting."),
    timeout_seconds: float = typer.Option(DEFAULT_WATCH_TIMEOUT_SECONDS, "--timeout", min=1.0, help="Read timeout for the event stream."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Watch the backend SSE stream for live orchestration events."""
    config = _load_config()
    events: list[Any] = []

    try:
        for event in _stream_events(config, timeout_seconds=timeout_seconds):
            events.append(event)
            if not json_output:
                if isinstance(event, dict):
                    event_type = str(event.get("event") or event.get("type") or "event")
                    console.print(f"[cyan]{event_type}[/cyan] {json.dumps(event, ensure_ascii=False)}")
                else:
                    console.print(str(event))
            if len(events) >= limit:
                break
    except httpx.HTTPError as exc:
        console.print(f"[red]Watch failed:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        _emit_output(events, json_output=True)


@app.command()
def chat(
    workspace: str = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace root directory (defaults to current directory)"
    ),
):
    """
    Interactive chat mode with GIMO orchestrator.

    This is the main interface for chatting with GIMO.
    When invoked without subcommands, starts an interactive session.
    """
    from gimo_cli_renderer import GimoChatRenderer

    workspace_root = workspace or str(_project_root())

    # Preflight checks
    renderer = GimoChatRenderer()

    # 1. Check if backend is running
    try:
        config = _load_config()
    except typer.Exit:
        renderer.show_error(
            "Project not initialized.\n"
            "Run 'gimo init' first to set up the workspace."
        )
        raise typer.Exit(1)

    try:
        base_url, timeout = _api_settings(config)
        token = _resolve_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        with httpx.Client(timeout=timeout) as client:
            health_resp = client.get(f"{base_url}/health", headers=headers)
            if health_resp.status_code != 200:
                raise Exception(f"Health check failed: HTTP {health_resp.status_code}")
    except Exception as e:
        renderer.show_error(
            f"Backend server is not running.\n"
            f"Error: {str(e)}\n\n"
            f"Start the server with: GIMO_LAUNCHER.cmd"
        )
        raise typer.Exit(1)

    # 2. Check if orchestrator is configured
    try:
        with httpx.Client(timeout=timeout) as client:
            providers_resp = client.get(f"{base_url}/ops/providers", headers=headers)
            if providers_resp.status_code != 200:
                raise Exception(f"HTTP {providers_resp.status_code}")

            providers_data = providers_resp.json()
            roles = providers_data.get("roles", {})
            orch_binding = roles.get("orchestrator")

            if not orch_binding:
                renderer.show_error(
                    "No orchestrator configured.\n\n"
                    "Configure a provider:\n"
                    "  1. Visit http://localhost:5173 (GIMO UI)\n"
                    "  2. Go to Settings > Providers\n"
                    "  3. Add a provider and assign it to 'orchestrator' role"
                )
                raise typer.Exit(1)

            orchestrator_info = f"{orch_binding.get('model', 'unknown')} ({orch_binding.get('provider_id', 'unknown')})"
    except Exception as e:
        renderer.show_error(f"Failed to check orchestrator config: {str(e)}")
        raise typer.Exit(1)

    # 3. Create or get thread
    try:
        with httpx.Client(timeout=timeout) as client:
            # List existing threads for this workspace
            threads_resp = client.get(
                f"{base_url}/ops/threads",
                params={"workspace_root": workspace_root},
                headers=headers
            )

            if threads_resp.status_code == 200:
                threads = threads_resp.json()
                # Use most recent active thread
                active_threads = [t for t in threads if t.get("status") == "active"]
                if active_threads:
                    thread = active_threads[0]
                    thread_id = thread["id"]
                else:
                    # Create new thread
                    create_resp = client.post(
                        f"{base_url}/ops/threads",
                        params={"workspace_root": workspace_root, "title": "CLI Chat Session"},
                        headers=headers
                    )
                    create_resp.raise_for_status()
                    thread = create_resp.json()
                    thread_id = thread["id"]
            else:
                raise Exception(f"Failed to list threads: HTTP {threads_resp.status_code}")
    except Exception as e:
        renderer.show_error(f"Failed to create chat thread: {str(e)}")
        raise typer.Exit(1)

    # Show session header
    renderer.show_header(orchestrator_info, workspace_root, thread_id)

    # Interactive loop
    while True:
        try:
            user_input = renderer.show_user_prompt()

            if not user_input.strip():
                continue

            # Exit commands
            if user_input.strip().lower() in {"/exit", "/quit", "exit", "quit"}:
                renderer.show_info("Goodbye!")
                break

            # Send message to backend
            with renderer.show_thinking_spinner():
                with httpx.Client(timeout=120.0) as client:  # Longer timeout for chat
                    chat_resp = client.post(
                        f"{base_url}/ops/threads/{thread_id}/chat",
                        params={"content": user_input},
                        headers=headers
                    )

                    if chat_resp.status_code != 200:
                        renderer.show_error(f"Chat request failed: HTTP {chat_resp.status_code}\n{chat_resp.text}")
                        continue

                    response_data = chat_resp.json()

            # Render response
            from gimo_cli_renderer import render_chat_session
            render_chat_session(
                orchestrator_info=orchestrator_info,
                workspace=workspace_root,
                thread_id=thread_id,
                user_message=user_input,
                response_data=response_data
            )

        except KeyboardInterrupt:
            console.print("\n[dim]Use /exit to quit[/dim]")
            continue
        except Exception as e:
            renderer.show_error(f"Error: {str(e)}")
            continue


if __name__ == "__main__":
    app()
