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
from cli_constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_WATCH_TIMEOUT_SECONDS,
    DEFAULT_PREFERRED_MODEL,
    DEFAULT_EXCLUDE_DIRS,
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
)
from cli_parsers import is_terminal_status
from cli_policies import get_budget_color
from cli_commands import dispatch_slash_command, get_help_text

app = typer.Typer(
    name="gimo",
    help="GIMO: Generalized Intelligent Multi-agent Orchestrator",
    add_completion=True,
    invoke_without_command=True,
)
console = Console()


def _project_root() -> Path:
    try:
        probe = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True, check=True)
        return Path(probe.stdout.strip())
    except Exception:
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
            "preferred_model": DEFAULT_PREFERRED_MODEL,
            "budget_limit_usd": 10.0,
            "verbose": False,
            "auto_run_eligible": True,
        },
        "repository": {
            "name": _project_root().name,
            "workspace_root": str(_project_root()),
            "index_depth": 3,
            "exclude_dirs": DEFAULT_EXCLUDE_DIRS,
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
    json_body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    base_url, timeout_seconds = _api_settings(config)
    token = _resolve_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{base_url}{path}"

    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.request(method, url, params=params, json=json_body, headers=headers)

    payload: Any
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    return response.status_code, payload


def _get_telemetry_toolbar(config: dict[str, Any]) -> str:
    """Fetches the latest global budget forecast and returns formatted HTML for prompt_toolkit toolbar."""
    status, payload = _api_request(config, "GET", "/ops/forecast")
    if status == 200 and isinstance(payload, list):
        for f in payload:
            if f.get("scope") == "global":
                spend = f.get("current_spend", 0.0)
                limit = f.get("limit")
                rem_pct = f.get("remaining_pct")
                
                alerts = []
                if rem_pct is not None and rem_pct < 20:
                    alerts.append(f"<ansired>⚠️ Low budget ({rem_pct:.1f}% left)</ansired>")
                
                # Fetch eco mode status quickly for alerts
                mode = "off"
                cfg_st, cfg_py = _api_request(config, "GET", "/ops/config/economy")
                if cfg_st == 200 and isinstance(cfg_py, dict):
                    mode = cfg_py.get("eco_mode", {}).get("mode", "off")
                    if mode != "off":
                        alerts.append(f"<ansiyellow>🌿 Eco Mode: {mode.upper()}</ansiyellow>")
                        
                alerts_line = " | ".join(alerts) if alerts else "<ansigray>No active alerts</ansigray>"
                
                if limit is not None:
                    color = get_budget_color(rem_pct)
                    if color == "red": color = "ansired"
                    elif color == "yellow": color = "ansiyellow"
                    else: color = "ansigreen"
                    telemetry_line = f" 💰 Spent: <b>${spend:.4f}</b> / ${limit:.2f} | <{color}>{rem_pct:.1f}% remaining</{color}> "
                else:
                    telemetry_line = f" 💰 Spent: <b>${spend:.4f}</b> (No limit set) "
                    
                return f"{telemetry_line}\n 🔔 ALERTS: {alerts_line} "
    return " 💰 Telemetry unavailable \n 🔔 ALERTS: <ansigray>None</ansigray> "

def _provider_config_request(config: dict[str, Any]) -> tuple[int, Any]:
    status_code, payload = _api_request(config, "GET", "/ops/providers")
    if status_code != 404:
        return status_code, payload
    return _api_request(config, "GET", "/ops/provider")


def _chat_provider_summary(config: dict[str, Any]) -> tuple[str, str]:
    status_code, payload = _provider_config_request(config)
    if status_code != 200 or not isinstance(payload, dict):
        return "unknown", "unknown"
    provider_id = str(payload.get("orchestrator_provider") or payload.get("active") or "unknown")
    model_id = str(payload.get("orchestrator_model") or payload.get("model_id") or "unknown")
    return provider_id, model_id


def _render_chat_models(config: dict[str, Any]) -> None:
    status_code, payload = _api_request(config, "GET", "/ops/provider/models")
    if status_code != 200:
        console.print(f"[red]Failed to fetch models ({status_code}): {payload}[/red]")
        return
    if not isinstance(payload, list):
        console.print(payload)
        return
    table = Table(title="Available Models", show_header=True)
    table.add_column("Model", style="cyan")
    for item in payload:
        model_name = item.get("id", str(item)) if isinstance(item, dict) else str(item)
        table.add_row(model_name)
    console.print(table)


def _select_chat_provider(
    config: dict[str, Any],
    provider_id: str,
    *,
    model: str | None = None,
    prefer_family: str | None = None,
) -> tuple[int, Any]:
    payload: dict[str, Any] = {"provider_id": provider_id}
    if model:
        payload["model"] = model
    if prefer_family:
        payload["prefer_family"] = prefer_family
    return _api_request(config, "POST", "/ops/provider/select", json_body=payload)


def _handle_chat_slash_command(
    config: dict[str, Any],
    user_input: str,
    *,
    workspace_root: str,
    thread_id: str,
    current_usage: dict[str, Any] | None = None,
    current_perm: list[str] | None = None,
    renderer: Any = None,
) -> tuple[bool, str | None]:
    if not user_input.startswith("/"):
        return False, None

    parts = user_input.strip().split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    def show_help():
        console.print(Panel(get_help_text(), title="Chat Commands", border_style="cyan"))

    def show_workspace():
        console.print(Panel(workspace_root, title="Workspace", border_style="blue"))

    def show_thread():
        console.print(Panel(thread_id, title="Thread", border_style="blue"))

    def exit_session():
        pass

    def handle_provider(arg: str):
        if arg == "list":
            status_code, payload = _api_request(config, "GET", "/ops/provider")
            if status_code == 200 and isinstance(payload, dict):
                providers = payload.get("providers", {})
                table = Table(title="Configured Providers", show_header=True)
                table.add_column("Provider ID", style="cyan")
                table.add_column("Type", style="magenta")
                table.add_column("Role Configured", style="green")
                for pid, pdata in providers.items():
                    ptype = pdata.get("provider_type") or pdata.get("type") or "unknown"
                    role = "Yes" if pdata.get("role_bindings") else "No"
                    table.add_row(pid, ptype, role)
                console.print(table)
            else:
                console.print(f"[red]Failed to fetch providers ({status_code})[/red]")
            return None

        if arg.startswith("add"):
            console.print("[yellow]Para añadir nuevos providers de forma persistente, edita el GIMO_OPTS o utiliza la UI web (Settings > Providers).[/yellow]")
            return None

        if arg.startswith("switch"):
            rest = arg[len("switch"):].strip()
            if rest:
                target_provider = rest.split()[0]
                target_model = rest.split()[1] if len(rest.split()) > 1 else None
                prefer_family = "qwen" if "ollama" in target_provider.lower() and not target_model else None
                status_code, payload = _select_chat_provider(
                    config, target_provider, model=target_model, prefer_family=prefer_family
                )
                if status_code != 200:
                    console.print(f"[red]Failed to switch provider ({status_code}): {payload}[/red]")
                    return None
                provider_id, model_id = _chat_provider_summary(config)
                console.print(Panel(f"Provider: [bold]{provider_id}[/bold]\nModel: [bold]{model_id}[/bold]", title="Provider Switched", border_style="green"))
                return model_id

        # Interactive Menu for /provider or /provider menu
        try:
            import questionary
            from prompt_toolkit.styles import Style as QuestionaryStyle
        except ImportError:
            console.print("[red]Questionary library required for interactive menu. Fallback: Use /provider switch <id>[/red]")
            return None

        status_code, payload = _api_request(config, "GET", "/ops/provider")
        if status_code != 200 or not isinstance(payload, dict):
            console.print(f"[red]Failed to fetch providers for menu ({status_code})[/red]")
            return None
        
        providers = payload.get("providers", {})
        active_provider, _ = _chat_provider_summary(config)
        
        choices = []
        for pid, pdata in providers.items():
            ptype = pdata.get("provider_type") or pdata.get("type") or "unknown"
            marker = "*" if pid == active_provider else " "
            choices.append(questionary.Choice(f"{marker} {pid} (Type: {ptype})", value=pid))

        if not choices:
            console.print("[yellow]No providers available.[/yellow]")
            return None

        custom_style = QuestionaryStyle([
            ('qmark', 'fg:#00ffff bold'),
            ('question', 'bold'),
            ('answer', 'fg:#00ffff bold'),
            ('pointer', 'fg:#00ffff bold'),
            ('highlighted', 'fg:#00ffff bold'),
            ('selected', 'fg:#ffffff'),
            ('separator', 'fg:#cc5454'),
            ('instruction', 'fg:#889da3'),
        ])

        try:
            selected_provider = questionary.select(
                "Select Active Provider (Connection):",
                choices=choices,
                style=custom_style,
                instruction="(Use arrow keys)",
            ).ask()
        except KeyboardInterrupt:
            selected_provider = None

        if not selected_provider:
            console.print("[dim]Selección cancelada.[/dim]")
            return None

        # Switch to the selected provider
        prefer_family = "qwen" if "ollama" in selected_provider.lower() else None
        status_code, select_payload = _select_chat_provider(
            config, selected_provider, prefer_family=prefer_family
        )
        if status_code != 200:
            console.print(f"[red]Failed to switch provider ({status_code}): {select_payload}[/red]")
            return None
        
        provider_id, model_id = _chat_provider_summary(config)
        console.print(
            Panel(
                f"Provider changed to: [bold]{provider_id}[/bold]\nModel: [bold]{model_id}[/bold]",
                title="Provider Switched",
                border_style="green",
            )
        )
        return model_id

    def list_models():
        _render_chat_models(config)

    def handle_model(arg: str):
        if not arg:
            preferred_model = str(config.get("orchestrator", {}).get("preferred_model") or "not set")
            _, active_model = _chat_provider_summary(config)
            console.print(
                Panel(
                    f"Preferred model: [bold]{preferred_model}[/bold]\nActive backend model: [bold]{active_model}[/bold]",
                    title="Model Selection",
                    border_style="yellow",
                )
            )
            return None

        config.setdefault("orchestrator", {})["preferred_model"] = arg
        _save_config(config)
        console.print(f"[green]Preferred model set to '{arg}'.[/green]")
        return arg

    def show_workers():
        status_code, payload = _api_request(config, "GET", "/ops/provider")
        if status_code == 200 and isinstance(payload, dict):
            from rich.tree import Tree
            providers = payload.get("providers", {})
            tree = Tree("👷 [bold cyan]Worker Pool & Role Assignments[/bold cyan]")
            roles_map = {}
            unassigned = []
            for pid, pdata in providers.items():
                roles = pdata.get("role_bindings", [])
                if not roles:
                    unassigned.append(pid)
                for r in roles:
                    roles_map.setdefault(r, []).append(pid)
            
            for role, pids in roles_map.items():
                role_node = tree.add(f"[magenta]{role.capitalize()}[/magenta]")
                for pid in pids:
                    ptype = providers[pid].get("provider_type") or providers[pid].get("type", "unknown")
                    models = providers[pid].get("models", [])
                    role_node.add(f"[green]{pid}[/green] [dim]({ptype})[/dim] - {len(models)} models")
            
            if unassigned:
                un_node = tree.add("[yellow]Unassigned (General Purpose Workers)[/yellow]")
                for pid in unassigned:
                    ptype = providers[pid].get("provider_type") or providers[pid].get("type", "unknown")
                    un_node.add(f"{pid} [dim]({ptype})[/dim]")
                    
            console.print(Panel(tree, border_style="blue", title="Agents Topology"))
        else:
            console.print(f"[red]Failed to fetch worker pool ({status_code}).[/red]")

    def show_status():
        ok, err = _preflight_check(config)
        provider_id, model_id = _chat_provider_summary(config)
        
        from concurrent.futures import ThreadPoolExecutor
        def fetch_eco(): return _api_request(config, "GET", "/ops/config/economy")
        def fetch_claude(): return _api_request(config, "GET", "/ops/connectors/claude/auth-status")
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            f_eco = executor.submit(fetch_eco)
            f_cl = executor.submit(fetch_claude)
            st_eco, eco_py = f_eco.result()
            st_cl, cl_py = f_cl.result()
            
        lines = []
        lines.append(f"🟢 [bold]System[/bold]: {'Healthy' if ok else f'[red]Degraded ({err})[/red]'}")
        lines.append(f"🧠 [bold]Active Orchestrator[/bold]: [cyan]{provider_id}[/cyan] ({model_id})")
        lines.append(f"📁 [bold]Workspace[/bold]: [dim]{workspace_root}[/dim]")
        
        if st_eco == 200 and isinstance(eco_py, dict):
            budget = eco_py.get("global_budget_usd")
            mode = eco_py.get("eco_mode", {}).get("mode", "off")
            limits_text = f"${budget}" if budget is not None else "No limits"
            lines.append(f"💰 [bold]Economy[/bold]: Global Budget: [green]{limits_text}[/green] | EcoMode: [yellow]{mode.upper()}[/yellow]")
        
        if st_cl == 200 and isinstance(cl_py, dict):
            if cl_py.get("authenticated"):
                plan = cl_py.get("plan", "Unknown")
                lines.append(f"⚡ [bold]Claude Quota[/bold]: Authenticated (Tier: [magenta]{plan}[/magenta])")
            else:
                lines.append(f"⚡ [bold]Claude Quota[/bold]: [dim]Not authenticated[/dim]")

        console.print(Panel("\n".join(lines), title="Real-time Telemetry Status", border_style="magenta"))

    # ── P0 new handlers ──────────────────────────────────────────────────────

    def undo():
        """git revert --no-edit HEAD — safe undo (assumes last commit is AI)."""
        try:
            result = _git_command(["revert", "--no-edit", "HEAD"])
            if result.returncode == 0:
                console.print(Panel(
                    result.stdout.strip() or "Revert successful.",
                    title="✓ /undo — git revert HEAD",
                    border_style="green",
                ))
            else:
                console.print(Panel(
                    result.stderr.strip() or result.stdout.strip() or "Revert failed.",
                    title="✗ /undo failed",
                    border_style="red",
                ))
        except Exception as exc:
            console.print(f"[red]Undo error: {exc}[/red]")

    def clear_view():
        """Clear-screen effect (local view only — no backend changes)."""
        console.clear()
        console.print("[dim]Chat cleared (thread and context intact).[/dim]")

    def reset_context():
        """Reset backend thread context after y/N confirmation."""
        try:
            answer = console.input("[bold yellow]¿Reiniciar contexto? (y/N): [/bold yellow]").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]Reset cancelado.[/dim]")
            return
        if answer not in {"y", "yes", "s", "si", "sí"}:
            console.print("[dim]Reset cancelado.[/dim]")
            return
        sc, payload = _api_request(config, "POST", f"/ops/threads/{thread_id}/reset")
        if sc in {200, 204}:
            console.print("[green]✓ Contexto del thread reiniciado.[/green]")
        else:
            console.print(f"[red]Reset failed ({sc}): {payload}[/red]")

    def show_tokens():
        """Show token usage breakdown from last turn."""
        usage = current_usage or {}
        if not usage:
            console.print("[dim]No hay datos de tokens para el turno actual.[/dim]")
            return
        lines = [
            f"  Tokens entrada:   [cyan]{usage.get('input_tokens', 0):,}[/cyan]",
            f"  Tokens salida:    [cyan]{usage.get('output_tokens', 0):,}[/cyan]",
            f"  Total turno:      [bold]{usage.get('total_tokens', 0):,}[/bold]",
            f"  Coste acumulado:  [green]${usage.get('cost_usd', 0.0):.5f}[/green]",
        ]
        ctx_pct = usage.get("context_window_pct")
        if ctx_pct is not None:
            bar_len = 20
            fill = min(int(ctx_pct / 100 * bar_len), bar_len)
            bar = "█" * fill + "░" * (bar_len - fill)
            color = "red" if ctx_pct > 80 else "yellow" if ctx_pct > 60 else "green"
            lines.append(f"  Ctx window:       [{color}]{bar}[/{color}] {ctx_pct:.1f}%")
        console.print(Panel("\n".join(lines), title="📊 Token Usage", border_style="cyan"))

    def show_diff():
        """Fetch and render diff from /ops/files/diff."""
        sc, payload = _api_request(config, "GET", "/ops/files/diff")
        if sc != 200:
            console.print(f"[red]Diff unavailable ({sc}): {payload}[/red]")
            return
        if isinstance(payload, dict):
            diff_text = payload.get("diff") or payload.get("content") or str(payload)
        else:
            diff_text = str(payload)
        if not diff_text.strip():
            console.print("[dim]No hay diferencias activas.[/dim]")
            return
        console.print(Panel(diff_text, title="📄 /diff — workspace diff", border_style="yellow"))

    def set_effort(effort_val: str):
        """POST effort setting to the active thread config."""
        sc, payload = _api_request(
            config, "POST", f"/ops/threads/{thread_id}/config",
            json_body={"effort": effort_val},
        )
        if sc in {200, 204}:
            console.print(f"[green]✓ Esfuerzo del orquestador: [bold]{effort_val}[/bold][/green]")
        else:
            console.print(f"[red]Set effort failed ({sc}): {payload}[/red]")

    def set_permissions(perm_val: str):
        """Change HITL mode live and update in-session display."""
        sc, payload = _api_request(
            config, "POST", f"/ops/threads/{thread_id}/config",
            json_body={"hitl_mode": perm_val},
        )
        if sc in {200, 204}:
            if current_perm is not None:
                current_perm.clear()
                current_perm.append(perm_val)
            console.print(f"[green]✓ Permisos HITL: [bold]perm:{perm_val}[/bold][/green]")
        else:
            console.print(f"[red]Set permissions failed ({sc}): {payload}[/red]")

    def add_file(path_val: str):
        """POST file path to active thread context."""
        sc, payload = _api_request(
            config, "POST", f"/ops/threads/{thread_id}/context/add",
            json_body={"path": path_val},
        )
        if sc in {200, 201}:
            console.print(f"[green]✓ Añadido al contexto: [bold]{path_val}[/bold][/green]")
        else:
            console.print(f"[red]Add file failed ({sc}): {payload}[/red]")

    def invalid_arg(msg: str):
        console.print(f"[yellow]⚠ {msg}[/yellow]")

    def toggle_debug():
        if renderer is not None:
            renderer.verbose = not renderer.verbose
            console.print(f"[dim]Debug mode {'enabled' if renderer.verbose else 'disabled'}[/dim]")

    def unknown_command(cmd: str):
        console.print(f"[yellow]Unknown command: {cmd}. Use /help.[/yellow]")

    callbacks = {
        "show_help": show_help,
        "show_workspace": show_workspace,
        "show_thread": show_thread,
        "exit_session": exit_session,
        "handle_provider": handle_provider,
        "handle_model": handle_model,
        "list_models": list_models,
        "show_workers": show_workers,
        "show_status": show_status,
        # P0 new
        "undo": undo,
        "clear_view": clear_view,
        "reset_context": reset_context,
        "show_tokens": show_tokens,
        "show_diff": show_diff,
        "set_effort": set_effort,
        "set_permissions": set_permissions,
        "add_file": add_file,
        "toggle_debug": toggle_debug,
        "invalid_arg": invalid_arg,
        "unknown_command": unknown_command,
    }

    return dispatch_slash_command(command, argument, callbacks)


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
    return is_terminal_status(status, ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES)


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
        return False, f"Cannot reach GIMO server: {exc}\nStart it with: gimo.cmd"

    try:
        status_code, payload = _provider_config_request(config)
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

    renderer = ChatRenderer(console, verbose=config.get("orchestrator", {}).get("verbose", False))
    workspace_root = str(_project_root())

    # Preflight
    ok, err = _preflight_check(config)
    if not ok:
        renderer.render_preflight_error(err, hint="Run 'gimo status' for diagnostics.")
        raise typer.Exit(1)

    # Fetch provider info for header
    provider_id, model = _chat_provider_summary(config)

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

    # State shared across turns for /tokens and /permissions
    current_usage: dict[str, Any] = {}
    current_perm: list[str] = ["suggest"]  # default HITL mode

    # Main loop
    while True:
        turn_interrupted = False
        try:
            user_input = renderer.get_user_input()
        except KeyboardInterrupt:
            renderer.render_interrupted()
            continue
        if not user_input:
            continue
        if user_input.lower() in {"/exit", "/quit"}:
            console.print("[dim]Session ended.[/dim]")
            break
        handled, updated_model = _handle_chat_slash_command(
            config,
            user_input,
            workspace_root=workspace_root,
            thread_id=thread_id,
            current_usage=current_usage,
            current_perm=current_perm,
            renderer=renderer,
        )
        if handled:
            if updated_model is not None:
                model = updated_model
            continue

        # Save to history
        with history_path.open("a", encoding="utf-8") as f:
            f.write(f"> {user_input}\n")

        # Try SSE streaming first, fall back to sync
        base_url, timeout_seconds = _api_settings(config)
        auth_token = _resolve_token()
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        headers["Accept"] = "text/event-stream"

        chat_response = ""
        usage = {}

        try:
            stream_timeout = httpx.Timeout(
                connect=timeout_seconds,
                read=600.0,  # 10 min for long agentic loops
                write=timeout_seconds,
                pool=timeout_seconds,
            )
            with httpx.Client(timeout=stream_timeout) as client:
                with renderer.render_thinking():
                    with client.stream(
                        "POST",
                        f"{base_url}/ops/threads/{thread_id}/chat/stream",
                        params={"content": user_input},
                        headers=headers,
                    ) as response:
                        if response.status_code != 200:
                            # Fall back to sync endpoint
                            raise httpx.HTTPStatusError(
                                f"Stream returned {response.status_code}",
                                request=response.request,
                                response=response,
                            )

                        current_event_type = "message"
                        renderer._generation_active = True
                        try:
                            for line in response.iter_lines():
                                if not line or line.startswith(":"):
                                    continue

                                # Parse SSE format
                                if line.startswith("event: "):
                                    current_event_type = line[7:].strip()
                                    continue
                                if not line.startswith("data: "):
                                    continue

                                raw_data = line[6:].strip()
                                if not raw_data:
                                    continue

                                try:
                                    data = json.loads(raw_data)
                                except json.JSONDecodeError:
                                    continue

                                evt = current_event_type
                                renderer.render_sse_raw(evt, raw_data)

                                if evt == "text_delta":
                                    # Accumulate for final render
                                    chat_response += data.get("content", "")

                                elif evt == "tool_call_start":
                                    renderer.render_tool_call_start(
                                        data.get("tool_name", "?"),
                                        data.get("arguments", {}),
                                        data.get("risk", "LOW"),
                                    )

                                elif evt == "tool_approval_required":
                                    # HITL: ask user for approval
                                    approved = renderer.render_hitl_prompt(
                                        data.get("tool_name", "?"),
                                        data.get("arguments", {}),
                                    )
                                    # Submit approval to backend
                                    try:
                                        client.post(
                                            f"{base_url}/ops/threads/{thread_id}/approve-tool",
                                            params={
                                                "tool_call_id": data.get("tool_call_id", ""),
                                                "approved": str(approved).lower(),
                                            },
                                            headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
                                        )
                                    except Exception:
                                        pass  # Best effort

                                elif evt == "tool_call_end":
                                    renderer.render_tool_call_result(
                                        data.get("tool_name", "?"),
                                        data.get("status", "error"),
                                        data.get("duration", 0.0),
                                        data.get("risk", "LOW"),
                                    )

                                elif evt == "done":
                                    chat_response = data.get("response", chat_response)
                                    usage = data.get("usage", {})
                                    current_usage.clear()
                                    current_usage.update(usage)

                                    # Emit warnings for ctx window and budget
                                    ctx_pct = usage.get("context_window_pct", 0)
                                    if ctx_pct > 70:
                                        from cli_commands import Notice
                                        import time
                                        renderer.render_notice(Notice("warning", f"Context window high: {ctx_pct:.1f}%", time.time(), 30, False))

                                    cost = usage.get("cost_usd", 0)
                                    budget_limit = float(config.get("orchestrator", {}).get("budget_limit_usd") or 0)
                                    if budget_limit > 0 and (cost / budget_limit) > 0.8:
                                        from cli_commands import Notice
                                        import time
                                        renderer.render_notice(Notice("warning", f"Budget critical: ${cost:.2f}/${budget_limit:.2f}", time.time(), 30, False))

                                    run_data = data.get("run", {})
                                    if run_data.get("id") or run_data.get("tools_used") or run_data.get("objective"):
                                        renderer.render_post_run_report(run_id=run_data.get("id"), usage=usage, run_data=run_data)


                                elif evt == "error":
                                    renderer.render_error(data.get("message", "Unknown error"))

                                # P2: conversational planning events
                                elif evt == "user_question":
                                    question = data.get("question", "")
                                    options = data.get("options", [])
                                    context = data.get("context", "")
                                    renderer.render_user_question(question, options, context)

                                elif evt == "plan_proposed":
                                    plan = data
                                    renderer.render_plan(plan)
                                    approval = renderer.get_plan_approval()

                                    try:
                                        client.post(
                                            f"{base_url}/ops/threads/{thread_id}/plan/respond",
                                            params={"action": approval},
                                            json={"feedback": "User feedback from CLI"},
                                            headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
                                        )

                                        if approval == "approve":
                                            renderer.console.print("[green]\u2713 Plan approved. Execution started.[/green]")
                                        elif approval == "reject":
                                            renderer.console.print("[red]\u2717 Plan rejected. Agent will revise.[/red]")
                                        else:
                                            renderer.console.print("[yellow]Plan modification not yet implemented in CLI. Please approve or reject.[/yellow]")
                                    except Exception as e:
                                        renderer.render_error(f"Failed to submit plan response: {e}")

                                elif evt == "confirmation_required":
                                    tool_name = data.get("tool_name", "?")
                                    message = data.get("message", "")
                                    renderer.console.print()
                                    renderer.console.print(Panel(
                                        f"{message}\n\nTool: [bold]{tool_name}[/bold]",
                                        title="\u26a0 Confirmation Required",
                                        border_style="yellow",
                                    ))
                                    try:
                                        answer = renderer.console.input("[bold yellow]Approve? (y/N): [/bold yellow]").strip()
                                        from cli_parsers import parse_yes_no
                                        approved = parse_yes_no(answer)

                                        try:
                                            client.post(
                                                f"{base_url}/ops/threads/{thread_id}/approve-tool",
                                                params={
                                                    "tool_call_id": data.get("tool_call_id", ""),
                                                    "approved": str(approved).lower(),
                                                },
                                                headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
                                            )
                                        except Exception:
                                            pass  # Best effort

                                        if not approved:
                                            renderer.console.print("[dim]Confirmation denied. Agent will skip this action.[/dim]")
                                    except (EOFError, KeyboardInterrupt):
                                        pass

                                elif evt == "session_start":
                                    mood = data.get("mood", "neutral")
                                    renderer.render_mood_indicator(mood)

                        except KeyboardInterrupt:
                            turn_interrupted = True
                            renderer.render_interrupted()
                            break  # Exit iter_lines stream immediately
                        finally:
                            renderer._generation_active = False

        except (httpx.HTTPStatusError, httpx.ConnectError):
            # Fall back to sync POST
            try:
                with httpx.Client(timeout=max(timeout_seconds, 300.0)) as client:
                    with renderer.render_thinking():
                        response = client.post(
                            f"{base_url}/ops/threads/{thread_id}/chat",
                            params={"content": user_input},
                            headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
                        )

                if response.status_code != 200:
                    renderer.render_error(f"HTTP {response.status_code}: {response.text[:200]}")
                    continue

                payload = response.json()
                tool_calls = payload.get("tool_calls", [])
                if tool_calls:
                    renderer.render_tool_calls(tool_calls)
                chat_response = payload.get("response", "")
                usage = payload.get("usage", {})
            except httpx.TimeoutException:
                renderer.render_error("Request timed out. The LLM may need more time.")
                continue
            except Exception as exc:
                renderer.render_error(f"Request failed: {exc}")
                continue
        except httpx.TimeoutException:
            renderer.render_error("Stream timed out. The LLM may need more time.")
            continue
        except Exception as exc:
            renderer.render_error(f"Stream failed: {exc}")
            continue

        if turn_interrupted:
            continue

        # Render response
        renderer.render_response(chat_response)
        renderer.render_footer(usage)

        # Save to history
        with history_path.open("a", encoding="utf-8") as f:
            f.write(f"{chat_response}\n---\n")


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug/verbose render mode"),
) -> None:
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

    if "orchestrator" not in config:
        config["orchestrator"] = {}
    config["orchestrator"]["verbose"] = verbose or config["orchestrator"].get("verbose", False)

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
    """Comprehensive status panel: repo, backend, budget, active run, alerts."""
    from concurrent.futures import ThreadPoolExecutor

    result: dict[str, Any] = {}

    # ── Git info ──────────────────────────────────────────────────────────────
    repo_name = _project_root().name
    branch_res = _git_command(["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "unknown"
    dirty_res = _git_command(["status", "--porcelain"])
    dirty_files = len([ln for ln in dirty_res.stdout.splitlines() if ln.strip()]) if dirty_res.returncode == 0 else 0
    result.update({"repo": repo_name, "branch": branch, "dirty_files": dirty_files})

    # ── Config ────────────────────────────────────────────────────────────────
    try:
        config = _load_config()
    except typer.Exit:
        config = {}

    if not config:
        lines = [
            f"📁 [bold]Repo[/bold]: {repo_name}  branch: [cyan]{branch}[/cyan]",
            "[red]⚠ Workspace not initialized. Run 'gimo init'.[/red]",
        ]
        if json_output:
            _emit_output(result, json_output=True)
            return
        console.print(Panel("\n".join(lines), title="GIMO Status", border_style="red"))
        return

    orch_cfg = dict(config.get("orchestrator") or {})
    budget_limit = float(orch_cfg.get("budget_limit_usd") or 0)

    # ── Parallel API fetches ──────────────────────────────────────────────────
    def _fetch(path: str) -> tuple[int, Any]:
        try:
            return _api_request(config, "GET", path)
        except Exception as exc:
            return -1, str(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_health   = pool.submit(_fetch, "/health")
        f_status   = pool.submit(_fetch, "/status")
        f_runs     = pool.submit(_fetch, "/ops/runs")
        f_prov     = pool.submit(_fetch, "/ops/provider")
        f_threads  = pool.submit(_fetch, "/ops/threads")
        f_forecast = pool.submit(_fetch, "/ops/forecast")

        hc, _   = f_health.result()
        sc, sp  = f_status.result()
        rc, rp  = f_runs.result()
        pc, pp  = f_prov.result()
        tc, tp  = f_threads.result()
        fc, fp  = f_forecast.result()

    # ── Backend ───────────────────────────────────────────────────────────────
    backend_online = hc == 200
    version = str(sp.get("version") or "unknown") if sc == 200 and isinstance(sp, dict) else "n/a"
    result.update({"backend_online": backend_online, "version": version})

    # ── Provider / model ─────────────────────────────────────────────────────
    provider_id, model_id = "unknown", "unknown"
    if pc == 200 and isinstance(pp, dict):
        provider_id = str(pp.get("orchestrator_provider") or pp.get("active") or "unknown")
        model_id    = str(pp.get("orchestrator_model") or pp.get("model_id") or "unknown")
    result.update({"provider": provider_id, "model": model_id})

    # ── Runs ─────────────────────────────────────────────────────────────────
    runs = rp if rc == 200 and isinstance(rp, list) else []
    latest_run = _latest_run_summary(runs)
    result["latest_run"] = latest_run

    # ── Last thread + ctx% ────────────────────────────────────────────────────
    last_thread_id, last_thread_turn, last_ctx_pct = "n/a", "n/a", None
    if tc == 200 and isinstance(tp, list) and tp:
        t0 = tp[0]
        last_thread_id   = str(t0.get("id") or "n/a")
        last_thread_turn = str(t0.get("turn_count") or t0.get("message_count") or "?")
        last_ctx_pct     = t0.get("context_window_pct") or t0.get("ctx_pct")

    # ── Budget ────────────────────────────────────────────────────────────────
    spend, rem_pct = 0.0, None
    if fc == 200 and isinstance(fp, list):
        for f in fp:
            if f.get("scope") == "global":
                spend   = float(f.get("current_spend") or 0)
                rem_pct = f.get("remaining_pct")
                break
    result.update({"spend_usd": spend, "budget_limit_usd": budget_limit})

    # ── Alerts ────────────────────────────────────────────────────────────────
    alerts: list[str] = []
    if not backend_online:
        alerts.append("✗ Backend OFFLINE")
    if rem_pct is not None and rem_pct < 20:
        alerts.append(f"⚠ Budget crítico: {rem_pct:.1f}% restante")
    result["alerts"] = alerts

    if json_output:
        _emit_output(result, json_output=True)
        return

    # ── Rich panel ───────────────────────────────────────────────────────────
    dirty_str   = f"  [yellow]({dirty_files} dirty)[/yellow]" if dirty_files else ""
    backend_str = f"[green]ONLINE[/green] · v{version}" if backend_online else "[red]OFFLINE[/red]"

    if budget_limit > 0:
        bar_len = 20
        fill = min(int((spend / budget_limit) * bar_len), bar_len)
        bar = "█" * fill + "░" * (bar_len - fill)
        from cli_policies import get_budget_color
        bcolor = get_budget_color(rem_pct)
        budget_str = f"[{bcolor}]{bar}[/{bcolor}] ${spend:.3f} / ${budget_limit:.2f}"
    else:
        budget_str = f"${spend:.3f} (sin límite)"

    if latest_run:
        _run_id = latest_run.get('id', '?')
        _run_status = latest_run.get('status', '?')
        run_str = f"{_run_id}  [dim italic]({_run_status})[/dim italic]"
        stage = latest_run.get("stage")
        if stage:
            run_str += f" · {stage}"
    else:
        run_str = "[dim]ninguno[/dim]"

    alerts_str = "  ".join(alerts) if alerts else "[dim]ninguna[/dim]"

    # ctx% bar (optional — only shown when backend reports it)
    if last_ctx_pct is not None:
        ctx_bar_len = 20
        ctx_fill = min(int(last_ctx_pct / 100 * ctx_bar_len), ctx_bar_len)
        ctx_bar = "█" * ctx_fill + "░" * (ctx_bar_len - ctx_fill)
        ctx_color = "red" if last_ctx_pct > 80 else "yellow" if last_ctx_pct > 60 else "green"
        ctx_str: str | None = f"[{ctx_color}]{ctx_bar}[/{ctx_color}] {last_ctx_pct:.1f}%"
    else:
        ctx_str = None

    panel_lines = [
        f"📁 [bold]Repo[/bold]:          {repo_name} · [cyan]{branch}[/cyan]{dirty_str}",
        f"🧠 [bold]Proveedor[/bold]:     [cyan]{provider_id}[/cyan] / {model_id}",
        f"🔒 [bold]Permisos[/bold]:      perm:[yellow]{orch_cfg.get('hitl_mode', 'suggest')}[/yellow]",
        f"🌐 [bold]Backend[/bold]:       {backend_str}",
        f"▶  [bold]Run activo[/bold]:    {run_str}",
        f"💰 [bold]Budget[/bold]:        {budget_str}",
        f"💬 [bold]Último thread[/bold]: {last_thread_id}  turno {last_thread_turn}",
    ]
    if ctx_str:
        panel_lines.append(f"📊 [bold]Ctx window[/bold]:    {ctx_str}")
    panel_lines.append(f"🔔 [bold]Alertas[/bold]:       {alerts_str}")
    console.print(Panel("\n".join(panel_lines), title="GIMO Status", border_style="cyan"))




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

    record_id = str(run_payload.get("id", "")) if run_payload else ""
    if record_id:
        base_name = record_id
    else:
        import uuid
        base_name = f"{plan_id}_{uuid.uuid4().hex[:8]}"

    run_path = _runs_dir() / f"{base_name}.json"
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
def tui(
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug/verbose render mode"),
) -> None:
    """Launch the experimental Textual UI."""
    try:
        config = _load_config()
    except Exception:
        _ensure_project_dirs()
        config = _load_config()

    if "orchestrator" not in config:
        config["orchestrator"] = {}
    config["orchestrator"]["verbose"] = verbose or config["orchestrator"].get("verbose", False)

    from gimo_tui import GimoApp
    console.print("[dim]Launching TUI...[/dim]")
    app_tui = GimoApp(config=config, thread_id="tui_default")
    app_tui.verbose = config["orchestrator"]["verbose"]
    app_tui.run()

@app.command()
def chat(
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug/verbose render mode"),
) -> None:
    """Interactive agentic chat session with GIMO orchestrator."""
    try:
        config = _load_config()
    except typer.Exit:
        _ensure_project_dirs()
        if not _config_path().exists():
            _save_config(_default_config())
        config = _load_config()

    if "orchestrator" not in config:
        config["orchestrator"] = {}
    config["orchestrator"]["verbose"] = verbose or config["orchestrator"].get("verbose", False)

    _interactive_chat(config)


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


# ---------------------------------------------------------------------------
# Sub-apps for grouped commands
# ---------------------------------------------------------------------------

providers_app = typer.Typer(name="providers", help="Manage LLM providers and connectors.")
trust_app = typer.Typer(name="trust", help="Trust engine dashboard and controls.")
mastery_app = typer.Typer(name="mastery", help="Token economy, cost analytics, and budget forecast.")
skills_app = typer.Typer(name="skills", help="List and execute registered skills.")
repos_app = typer.Typer(name="repos", help="Repository management.")
threads_app = typer.Typer(name="threads", help="Conversation thread management.")
observe_app = typer.Typer(name="observe", help="Observability: metrics, traces, and alerts.")

app.add_typer(providers_app, name="providers")
app.add_typer(trust_app, name="trust")
app.add_typer(mastery_app, name="mastery")
app.add_typer(skills_app, name="skills")
app.add_typer(repos_app, name="repos")
app.add_typer(threads_app, name="threads")
app.add_typer(observe_app, name="observe")


# --- providers ---


@providers_app.command("list")
def providers_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List configured providers."""
    config = _load_config()
    status_code, payload = _provider_config_request(config)
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        table = Table(title="Providers", show_header=True)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        for k, v in payload.items():
            if k == "providers" and isinstance(v, dict):
                for pid, pdata in v.items():
                    ptype = pdata.get("type", "?") if isinstance(pdata, dict) else str(pdata)
                    table.add_row(f"  {pid}", ptype)
            else:
                table.add_row(k, str(v)[:120])
        console.print(table)
    else:
        console.print(payload)


@providers_app.command("test")
def providers_test(
    provider_id: str = typer.Argument(..., help="Provider ID to test."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Test connectivity for a provider."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", f"/ops/connectors/{provider_id}/health")
    if json_output:
        _emit_output({"status_code": status_code, "result": payload}, json_output=True)
        return
    if status_code == 200:
        console.print(f"[green]Provider '{provider_id}' is healthy.[/green]")
    else:
        console.print(f"[red]Provider '{provider_id}' test failed ({status_code}): {payload}[/red]")


@providers_app.command("models")
def providers_models(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List models available from the active provider."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/provider/models")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Available Models", show_header=True)
        table.add_column("Model", style="cyan")
        for m in payload:
            name = m.get("id", str(m)) if isinstance(m, dict) else str(m)
            table.add_row(name)
        console.print(table)
    else:
        console.print(payload)


# --- trust ---


@trust_app.command("status")
def trust_status(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show trust engine dashboard."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/trust/dashboard")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        table = Table(title="Trust Dashboard", show_header=True)
        table.add_column("Dimension", style="cyan")
        table.add_column("Score", style="magenta")
        table.add_column("State", style="white")
        entries = payload.get("entries") or payload.get("dimensions") or []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    table.add_row(
                        str(entry.get("dimension", entry.get("key", "?"))),
                        str(entry.get("score", "?")),
                        str(entry.get("state", entry.get("circuit_state", "?"))),
                    )
        console.print(table)
        summary = payload.get("summary") or payload.get("aggregate")
        if summary:
            console.print(f"[dim]Aggregate: {summary}[/dim]")
    else:
        console.print(payload)


@trust_app.command("reset")
def trust_reset(
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Reset trust engine state."""
    if not yes and sys.stdin.isatty():
        if not typer.confirm("Reset trust engine? This clears all trust scores.", default=False):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)
    config = _load_config()
    status_code, payload = _api_request(config, "POST", "/ops/trust/reset")
    if json_output:
        _emit_output({"status_code": status_code, "result": payload}, json_output=True)
        return
    if status_code == 200:
        console.print("[green]Trust engine reset successfully.[/green]")
    else:
        console.print(f"[red]Reset failed ({status_code}): {payload}[/red]")


# --- mastery ---


@mastery_app.command("status")
def mastery_status(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show token mastery status (economy, hardware, efficiency)."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/mastery/status")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        table = Table(title="Token Mastery", show_header=False)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="magenta")
        for k, v in payload.items():
            if not isinstance(v, (dict, list)):
                table.add_row(k, str(v))
        console.print(table)
    else:
        console.print(payload)


@mastery_app.command("forecast")
def mastery_forecast(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show budget forecast and burn rate."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/mastery/forecast")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        table = Table(title="Budget Forecast", show_header=False)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="magenta")
        for k, v in payload.items():
            if not isinstance(v, (dict, list)):
                table.add_row(k, str(v))
        console.print(table)
    else:
        console.print(payload)


@mastery_app.command("analytics")
def mastery_analytics(
    days: int = typer.Option(30, "--days", help="Number of days for analytics."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show cost analytics over a time range."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/mastery/analytics", params={"days": days})
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    console.print_json(data=payload) if isinstance(payload, (dict, list)) else console.print(payload)


# --- skills ---


@skills_app.command("list")
def skills_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List registered skills."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/skills")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Skills", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Description", style="dim")
        for skill in payload:
            if isinstance(skill, dict):
                table.add_row(
                    str(skill.get("id", "?")),
                    str(skill.get("name", "?")),
                    str(skill.get("description", ""))[:60],
                )
        console.print(table)
    else:
        console.print(payload)


@skills_app.command("run")
def skills_run(
    skill_id: str = typer.Argument(..., help="Skill ID to execute."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Execute a registered skill."""
    config = _load_config()
    with console.status("[bold green]Executing skill..."):
        status_code, payload = _api_request(config, "POST", f"/ops/skills/{skill_id}/execute")
    if json_output:
        _emit_output({"status_code": status_code, "result": payload}, json_output=True)
        return
    if status_code == 200:
        console.print(f"[green]Skill '{skill_id}' executed successfully.[/green]")
        if isinstance(payload, dict):
            console.print_json(data=payload)
    else:
        console.print(f"[red]Execution failed ({status_code}): {payload}[/red]")


# --- repos ---


@repos_app.command("list")
def repos_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List known repositories."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/repos")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Repositories", show_header=True)
        table.add_column("Path", style="cyan")
        table.add_column("Active", style="green")
        for repo in payload:
            if isinstance(repo, dict):
                table.add_row(str(repo.get("path", "?")), str(repo.get("active", "")))
            else:
                table.add_row(str(repo), "")
        console.print(table)
    elif isinstance(payload, dict):
        repos = payload.get("repos") or payload.get("repositories") or []
        active = payload.get("active") or payload.get("selected")
        if repos:
            for r in repos:
                marker = " [green]*[/green]" if str(r) == str(active) else ""
                console.print(f"  {r}{marker}")
        else:
            console.print_json(data=payload)
    else:
        console.print(payload)


@repos_app.command("select")
def repos_select(
    path: str = typer.Argument(..., help="Repository path to select."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Select a repository as active workspace."""
    config = _load_config()
    status_code, payload = _api_request(config, "POST", "/ops/repos/select", params={"path": path})
    if json_output:
        _emit_output({"status_code": status_code, "result": payload}, json_output=True)
        return
    if status_code == 200:
        console.print(f"[green]Repository selected: {path}[/green]")
    else:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")


# --- threads ---


@threads_app.command("list")
def threads_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List conversation threads."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/threads")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Threads", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Turns", style="magenta")
        table.add_column("Created", style="dim")
        for t in payload:
            if isinstance(t, dict):
                turns = t.get("turns", [])
                table.add_row(
                    str(t.get("id", "?"))[:12],
                    str(t.get("title", "Untitled"))[:40],
                    str(len(turns) if isinstance(turns, list) else "?"),
                    str(t.get("created_at", ""))[:19],
                )
        console.print(table)
    else:
        console.print(payload)


@threads_app.command("show")
def threads_show(
    thread_id: str = typer.Argument(..., help="Thread ID to display."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show details of a specific thread."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", f"/ops/threads/{thread_id}")
    if status_code != 200:
        console.print(f"[red]Thread not found ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        console.print(Panel(
            f"Title: {payload.get('title', 'Untitled')}\n"
            f"Workspace: {payload.get('workspace_root', '?')}\n"
            f"Turns: {len(payload.get('turns', []))}",
            title=f"Thread {thread_id[:12]}",
            border_style="cyan",
        ))
        for turn in payload.get("turns", []):
            if not isinstance(turn, dict):
                continue
            agent = turn.get("agent_id", "?")
            items = turn.get("items", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                itype = item.get("type", "?")
                content = str(item.get("content", ""))[:200]
                if itype == "text" and content:
                    prefix = "[bold cyan]>[/bold cyan]" if agent in ("user", "User") else "[bold green]GIMO:[/bold green]"
                    console.print(f"  {prefix} {content}")
                elif itype == "tool_call":
                    meta = item.get("metadata", {})
                    console.print(f"  [dim]\u25b8 {meta.get('tool_name', '?')}[/dim]")
    else:
        console.print(payload)


# --- observe ---


@observe_app.command("metrics")
def observe_metrics(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show observability metrics."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/observability/metrics")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        table = Table(title="Metrics", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")
        for k, v in payload.items():
            if not isinstance(v, (dict, list)):
                table.add_row(k, str(v))
        console.print(table)
    else:
        console.print(payload)


@observe_app.command("alerts")
def observe_alerts(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show active alerts."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/observability/alerts")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        alerts = payload.get("alerts", [])
        count = payload.get("count", len(alerts) if isinstance(alerts, list) else 0)
        if not alerts:
            console.print(f"[green]No active alerts. (count={count})[/green]")
            return
        table = Table(title="Alerts", show_header=True)
        table.add_column("Level", style="yellow")
        table.add_column("Message", style="white")
        for alert in (alerts if isinstance(alerts, list) else []):
            if isinstance(alert, dict):
                table.add_row(str(alert.get("level", "?")), str(alert.get("message", ""))[:80])
            else:
                table.add_row("?", str(alert)[:80])
        console.print(table)
    else:
        console.print(payload)


@observe_app.command("traces")
def observe_traces(
    limit: int = typer.Option(10, "--limit", help="Number of traces."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show recent traces."""
    config = _load_config()
    status_code, payload = _api_request(config, "GET", "/ops/observability/traces", params={"limit": limit})
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Traces", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Duration", style="dim")
        for t in payload:
            if isinstance(t, dict):
                table.add_row(
                    str(t.get("trace_id", t.get("id", "?")))[:12],
                    str(t.get("status", "?")),
                    str(t.get("duration_ms", t.get("duration", "?")))[:10],
                )
        console.print(table)
    else:
        console.print(payload)


if __name__ == "__main__":
    app()
