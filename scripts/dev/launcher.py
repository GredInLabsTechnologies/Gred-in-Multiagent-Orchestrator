"""GIMO Dev Launcher — Single-terminal process manager with interactive control.

Launches backend (uvicorn --reload), frontend (vite), and web (next dev)
in a single terminal with color-coded multiplexed logs and interactive commands.

Usage:
    python scripts/dev/launcher.py          # launch all
    python scripts/dev/launcher.py --no-web # skip web app
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

SERVICES: dict[str, dict] = {
    "backend": {
        "cmd_win": f'"{PYTHON}" -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325 --reload --reload-dir tools/gimo_server --log-level info',
        "cmd_unix": f"{PYTHON} -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325 --reload --reload-dir tools/gimo_server --log-level info",
        "color": "\033[96m",  # cyan
        "health_url": "http://127.0.0.1:9325/auth/check",
        "port": 9325,
    },
    "frontend": {
        "cmd_win": "npm run dev -- --host 127.0.0.1",
        "cmd_unix": "npm run dev -- --host 127.0.0.1",
        "cwd": str(ROOT / "tools" / "orchestrator_ui"),
        "color": "\033[93m",  # yellow
        "port": 5173,
    },
    "web": {
        "cmd_win": "npm run dev",
        "cmd_unix": "npm run dev",
        "cwd": str(ROOT / "apps" / "web"),
        "color": "\033[95m",  # magenta
        "port": 3000,
    },
}

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"

# ── Helpers ─────────────────────────────────────────────────────────────

def _build_provenance_env() -> dict:
    """R18 Change 10 — inject GIMO_BUILD_SHA so the backend reports the
    exact commit it was booted from via /ops/health/info."""
    if os.environ.get("GIMO_BUILD_SHA"):
        return {}
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0:
            return {"GIMO_BUILD_SHA": out.stdout.strip()}
    except Exception:
        pass
    return {}


def _enable_win_ansi():
    """Enable ANSI escape codes on Windows 10+ and force UTF-8 stdout."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass
    # Force UTF-8 output to avoid charmap encoding errors
    if sys.stdout.encoding != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _print_banner():
    print(f"""
{BOLD}{CYAN}========================================================
              GIMO Dev Launcher
========================================================{RESET}
""")


def _log(service: str, color: str, line: str):
    """Print a log line with service prefix."""
    tag = f"{color}{BOLD}[{service:>8}]{RESET}"
    print(f"{tag} {line}", flush=True)


def _sys_log(msg: str):
    print(f"{DIM}[launcher]{RESET} {msg}", flush=True)


async def _kill_port(port: int):
    """Kill any process on the given port."""
    if sys.platform == "win32":
        proc = await asyncio.create_subprocess_shell(
            f'for /f "tokens=5" %a in (\'netstat -aon ^| findstr :{port} ^| findstr LISTENING\') do taskkill /F /PID %a',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    else:
        proc = await asyncio.create_subprocess_shell(
            f"lsof -ti :{port} | xargs -r kill -9",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()


async def _health_check(url: str, timeout: float = 30.0) -> bool:
    """Wait for a URL to respond with 2xx/401."""
    import urllib.request
    import urllib.error
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=2)
            if resp.status < 500:
                return True
        except urllib.error.HTTPError as e:
            if e.code < 500:  # 401 = auth required = server is up
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


# ── Process Manager ────────────────────────────────────────────────────

class ServiceProcess:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.process: asyncio.subprocess.Process | None = None
        self._read_task: asyncio.Task | None = None
        self.running = False
        self.restart_count = 0

    async def start(self):
        if self.process and self.process.returncode is None:
            return

        cwd = self.config.get("cwd", str(ROOT))
        color = self.config["color"]
        cmd = self.config["cmd_win"] if sys.platform == "win32" else self.config["cmd_unix"]

        _log(self.name, color, f"Starting...")
        self.process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "1", **_build_provenance_env()},
        )
        self.running = True
        self._read_task = asyncio.create_task(self._stream_output())
        _log(self.name, color, f"PID {self.process.pid}")

    async def _stream_output(self):
        color = self.config["color"]
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    _log(self.name, color, decoded)
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            rc = self.process.returncode
            _log(self.name, color, f"Exited (code={rc})")

    async def stop(self):
        if not self.process or self.process.returncode is not None:
            self.running = False
            return
        color = self.config["color"]
        _log(self.name, color, "Stopping...")
        try:
            if sys.platform == "win32":
                # On Windows, kill the process tree
                kill_proc = await asyncio.create_subprocess_shell(
                    f"taskkill /F /T /PID {self.process.pid}",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await kill_proc.wait()
            else:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self.process.kill()
        except ProcessLookupError:
            pass
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        self.running = False
        _log(self.name, color, "Stopped.")

    async def restart(self):
        self.restart_count += 1
        await self.stop()
        await asyncio.sleep(0.5)
        await self.start()


class Launcher:
    def __init__(self, skip_services: set[str] | None = None):
        self.skip = skip_services or set()
        self.services: dict[str, ServiceProcess] = {}
        self._shutdown_event = asyncio.Event()

    async def start_all(self):
        """Kill stale ports and launch all services."""
        _sys_log("Cleaning stale ports...")
        tasks = []
        for name, cfg in SERVICES.items():
            if name not in self.skip:
                tasks.append(_kill_port(cfg["port"]))
        await asyncio.gather(*tasks)
        await asyncio.sleep(0.3)

        # Start backend first, wait for health, then frontend/web
        if "backend" not in self.skip:
            svc = ServiceProcess("backend", SERVICES["backend"])
            self.services["backend"] = svc
            await svc.start()

            _sys_log("Waiting for backend health...")
            health_url = SERVICES["backend"]["health_url"]
            ok = await _health_check(health_url, timeout=30)
            if ok:
                _sys_log(f"{GREEN}Backend ready.{RESET}")
            else:
                _sys_log(f"{YELLOW}Backend slow to start, continuing...{RESET}")

        # Start frontend and web in parallel
        parallel = []
        for name in ("frontend", "web"):
            if name not in self.skip:
                svc = ServiceProcess(name, SERVICES[name])
                self.services[name] = svc
                parallel.append(svc.start())
        if parallel:
            await asyncio.gather(*parallel)

        self._print_status()
        self._print_commands()

    def _print_status(self):
        print()
        _sys_log(f"{GREEN}{BOLD}All services launched:{RESET}")
        if "backend" in self.services:
            _sys_log(f"  Backend:  {CYAN}http://127.0.0.1:9325{RESET}")
        if "frontend" in self.services:
            _sys_log(f"  UI:       {YELLOW}http://127.0.0.1:5173{RESET}")
        if "web" in self.services:
            _sys_log(f"  Web:      {YELLOW}http://localhost:3000{RESET}")
        print()

    def _print_commands(self):
        print(f"{DIM}─── Commands ──────────────────────────────────────────{RESET}")
        print(f"  {BOLD}r{RESET} / {BOLD}restart{RESET}    Restart backend (hot-ish reload)")
        print(f"  {BOLD}rf{RESET}             Restart frontend")
        print(f"  {BOLD}ra{RESET}             Restart all")
        print(f"  {BOLD}s{RESET} / {BOLD}status{RESET}     Show service status")
        print(f"  {BOLD}q{RESET} / {BOLD}quit{RESET}       Stop all and exit")
        print(f"  {BOLD}Ctrl+C{RESET}         Stop all and exit")
        print(f"{DIM}──────────────────────────────────────────────────────{RESET}")
        print()

    async def _handle_command(self, cmd: str):
        cmd = cmd.strip().lower()
        if cmd in ("q", "quit", "exit", "stop"):
            _sys_log("Shutting down all services...")
            await self.stop_all()
            self._shutdown_event.set()

        elif cmd in ("r", "restart", "rb"):
            if "backend" in self.services:
                _sys_log(f"{YELLOW}Restarting backend...{RESET}")
                await self.services["backend"].restart()
                ok = await _health_check(SERVICES["backend"]["health_url"], timeout=15)
                if ok:
                    _sys_log(f"{GREEN}Backend restarted OK.{RESET}")
                else:
                    _sys_log(f"{RED}Backend may not be healthy.{RESET}")
            else:
                _sys_log("Backend not running.")

        elif cmd == "rf":
            if "frontend" in self.services:
                _sys_log(f"{YELLOW}Restarting frontend...{RESET}")
                await self.services["frontend"].restart()
            else:
                _sys_log("Frontend not running.")

        elif cmd == "rw":
            if "web" in self.services:
                _sys_log(f"{YELLOW}Restarting web...{RESET}")
                await self.services["web"].restart()
            else:
                _sys_log("Web not running.")

        elif cmd == "ra":
            _sys_log(f"{YELLOW}Restarting all services...{RESET}")
            for svc in self.services.values():
                await svc.restart()
            if "backend" in self.services:
                await _health_check(SERVICES["backend"]["health_url"], timeout=15)
            _sys_log(f"{GREEN}All services restarted.{RESET}")

        elif cmd in ("s", "status"):
            print()
            for name, svc in self.services.items():
                color = svc.config["color"]
                state = f"{GREEN}RUNNING{RESET}" if svc.running else f"{RED}STOPPED{RESET}"
                restarts = f" (restarts: {svc.restart_count})" if svc.restart_count else ""
                pid = f" PID {svc.process.pid}" if svc.process and svc.process.returncode is None else ""
                print(f"  {color}{BOLD}{name:>8}{RESET}  {state}{pid}{restarts}")
            print()

        elif cmd in ("h", "help", "?"):
            self._print_commands()

        elif cmd == "":
            pass  # ignore empty

        else:
            _sys_log(f"Unknown command: {cmd}. Type 'h' for help.")

    async def _input_loop(self):
        """Read commands from stdin asynchronously."""
        loop = asyncio.get_event_loop()
        while not self._shutdown_event.is_set():
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:  # EOF
                    break
                await self._handle_command(line)
            except (EOFError, KeyboardInterrupt):
                break

    async def stop_all(self):
        """Stop all services gracefully."""
        stops = [svc.stop() for svc in self.services.values()]
        await asyncio.gather(*stops, return_exceptions=True)

    async def run(self):
        """Main entry point."""
        _enable_win_ansi()
        _print_banner()

        # Handle Ctrl+C
        if sys.platform != "win32":
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self._graceful_shutdown()))

        await self.start_all()

        # Open browser
        try:
            import webbrowser
            webbrowser.open("http://127.0.0.1:5173")
        except Exception:
            pass

        # Run input loop
        try:
            await self._input_loop()
        except KeyboardInterrupt:
            pass
        finally:
            _sys_log("Cleaning up...")
            await self.stop_all()
            _sys_log(f"{GREEN}All services stopped. Goodbye.{RESET}")

    async def _graceful_shutdown(self):
        _sys_log("Signal received, shutting down...")
        await self.stop_all()
        self._shutdown_event.set()


def _run_detached(skip: set[str]) -> int:
    """Headless / non-interactive launcher.

    The interactive ``Launcher`` above multiplexes child stdout via
    ``asyncio.subprocess.PIPE``. On Windows this binds the children's
    pipes to the parent loop's proactor — when the parent shell detaches
    (Claude Code background mode, CI, ``gimo.cmd up`` from a hook), the
    pipes are closed under the children, uvicorn loops on
    ``ValueError: I/O operation on closed pipe``, and never binds 9325.

    Detached mode sidesteps this by:
      - Using plain ``subprocess.Popen`` with file-backed stdout/stderr
        (no asyncio loop, no inherited pipes).
      - On Windows, ``CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`` so
        the children survive the parent.
      - Writing PIDs to ``.orch_data/runtime/launcher.pids.json`` for
        ``gimo down`` to consume.
      - Polling the health URL and exiting 0 once the backend is up.
    """
    import json
    import subprocess
    import urllib.request
    import urllib.error

    runtime = ROOT / ".orch_data" / "runtime"
    logs = ROOT / ".orch_data" / "logs"
    runtime.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    pids: dict[str, int] = {}
    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        creationflags = 0x00000200 | 0x00000008

    env = {**os.environ, "PYTHONUNBUFFERED": "1", **_build_provenance_env()}

    def _spawn(name: str, cfg: dict) -> int:
        cmd = cfg["cmd_win"] if sys.platform == "win32" else cfg["cmd_unix"]
        cwd = cfg.get("cwd", str(ROOT))
        log_path = logs / f"{name}.log"
        # Open in append mode so successive runs preserve history.
        fh = open(log_path, "ab", buffering=0)
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=True,
            stdout=fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=creationflags,
            close_fds=True,
        )
        _sys_log(f"{name} detached PID {proc.pid} -> {log_path}")
        return proc.pid

    # Free stale ports first (synchronous best-effort).
    for name, cfg in SERVICES.items():
        if name in skip:
            continue
        try:
            if sys.platform == "win32":
                subprocess.run(
                    f'for /f "tokens=5" %a in (\'netstat -aon ^| findstr :{cfg["port"]} ^| findstr LISTENING\') do taskkill /F /PID %a',
                    shell=True, capture_output=True, timeout=5,
                )
            else:
                subprocess.run(
                    f"lsof -ti :{cfg['port']} | xargs -r kill -9",
                    shell=True, capture_output=True, timeout=5,
                )
        except Exception:
            pass

    # Backend first.
    if "backend" not in skip:
        pids["backend"] = _spawn("backend", SERVICES["backend"])

    # Health check.
    health_ok = False
    if "backend" not in skip:
        url = SERVICES["backend"]["health_url"]
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(url, method="GET")
                resp = urllib.request.urlopen(req, timeout=2)
                if resp.status < 500:
                    health_ok = True
                    break
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    health_ok = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if health_ok:
            _sys_log(f"{GREEN}Backend ready (detached).{RESET}")
        else:
            _sys_log(f"{RED}Backend did not respond on {url} within 60s.{RESET}")

    # Frontend / web.
    for name in ("frontend", "web"):
        if name not in skip:
            pids[name] = _spawn(name, SERVICES[name])

    (runtime / "launcher.pids.json").write_text(
        json.dumps({"pids": pids, "started_at": time.time()}, indent=2),
        encoding="utf-8",
    )

    if "backend" in skip or health_ok:
        _sys_log(f"{GREEN}Detached launch complete. PIDs: {pids}{RESET}")
        return 0
    return 1


async def main():
    skip = set()
    if "--no-web" in sys.argv:
        skip.add("web")
    if "--no-frontend" in sys.argv:
        skip.add("frontend")
    if "--backend-only" in sys.argv:
        skip.add("frontend")
        skip.add("web")

    # Auto-detect headless context: no TTY on stdin → use detached mode.
    detached = "--detached" in sys.argv or "--headless" in sys.argv
    if not detached and not sys.stdin.isatty():
        detached = True

    if detached:
        rc = _run_detached(skip)
        sys.exit(rc)

    launcher = Launcher(skip_services=skip)
    await launcher.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{DIM}[launcher]{RESET} Interrupted. Exiting.")
