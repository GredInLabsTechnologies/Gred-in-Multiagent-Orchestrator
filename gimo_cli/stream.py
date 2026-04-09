"""SSE streaming, output helpers, and run polling."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from gimo_cli import console
from gimo_cli.api import api_request, api_settings, resolve_token
from gimo_cli.config import (
    ACTIVE_RUN_STATUSES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_WATCH_TIMEOUT_SECONDS,
    TERMINAL_RUN_STATUSES,
    is_terminal_status,
    project_root,
)


SSE_IDLE_TIMEOUT_SECONDS = 120


def stream_events(
    config: dict[str, Any],
    *,
    path: str = "/ops/stream",
    timeout_seconds: float = DEFAULT_WATCH_TIMEOUT_SECONDS,
    last_event_id: str = "",
):
    base_url, connect_timeout_seconds = api_settings(config)
    token = resolve_token("operator", config)
    headers = {"Accept": "text/event-stream", "X-GIMO-Surface": "cli"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    url = f"{base_url}{path}"
    read_timeout = timeout_seconds if timeout_seconds > 0 else None
    timeout = httpx.Timeout(
        connect=connect_timeout_seconds,
        read=read_timeout,
        write=connect_timeout_seconds,
        pool=connect_timeout_seconds,
    )

    _last_id = ""
    last_payload_at = time.monotonic()
    idle_seconds = timeout_seconds if timeout_seconds > 0 else SSE_IDLE_TIMEOUT_SECONDS
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if timeout_seconds > 0 and (time.monotonic() - last_payload_at) >= timeout_seconds:
                        console.print(f"[yellow]No events received for {idle_seconds}s - stream idle.[/yellow]")
                        return
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("id:"):
                        _last_id = line[3:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    last_payload_at = time.monotonic()
                    try:
                        parsed = json.loads(raw)
                        if _last_id and isinstance(parsed, dict):
                            parsed["_last_event_id"] = _last_id
                        yield parsed
                    except json.JSONDecodeError:
                        yield raw
    except httpx.ReadTimeout:
        console.print(f"[yellow]No events received for {idle_seconds}s - stream idle.[/yellow]")


def emit_output(payload: Any, *, json_output: bool) -> None:
    if json_output:
        console.print_json(data=payload)
        return
    console.print(payload)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def terminal_status(status: str) -> bool:
    return is_terminal_status(status, ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES)


def poll_run(
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
        status_code, payload = api_request(config, "GET", f"/ops/runs/{run_id}")
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

        if terminal_status(status):
            return latest_payload

        if deadline is not None and time.time() >= deadline:
            latest_payload["poll_timeout"] = True
            return latest_payload

        time.sleep(max(poll_interval_seconds, 0.1))


def git_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_root(),
        text=True,
        capture_output=True,
        check=False,
    )
