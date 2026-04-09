"""Server lifecycle commands: up, down, ps, and auto-start helper.

Innovation over SOTA:
- Port-based killing (not PID-based) — solves orphaned instances, PID recycling
- Graceful shutdown via HTTP endpoint before force-kill
- Instance discovery (`gimo ps`) — find ALL GIMO instances on any port
- psutil-based cross-platform process detection (no shell-out to netstat)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import typer

from gimo_cli import app, console
from gimo_cli.bond import gimo_home
from gimo_cli.config import DEFAULT_API_BASE_URL


def _pid_file() -> Path:
    return gimo_home() / "server.pid"


def _read_pid() -> int | None:
    """Read the stored PID. Returns None if file missing or invalid."""
    pf = _pid_file()
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
        if pid <= 0:
            pf.unlink(missing_ok=True)
            return None
        return pid
    except (ValueError, OSError):
        pf.unlink(missing_ok=True)
        return None


def server_healthy(url: str, timeout: float = 3.0) -> bool:
    """Check if a GIMO server is responding at the given URL."""
    try:
        resp = httpx.get(f"{url}/health", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _health_pid(url: str, timeout: float = 3.0) -> int | None:
    """Best-effort server PID from GET /health payload."""
    try:
        resp = httpx.get(f"{url}/health", timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        pid = data.get("pid")
        if isinstance(pid, int) and pid > 0:
            return pid
        if isinstance(pid, str) and pid.isdigit():
            parsed = int(pid)
            return parsed if parsed > 0 else None
    except Exception:
        return None
    return None


def _is_gimo_server(url: str, timeout: float = 3.0) -> bool:
    """Check if the server at URL is specifically a GIMO server (has server marker)."""
    try:
        resp = httpx.get(f"{url}/health", timeout=timeout)
        if resp.status_code != 200:
            return False
        data = resp.json()
        return data.get("server") == "gimo"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Port-based process discovery (psutil, cross-platform)
# ---------------------------------------------------------------------------

def _find_pids_on_port(port: int) -> list[int]:
    """Find ALL live PIDs listening on the given port using psutil.

    Cross-platform: works on Windows, Linux, macOS without shelling out.
    Filters out zombie connections (PID exists in kernel table but process is dead).
    """
    try:
        import psutil
    except ImportError:
        return _find_pids_on_port_fallback(port)

    pids: set[int] = set()
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status == "LISTEN" and conn.laddr.port == port:
            if conn.pid:
                # Verify the process actually exists (filters zombie TCP entries)
                try:
                    psutil.Process(conn.pid)
                    pids.add(conn.pid)
                except psutil.NoSuchProcess:
                    pass
    return sorted(pids)


def _find_pids_on_port_fallback(port: int) -> list[int]:
    """Fallback: find PIDs via netstat (when psutil unavailable)."""
    pids: set[int] = set()
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, check=False,
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and "LISTENING" in parts:
                    addr = parts[1]
                    if addr.endswith(f":{port}"):
                        try:
                            pids.add(int(parts[-1]))
                        except ValueError:
                            pass
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, check=False,
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
    """Kill a PID with graceful-first strategy. Returns True if killed/dead.

    Windows strategy:
    1. SIGBREAK → uvicorn catches it, runs lifespan cleanup, closes sockets
    2. Wait up to 10s for graceful exit
    3. taskkill /F only as last resort (may leave zombie sockets)

    Unix strategy:
    1. SIGTERM → uvicorn runs graceful shutdown
    2. Wait up to 10s
    3. SIGKILL as last resort
    """
    try:
        import psutil
        proc = psutil.Process(pid)
    except Exception:
        return True  # Already dead

    try:
        if sys.platform == "win32":
            # Step 1: SIGBREAK for graceful shutdown (uvicorn handles this)
            try:
                os.kill(pid, signal.SIGBREAK)
            except (OSError, ProcessLookupError):
                return True

            # Step 2: Wait for graceful exit
            try:
                proc.wait(timeout=10)
                return True
            except Exception:
                pass

            # Step 3: Force kill (last resort — may create zombie sockets)
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, check=False,
            )
            return True
        else:
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
    """Kill ALL processes on a port. Returns (found, killed).

    Strategy:
    1. Graceful shutdown via HTTP (server cleans up properly)
    2. Wait briefly for graceful exit
    3. Find remaining PIDs on port via psutil
    4. Force-kill any survivors
    """
    found = 0
    killed = 0

    # Step 1: Graceful shutdown via HTTP (cleanest — server closes sockets properly)
    graceful = _graceful_shutdown(url)
    if graceful:
        # Wait for uvicorn to complete lifespan cleanup + socket close
        for _ in range(15):
            time.sleep(1)
            if _port_is_free(port):
                return (1, 1)

    # Step 2: Find any remaining PIDs on port
    pids = _find_pids_on_port(port)
    found = len(pids)

    if not pids and graceful:
        return (1, 1)

    # Step 3: Kill survivors (graceful-first via SIGBREAK/SIGTERM)
    for pid in pids:
        if _kill_pid(pid):
            killed += 1

    # Step 4: Verify port is free
    time.sleep(1)
    remaining = _find_pids_on_port(port)
    for pid in remaining:
        _kill_pid(pid)

    # Step 5: Fallback by authoritative /health pid for orphaned worker cases.
    # On Windows + multiprocessing/reload, port scans can report stale/parent
    # PIDs while the live serving worker remains.
    runtime_pid = _health_pid(url, timeout=1.5)
    if runtime_pid:
        if _kill_pid(runtime_pid):
            killed += 1

    return (max(found, 1) if graceful else found, killed + (1 if graceful and found == 0 else 0))


def _port_is_free(port: int) -> bool:
    """Check if a port is free (no live process listening).

    On Windows, kernel may retain zombie TCP LISTEN entries after process death.
    We check if the owning process actually exists — if it's dead, we treat
    the port as free (the new process can bind with SO_REUSEADDR).
    """
    return len(_find_pids_on_port(port)) == 0


def _wait_for_server_stop(url: str, port: int, timeout_seconds: float = 10.0) -> bool:
    """Wait until server is consistently down (not just a transient probe miss)."""
    deadline = time.time() + timeout_seconds
    consecutive_down = 0
    while time.time() < deadline:
        port_busy = bool(_find_pids_on_port(port))
        healthy = server_healthy(url, timeout=1.0)
        if not port_busy and not healthy:
            consecutive_down += 1
            if consecutive_down >= 3:
                return True
        else:
            consecutive_down = 0
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_server(host: str = "127.0.0.1", port: int = 9325) -> bool:
    """Start the GIMO server in the background. Returns True on success."""
    url = f"http://{host}:{port}"

    # Already running and healthy? (verify it's actually GIMO, not a zombie)
    if _is_gimo_server(url):
        return True

    # Port occupied by a live process — clean up
    if not _port_is_free(port):
        _kill_all_on_port(port, url)
        time.sleep(0.5)
        if not _port_is_free(port):
            return False  # Can't free the port

    # Clean stale PID file
    _pid_file().unlink(missing_ok=True)

    from gimo_cli.config import project_root
    proj_root = project_root()

    env = os.environ.copy()
    env["ORCH_PORT"] = str(port)

    uvicorn_cmd = [
        sys.executable, "-m", "uvicorn", "tools.gimo_server.main:app",
        "--host", host, "--port", str(port),
        "--timeout-graceful-shutdown", "10",
    ]

    # Capture logs to ~/.gimo/server.log instead of discarding them
    log_path = gimo_home() / "server.log"
    log_file = open(log_path, "w", encoding="utf-8")

    try:
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP: required for SIGBREAK graceful shutdown
            # CREATE_NO_WINDOW: no console window flashing
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

    _pid_file().write_text(str(proc.pid), encoding="utf-8")

    # Readiness probe: wait for /ready (lifespan complete), not /health (immediate)
    def _is_ready() -> bool:
        try:
            resp = httpx.get(f"{url}/ready", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    with console.status("[bold green]Starting GIMO server...[/bold green]", spinner="dots"):
        for _ in range(90):
            time.sleep(1)
            if _is_ready():
                log_file.close()
                return True
            # Check if process died early
            try:
                import psutil
                psutil.Process(proc.pid)
            except Exception:
                break  # Process crashed

    log_file.close()
    _pid_file().unlink(missing_ok=True)
    return False


@app.command()
def up(
    port: int = typer.Option(9325, "--port", "-p", help="Port to run the server on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
) -> None:
    """Start the GIMO server in the background."""
    url = f"http://{host}:{port}"

    if server_healthy(url):
        try:
            resp = httpx.get(f"{url}/health", timeout=3.0)
            data = resp.json()
            pid = data.get("pid", "?")
            version = data.get("version", "unknown")
        except Exception:
            pid, version = "?", "unknown"
        console.print(f"[green][OK] Server already running (PID {pid}, v{version})[/green]")
        console.print(f"[dim]  {url}/health[/dim]")
        return

    # Port occupied by something else?
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
        try:
            resp = httpx.get(f"{url}/health", timeout=3.0)
            data = resp.json()
            pid = data.get("pid", "?")
            version = data.get("version", "unknown")
        except Exception:
            pid, version = _read_pid() or "?", "unknown"
        console.print(f"[green][OK] Server started (PID {pid}, v{version})[/green]")
        console.print(f"[dim]  {url}/health[/dim]")
    else:
        console.print("[red][X] Server failed to start within 90 seconds[/red]")
        console.print("[yellow]Check logs or try: python -m uvicorn tools.gimo_server.main:app[/yellow]")
        raise typer.Exit(1)


@app.command()
def down(
    port: int = typer.Option(9325, "--port", "-p", help="Port of the server to stop."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host the server is bound to."),
) -> None:
    """Stop ALL GIMO server instances on the given port."""
    url = f"http://{host}:{port}"

    # Check if anything is on this port
    pids = _find_pids_on_port(port)
    is_healthy = server_healthy(url)

    if not pids and not is_healthy:
        console.print(f"[yellow][!] No server found on port {port}[/yellow]")
        _pid_file().unlink(missing_ok=True)
        return

    if pids:
        console.print(f"[dim]Found {len(pids)} process(es) on port {port}: {pids}[/dim]")
    elif is_healthy:
        console.print(f"[dim]Server responding on {url} (PID not detected via port scan)[/dim]")

    # Kill everything
    found, killed = _kill_all_on_port(port, url)

    # Clean PID file
    _pid_file().unlink(missing_ok=True)

    # Verify with stability window to avoid shutdown race false-positives.
    remaining = _find_pids_on_port(port)
    runtime_alive = server_healthy(url, timeout=1.5)
    if runtime_alive:
        runtime_pid = _health_pid(url, timeout=1.5)
        if runtime_pid:
            _kill_pid(runtime_pid)
            time.sleep(0.5)
            remaining = _find_pids_on_port(port)
            runtime_alive = server_healthy(url, timeout=1.5)

    if remaining or runtime_alive or (not _wait_for_server_stop(url, port, timeout_seconds=8.0)):
        console.print(f"[red][X] {len(remaining)} process(es) still on port {port}: {remaining}[/red]")
        console.print("[yellow]Try: taskkill /F /PID <pid> (Windows) or kill -9 <pid> (Unix)[/yellow]")
        raise typer.Exit(1)

    console.print(f"[green][OK] Server stopped (killed {killed} process(es))[/green]")


@app.command()
def ps(
    scan_range: str = typer.Option("9325", "--ports", "-p", help="Ports to scan (comma-separated or range like 9320-9330)."),
) -> None:
    """Discover running GIMO server instances."""
    ports: list[int] = []
    for part in scan_range.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            ports.extend(range(int(start), int(end) + 1))
        else:
            ports.append(int(part))

    found_any = False
    for port in ports:
        pids = _find_pids_on_port(port)
        if not pids:
            continue

        url = f"http://127.0.0.1:{port}"
        healthy = server_healthy(url, timeout=1.5)
        version = "?"
        server_pid = "?"
        if healthy:
            try:
                resp = httpx.get(f"{url}/health", timeout=1.5)
                data = resp.json()
                version = data.get("version", "?")
                server_pid = data.get("pid", "?")
            except Exception:
                pass

        status = "[green]healthy[/green]" if healthy else "[red]unhealthy[/red]"
        pid_str = ", ".join(str(p) for p in pids)
        console.print(
            f"  Port {port}  |  PIDs: {pid_str}  |  {status}  |  v{version}"
        )
        found_any = True

    if not found_any:
        console.print(f"[dim]No GIMO instances found on port(s): {scan_range}[/dim]")
