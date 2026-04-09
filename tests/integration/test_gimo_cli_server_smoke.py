from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _run_cli(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "gimo_cli", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _format_result(result: subprocess.CompletedProcess[str]) -> str:
    return f"command={result.args!r}\nexit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def _health_is_up(base_url: str) -> bool:
    try:
        return httpx.get(f"{base_url}/health", timeout=1.0).status_code == 200
    except Exception:
        return False


def _wait_for_health_down(base_url: str, timeout_seconds: float = 15.0) -> bool:
    parsed = httpx.URL(base_url)
    host = parsed.host or "127.0.0.1"
    port = parsed.port or 80
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            code = sock.connect_ex((host, port))
        if code in {61, 111, 10061}:
            return True
        if not _health_is_up(base_url):
            return True
        time.sleep(0.5)
    return False


@pytest.mark.integration
@pytest.mark.timeout(120)
def test_gimo_cli_server_smoke_up_ps_doctor_down(tmp_path):
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "GIMO_HOME": str(tmp_path / "gimo-home"),
            "GIMO_API_URL": base_url,
            "ORCH_API_URL": base_url,
            "ORCH_BASE_URL": base_url,
            "ORCH_TOKEN": "smoke-test-token-00000000000000000000000000000000",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )

    try:
        up = _run_cli("up", "--host", "127.0.0.1", "--port", str(port), env=env)
        assert up.returncode == 0, _format_result(up)
        assert f"Server started at {base_url}" in up.stdout, _format_result(up)
        assert _health_is_up(base_url)

        ps = _run_cli("ps", "--host", "127.0.0.1", "--ports", str(port), env=env)
        assert ps.returncode == 0, _format_result(ps)
        assert f"Port {port}" in ps.stdout, _format_result(ps)

        doctor = _run_cli("doctor", env=env)
        assert doctor.returncode == 0, _format_result(doctor)
        assert "GIMO Doctor Report" in doctor.stdout, _format_result(doctor)
        assert base_url in doctor.stdout, _format_result(doctor)

        down = _run_cli("down", "--host", "127.0.0.1", "--port", str(port), env=env)
        assert down.returncode == 0, _format_result(down)
        assert (
            "health now refuses connections" in down.stdout
            or "health is no longer reachable" in down.stdout
        ), _format_result(down)
        assert _wait_for_health_down(base_url), _format_result(down)
    finally:
        if _health_is_up(base_url):
            _run_cli("down", "--host", "127.0.0.1", "--port", str(port), env=env)
