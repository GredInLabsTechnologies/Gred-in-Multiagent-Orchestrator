"""Server lifecycle commands: up, down, ps, and auto-start helper."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

import httpx
import typer

from gimo_cli import app, console
from gimo_cli.bond import gimo_home
from gimo_cli.config import DEFAULT_API_BASE_URL


def _default_server_location() -> tuple[str, int]:
    parsed = urlparse(DEFAULT_API_BASE_URL)
    return parsed.hostname or "127.0.0.1", parsed.port or 9325


DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT = _default_server_location()


def _server_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _probe_json(url: str, path: str = "/health", timeout: float = 3.0) -> dict[str, object] | None:
    try:
        resp = httpx.get(f"{url}{path}", timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else {}


def server_healthy(url: str, timeout: float = 3.0) -> bool:
    """Check if a GIMO server is responding at the given URL."""
    return _probe_json(url, "/health", timeout=timeout) is not None


def _health_details(url: str, timeout: float = 3.0) -> tuple[str | int, str]:
    data = _probe_json(url, "/health", timeout=timeout) or {}
    return data.get("pid", "?"), str(data.get("version", "unknown"))


def _health_pid(url: str, timeout: float = 3.0) -> int | None:
    data = _probe_json(url, "/health", timeout=timeout)
    if not data:
        return None
    pid = data.get("pid")
    if isinstance(pid, int) and pid > 0:
        return pid
    if isinstance(pid, str) and pid.isdigit():
        parsed = int(pid)
        return parsed if parsed > 0 else None
    return None


def _is_connection_refused(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ConnectionRefusedError):
            return True
        errno = getattr(current, "errno", None)
        if errno in {61, 111, 10061}:
            return True
        text = str(current).lower()
        if "connection refused" in text or "actively refused" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


def _wait_for_ready(url: str, proc: subprocess.Popen, timeout_seconds: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _probe_json(url, "/ready", timeout=1.5) is not None:
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def _wait_for_health_refusal(url: str, timeout_seconds: float = 10.0) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    deadline = time.monotonic() + timeout_seconds
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            code = sock.connect_ex((host, port))
        if code in {61, 111, 10061}:
            return True
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    return False


def _wait_for_server_down(url: str, port: int, timeout_seconds: float = 15.0) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _wait_for_health_refusal(url, timeout_seconds=0.0):
            return "refused"
        if _port_is_free(port) and not server_healthy(url, timeout=1.0):
            return "unreachable"
        time.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# Port-based process discovery fallback
# ---------------------------------------------------------------------------

def _find_pids_on_port(port: int) -> list[int]:
    """Find live PIDs listening on the given port."""
    try:
        import psutil
    except ImportError:
        return _find_pids_on_port_fallback(port)

    pids: set[int] = set()
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status == "LISTEN" and conn.laddr.port == port and conn.pid:
            try:
                psutil.Process(conn.pid)
                pids.add(conn.pid)
            except psutil.NoSuchProcess:
                pass
    return sorted(pids)


def _find_pids_on_port_fallback(port: int) -> list[int]:
    """Fallback: find PIDs via netstat/lsof when psutil is unavailable."""
    pids: set[int] = set()
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and "LISTENING" in parts and parts[1].endswith(f":{port}"):
                    try:
                        pids.add(int(parts[-1]))
                    except ValueError:
                        pass
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.strip().splitlines():
                try:
                    pids.add(int(line.strip()))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return sorted(pids)


def _graceful_shutdown(url: str, timeout: float = 3.0) -> bool:
    """Ask the server to self-terminate via POST /ops/shutdown."""
    try:
        resp = httpx.post(f"{url}/ops/shutdown", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _kill_pid(pid: int) -> bool:
    """Kill a PID with graceful-first strategy."""
    try:
        import psutil

        proc = psutil.Process(pid)
    except Exception:
        return True

    try:
        if sys.platform == "win32":
            try:
                os.kill(pid, signal.SIGBREAK)
            except (OSError, ProcessLookupError):
                return True

            try:
                proc.wait(timeout=10)
                return True
            except Exception:
                pass

            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
            return True

        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                return True
        os.kill(pid, signal.SIGKILL)
        return True
    except (OSError, ProcessLookupError):
        return True


def _kill_all_on_port(port: int, url: str) -> tuple[int, int]:
    """Kill all listeners on a port, preferring graceful HTTP shutdown."""
    pids = set(_find_pids_on_port(port))
    runtime_pid = _health_pid(url, timeout=1.5)
    if runtime_pid:
        pids.add(runtime_pid)

    graceful = _graceful_shutdown(url)
    if graceful and _wait_for_port_free(port, timeout_seconds=15.0):
        count = max(len(pids), 1)
        return count, count

    killed = 0
    for pid in sorted(pids):
        if _kill_pid(pid):
            killed += 1

    found = len(pids) or (1 if graceful else 0)
    return found, killed or (1 if graceful else 0)


def _port_is_free(port: int) -> bool:
    return len(_find_pids_on_port(port)) == 0


def _wait_for_port_free(port: int, timeout_seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _port_is_free(port):
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _resolve_launcher_python(
    proj_root, env: dict
) -> tuple[str, "str | None", str]:
    """Decide which Python interpreter to use for the server.

    Plan 2026-04-16 Change 6: if a runtime bundle is present next to the launcher,
    extract it lazily and boot through the bundled Python. This makes the desktop
    path symmetric with Android (both consume the same signed bundle).

    Returns a tuple ``(python_exe, pythonpath_extra, provenance)`` where
    ``provenance`` is ``"bundle"`` or ``"host"`` for audit logs.
    """
    from pathlib import Path as _P
    assets_override = env.get("ORCH_RUNTIME_ASSETS_DIR", "").strip()
    assets_dir = _P(assets_override) if assets_override else _P(proj_root) / "runtime-assets"
    manifest_path = assets_dir / "gimo-core-runtime.json"
    if not manifest_path.exists():
        return sys.executable, None, "host"

    # Bundle present — extract lazily and launch through it
    try:
        from tools.gimo_server.services.runtime_bootstrap import (
            RuntimeBootstrapError,
            ensure_extracted,
        )
        target_dir = _P(env.get("ORCH_RUNTIME_DIR", "") or (_P(proj_root) / "runtime"))
        pub_pem = env.get("ORCH_RUNTIME_PUBLIC_KEY", "")
        allow_unsigned = env.get("ORCH_RUNTIME_ALLOW_UNSIGNED", "").lower() in {"1", "true", "yes"}
        # BUGS_LATENTES §H8: escape hatch para tests / bundles sintéticos en
        # hosts cross-ABI. En producción siempre False para que el probe
        # atrape ABI mismatch temprano.
        skip_probe = env.get("ORCH_RUNTIME_SKIP_EXEC_PROBE", "").lower() in {"1", "true", "yes"}
        result = ensure_extracted(
            assets_dir, target_dir,
            public_key_pem=pub_pem or None,
            allow_unsigned=allow_unsigned,
            skip_exec_probe=skip_probe,
        )
        return str(result.python_binary), str(result.repo_root), "bundle"
    except (RuntimeBootstrapError, Exception) as exc:
        # Fallback to host interpreter — but make the reason loud in the console.
        console.print(
            f"[yellow][!] Runtime bundle found but bootstrap failed: {exc}[/yellow]"
        )
        console.print("[dim]Falling back to host Python.[/dim]")
        return sys.executable, None, "host"


def start_server(host: str = DEFAULT_SERVER_HOST, port: int = DEFAULT_SERVER_PORT) -> bool:
    """Start the GIMO server in the background. Returns True on success."""
    url = _server_url(host, port)
    if server_healthy(url):
        return True

    if not _port_is_free(port):
        _kill_all_on_port(port, url)
        time.sleep(0.5)
        if not _port_is_free(port):
            return False

    from gimo_cli.config import project_root

    proj_root = project_root()
    env = os.environ.copy()
    env["ORCH_PORT"] = str(port)

    # Plan 2026-04-16 Change 6: bundle-aware interpreter selection
    python_exe, pythonpath_extra, provenance = _resolve_launcher_python(proj_root, env)
    if pythonpath_extra:
        existing = env.get("PYTHONPATH", "")
        sep = ";" if sys.platform == "win32" else ":"
        env["PYTHONPATH"] = pythonpath_extra if not existing else f"{pythonpath_extra}{sep}{existing}"
    if provenance == "bundle":
        console.print("[dim][OK] Booting through runtime bundle[/dim]")

    uvicorn_cmd = [
        python_exe,
        "-m",
        "uvicorn",
        "tools.gimo_server.main:app",
        "--host",
        host,
        "--port",
        str(port),
        "--timeout-graceful-shutdown",
        "10",
    ]

    log_path = gimo_home() / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")

    try:
        if sys.platform == "win32":
            creation_flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            )
            proc = subprocess.Popen(
                uvicorn_cmd,
                cwd=str(proj_root),
                env=env,
                stdout=log_file,
                stderr=log_file,
                creationflags=creation_flags,
            )
        else:
            proc = subprocess.Popen(
                uvicorn_cmd,
                cwd=str(proj_root),
                env=env,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
    except Exception:
        log_file.close()
        raise

    with console.status("[bold green]Starting GIMO server...[/bold green]", spinner="dots"):
        ready = _wait_for_ready(url, proc, timeout_seconds=90.0)

    if not ready and proc.poll() is None:
        _kill_pid(proc.pid)
    log_file.close()
    return ready


@app.command()
def up(
    port: int = typer.Option(DEFAULT_SERVER_PORT, "--port", "-p", help="Port to run the server on."),
    host: str = typer.Option(DEFAULT_SERVER_HOST, "--host", help="Host to bind to."),
) -> None:
    """Start the GIMO server in the background."""
    url = _server_url(host, port)

    if server_healthy(url):
        pid, version = _health_details(url)
        console.print(f"[green][OK] Server already running at {url}[/green]")
        console.print(f"[dim]  PID {pid} | v{version}[/dim]")
        return

    if not _port_is_free(port):
        occupants = _find_pids_on_port(port)
        console.print(f"[yellow][!] Port {port} occupied by PID(s): {occupants}[/yellow]")
        console.print("[dim]Cleaning up...[/dim]")
        _kill_all_on_port(port, url)
        time.sleep(0.5)
        if not _port_is_free(port):
            console.print(f"[red][X] Cannot free port {port}. Kill manually.[/red]")
            raise typer.Exit(1)

    console.print(f"[bold]Starting GIMO server on {url}...[/bold]")
    if start_server(host, port):
        pid, version = _health_details(url)
        console.print(f"[green][OK] Server started at {url}[/green]")
        console.print(f"[dim]  PID {pid} | v{version} | /ready=200[/dim]")
        return

    console.print(f"[red][X] Server failed to become ready at {url} within 90 seconds[/red]")
    console.print(f"[yellow]Check logs: {gimo_home() / 'server.log'}[/yellow]")
    raise typer.Exit(1)


@app.command()
def down(
    port: int = typer.Option(DEFAULT_SERVER_PORT, "--port", "-p", help="Port of the server to stop."),
    host: str = typer.Option(DEFAULT_SERVER_HOST, "--host", help="Host the server is bound to."),
) -> None:
    """Stop the GIMO server running on the given host/port."""
    url = _server_url(host, port)
    health_before = _probe_json(url, "/health", timeout=1.5)
    pids = _find_pids_on_port(port)

    if not health_before and not pids:
        console.print(f"[yellow][!] No server found at {url}[/yellow]")
        return

    if health_before:
        console.print(f"[bold]Stopping GIMO server at {url}...[/bold]")
    if pids:
        console.print(f"[dim]Listener PID(s): {pids}[/dim]")

    found, killed = _kill_all_on_port(port, url)
    down_state = _wait_for_server_down(url, port, timeout_seconds=15.0)
    if down_state is None:
        remaining = _find_pids_on_port(port)
        console.print(f"[red][X] {url}/health did not fall to connection-refused[/red]")
        console.print(f"[yellow]Remaining listener PID(s): {remaining}[/yellow]")
        raise typer.Exit(1)

    if down_state == "refused":
        console.print(f"[green][OK] Server stopped and {url}/health now refuses connections[/green]")
    else:
        console.print(f"[green][OK] Server stopped and {url}/health is no longer reachable[/green]")
    console.print(f"[dim]  Found {found} listener(s); terminated {killed}[/dim]")


@app.command()
def ps(
    scan_range: str = typer.Option(
        str(DEFAULT_SERVER_PORT),
        "--ports",
        "-p",
        help="Ports to scan (comma-separated or range like 9320-9330).",
    ),
    host: str = typer.Option(DEFAULT_SERVER_HOST, "--host", help="Host to probe."),
) -> None:
    """Discover running GIMO server instances by probing /health on each port."""
    ports: list[int] = []
    for part in scan_range.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start, end = item.split("-", 1)
            ports.extend(range(int(start), int(end) + 1))
        else:
            ports.append(int(item))

    found_any = False
    for port in ports:
        url = _server_url(host, port)
        data = _probe_json(url, "/health", timeout=1.5)
        if data is None:
            continue
        version = data.get("version", "?")
        server_pid = data.get("pid", "?")
        console.print(f"  Port {port}  |  PID: {server_pid}  |  [green]healthy[/green]  |  v{version}")
        found_any = True

    if not found_any:
        console.print(f"[dim]No GIMO instances found on port(s): {scan_range}[/dim]")
