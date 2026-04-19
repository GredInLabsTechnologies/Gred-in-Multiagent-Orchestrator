"""Shared subprocess helpers with Windows .cmd shim compatibility.

Both auth services (claude, codex) and the provider catalog need to
spawn CLI subprocesses.  The Windows shell=True dance and timeout
handling are identical — this module is the single implementation.
"""
from __future__ import annotations

import subprocess
import sys


def popen_compat(args: list[str], **kwargs) -> subprocess.Popen:
    """Spawn a subprocess; use shell=True on Windows for .cmd shim compat."""
    if sys.platform == "win32":
        return subprocess.Popen(" ".join(args), shell=True, **kwargs)  # nosec B602
    return subprocess.Popen(args, **kwargs)


def run_cli(args: list[str], timeout: float = 8) -> tuple[int, str]:
    """Run a command synchronously and return (returncode, combined_output).

    Raises subprocess.TimeoutExpired on timeout (after killing the child).
    """
    try:
        proc = popen_compat(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, (out or b"").decode("utf-8", errors="replace").strip()
    except subprocess.TimeoutExpired as exc:
        try:
            exc.process.kill()
        except Exception:
            pass
        raise
