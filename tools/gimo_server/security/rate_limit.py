from datetime import datetime

from fastapi import HTTPException, Request

from tools.gimo_server.config import (
    RATE_LIMIT_CLEANUP_SECONDS,
    RATE_LIMIT_PER_MIN,
    RATE_LIMIT_WINDOW_SECONDS,
)

rate_limit_store = {}
_last_cleanup = datetime.now()


def _cleanup_rate_limits(now: datetime):
    global _last_cleanup
    if (now - _last_cleanup).total_seconds() < RATE_LIMIT_CLEANUP_SECONDS:
        return
    to_delete = [
        ip
        for ip, data in rate_limit_store.items()
        if (now - data["start_time"]).total_seconds() > RATE_LIMIT_WINDOW_SECONDS
    ]
    for ip in to_delete:
        del rate_limit_store[ip]
    _last_cleanup = now


def check_rate_limit(request: Request):
    now = datetime.now()
    _cleanup_rate_limits(now)

    client_ip = request.client.host if request.client else "unknown"
    if client_ip not in rate_limit_store:
        rate_limit_store[client_ip] = {"count": 1, "start_time": now}
    else:
        data = rate_limit_store[client_ip]
        if (now - data["start_time"]).total_seconds() > RATE_LIMIT_WINDOW_SECONDS:
            data["count"] = 1
            data["start_time"] = now
        else:
            data["count"] += 1
            if data["count"] > RATE_LIMIT_PER_MIN:
                raise HTTPException(status_code=429, detail="Too many requests")
    return None
