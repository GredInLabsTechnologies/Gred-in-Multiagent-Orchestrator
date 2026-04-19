from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request

from tools.gimo_server.config import (
    RATE_LIMIT_CLEANUP_SECONDS,
    RATE_LIMIT_PER_MIN,
    RATE_LIMIT_WINDOW_SECONDS,
)

# Per-role limits (requests per minute)
ROLE_RATE_LIMITS: dict[str, int] = {
    "actions": 60,
    "operator": 200,
    "admin": 1000,
}

rate_limit_store: dict[str, dict] = {}
_last_cleanup = datetime.now()


def _normalize_rate_limit_start(start_time: Any) -> datetime | None:
    """Normalize legacy/heterogeneous start_time values to local naive datetime."""
    if isinstance(start_time, datetime):
        return start_time.astimezone().replace(tzinfo=None) if start_time.tzinfo else start_time
    if isinstance(start_time, (int, float)):
        return datetime.fromtimestamp(float(start_time))
    return None


def window_elapsed_seconds(data: dict[str, Any], now: datetime | None = None) -> float | None:
    current = now or datetime.now()
    start_time = _normalize_rate_limit_start(data.get("start_time"))
    if start_time is None:
        return None
    return (current - start_time).total_seconds()


def _cleanup_rate_limits(now: datetime):
    global _last_cleanup
    if (now - _last_cleanup).total_seconds() < RATE_LIMIT_CLEANUP_SECONDS:
        return
    to_delete = [
        key
        for key, data in rate_limit_store.items()
        if (elapsed := window_elapsed_seconds(data, now)) is None or elapsed > RATE_LIMIT_WINDOW_SECONDS
    ]
    for key in to_delete:
        del rate_limit_store[key]
    _last_cleanup = now


def consume_rate_limit(
    key: str,
    *,
    limit: int,
    error_detail: str = "Too many requests",
    now: datetime | None = None,
) -> None:
    """Consume a rate-limit bucket using the canonical in-memory window contract."""
    current = now or datetime.now()
    data = rate_limit_store.get(key)
    if data is None:
        rate_limit_store[key] = {"count": 1, "start_time": current}
        return

    elapsed = window_elapsed_seconds(data, current)
    if elapsed is None or elapsed > RATE_LIMIT_WINDOW_SECONDS:
        rate_limit_store[key] = {"count": 1, "start_time": current}
        return

    data["count"] = int(data.get("count", 0)) + 1
    if data["count"] > limit:
        raise HTTPException(status_code=429, detail=error_detail)


def check_rate_limit(request: Request):
    now = datetime.now()
    _cleanup_rate_limits(now)

    client_ip = request.client.host if request.client else "unknown"

    # Determine role from auth state (set by verify_token dependency)
    role = getattr(request.state, "auth_role", None) or "unknown"
    limit = ROLE_RATE_LIMITS.get(role, RATE_LIMIT_PER_MIN)

    # Key by IP + role to enforce per-role limits
    key = f"{client_ip}:{role}"
    consume_rate_limit(key, limit=limit, now=now)
    return None
