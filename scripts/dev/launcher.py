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

# ── Win32 Job Object — zero-orphan guarantee ────────────────────────────
#
# A Windows Job Object with KILL_ON_JOB_CLOSE binds every assigned process
# (and every descendant they spawn) to the launcher's lifetime. When the
# launcher's handle to the job closes for ANY reason — Ctrl-C, kill -9 of
# the launcher, parent shell teardown, segfault, OOM — the kernel kills
# every member of the job atomically. There is no way for a child to
# outlive the launcher and become a zombie / orphan listener.
#
# This is the only mechanism on Windows that gives a HARD guarantee. We
# create the job at module import time so even an early crash inside
# Launcher.run() still cleans up. The handle is held by a module-level
# global so the GC cannot collapse it before we want it to.
_JOB_HANDLE = None  # type: ignore[var-annotated]


def _create_job_object():
    global _JOB_HANDLE
    if sys.platform != "win32":
        return None
    if _JOB_HANDLE is not None:
        return _JOB_HANDLE
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # CreateJobObjectW(NULL, NULL) — anonymous, default security
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        h_job = kernel32.CreateJobObjectW(None, None)
        if not h_job:
            raise OSError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")

        # JOBOBJECT_BASIC_LIMIT_INFORMATION + EXTENDED variant.
        # We only need LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000).
        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE

        # JobObjectExtendedLimitInformation = 9
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ]
        ok = kernel32.SetInformationJobObject(
            h_job, 9, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok:
            raise OSError(f"SetInformationJobObject failed: {ctypes.get_last_error()}")

        _JOB_HANDLE = h_job
        return _JOB_HANDLE
    except Exception as exc:
        # Fail loudly — without the Job Object, zero-orphan is not a guarantee.
        print(f"[launcher] FATAL: cannot create Job Object: {exc}", file=sys.stderr)
        return None


def _assign_to_job(pid: int) -> None:
    if sys.platform != "win32":
        return
    if _JOB_HANDLE is None:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    h_proc = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if not h_proc:
        raise OSError(f"OpenProcess({pid}) failed: {ctypes.get_last_error()}")
    try:
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        ok = kernel32.AssignProcessToJobObject(_JOB_HANDLE, h_proc)
        if not ok:
            raise OSError(
                f"AssignProcessToJobObject({pid}) failed: {ctypes.get_last_error()}"
            )
    finally:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle(h_proc)


def _preflight_port(port: int) -> tuple[bool, str]:
    """Return (ok, reason). ok=False if the port is held by a zombie TCB."""
    if sys.platform != "win32":
        return True, ""
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$c=Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue;"
             f"if($c){{$p=Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue;"
             f"if(-not $p){{Write-Output ('ZOMBIE:'+$c.OwningProcess)}}else{{Write-Output ('OWNED:'+$p.Id+':'+$p.Name)}}}}else{{Write-Output 'FREE'}}"],
            capture_output=True, text=True, timeout=5,
        )
        line = (out.stdout or "").strip().splitlines()[-1] if out.stdout else "FREE"
        if line == "FREE":
            return True, ""
        if line.startswith("ZOMBIE:"):
            return False, f"port {port} held by orphan TCB (PID {line.split(':',1)[1]} no longer exists). Cannot proceed without leaving more orphans. Wait for kernel GC, change port, or reboot."
        # OWNED by a real process — kill_port can handle it; not a zombie.
        return True, ""
    except Exception:
        return True, ""


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

        # ZERO-ORPHAN POLICY: uvicorn --reload forks a watcher+worker pair.
        # On Windows the watcher cannot guarantee the worker dies cleanly,
        # which is the source of the orphan-listener / zombie-TCB class of
        # bugs that leak port 9325. We do not allow that fork pattern. The
        # Job Object below catches everything else (Ctrl-C, parent kill,
        # crash) but cannot save us from a known-leaky child design.
        if self.name == "backend":
            cmd = cmd.replace(" --reload --reload-dir tools/gimo_server", "")

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
        # Bind this child (and every grandchild it spawns) to the launcher's
        # Job Object so the kernel guarantees it dies with us. This is the
        # only Windows-native way to make zero-orphan a hard guarantee.
        try:
            _assign_to_job(self.process.pid)
        except Exception as exc:
            _sys_log(f"{YELLOW}WARN: failed to assign {self.name} pid={self.process.pid} to Job Object: {exc}{RESET}")

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

        # Zero-orphan guarantee: create the Job Object BEFORE spawning anything.
        # If creation fails on Windows we abort — running without it would
        # silently regress to the orphan-listener / zombie-TCB class of bugs.
        if sys.platform == "win32":
            if _create_job_object() is None:
                _sys_log(f"{RED}FATAL: Job Object unavailable; refusing to spawn children to avoid orphans.{RESET}")
                sys.exit(2)
            _sys_log(f"{GREEN}Job Object active — children will die with launcher.{RESET}")

        # Pre-flight: refuse to start on top of an orphan TCB.
        for name, cfg in SERVICES.items():
            if name in self.skip:
                continue
            ok, reason = _preflight_port(cfg["port"])
            if not ok:
                _sys_log(f"{RED}FATAL: {reason}{RESET}")
                sys.exit(3)

        # Persist launcher PID so `gimo down` can authoritatively cascade
        # the kill (taskkill /F /T <launcher_pid> closes the Job handle and
        # the kernel collapses every member atomically).
        try:
            runtime = ROOT / ".orch_data" / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "launcher.pid").write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

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


async def main():
    skip = set()
    if "--no-web" in sys.argv:
        skip.add("web")
    if "--no-frontend" in sys.argv:
        skip.add("frontend")
    if "--backend-only" in sys.argv:
        skip.add("frontend")
        skip.add("web")

    # ZERO-ORPHAN POLICY: there is no detached / fire-and-forget mode.
    # The launcher always runs in the foreground attached to its parent
    # shell and owns a Win32 Job Object that kills every child the moment
    # the launcher exits (for ANY reason). Background usage is the parent
    # shell's responsibility (e.g. `gimo up &`); `gimo down` then kills the
    # launcher PID and the kernel collapses the entire process tree.
    launcher = Launcher(skip_services=skip)
    await launcher.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{DIM}[launcher]{RESET} Interrupted. Exiting.")
