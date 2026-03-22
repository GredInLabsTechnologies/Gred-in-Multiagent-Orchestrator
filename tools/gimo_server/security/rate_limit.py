from datetime import datetime

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


def _cleanup_rate_limits(now: datetime):
    global _last_cleanup
    if (now - _last_cleanup).total_seconds() < RATE_LIMIT_CLEANUP_SECONDS:
        return
    to_delete = [
        key
        for key, data in rate_limit_store.items()
        if (now - data["start_time"]).total_seconds() > RATE_LIMIT_WINDOW_SECONDS
    ]
    for key in to_delete:
        del rate_limit_store[key]
    _last_cleanup = now


def check_rate_limit(request: Request):
    now = datetime.now()
    _cleanup_rate_limits(now)

    client_ip = request.client.host if request.client else "unknown"

    # Determine role from auth state (set by verify_token dependency)
    role = getattr(request.state, "auth_role", None) or "unknown"
    limit = ROLE_RATE_LIMITS.get(role, RATE_LIMIT_PER_MIN)

    # Key by IP + role to enforce per-role limits
    key = f"{client_ip}:{role}"

    if key not in rate_limit_store:
        rate_limit_store[key] = {"count": 1, "start_time": now}
    else:
        data = rate_limit_store[key]
        if (now - data["start_time"]).total_seconds() > RATE_LIMIT_WINDOW_SECONDS:
            data["count"] = 1
            data["start_time"] = now
        else:
            data["count"] += 1
            if data["count"] > limit:
                raise HTTPException(status_code=429, detail="Too many requests")
    return None
