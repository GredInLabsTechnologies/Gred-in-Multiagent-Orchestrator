import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tools.gimo_server.config import ORCH_ACTIONS_TOKEN, ORCH_OPERATOR_TOKEN, TOKENS

logger = logging.getLogger("orchestrator.auth")

security = HTTPBearer(auto_error=False)

INVALID_TOKEN_ERROR = "Invalid token"


@dataclass(frozen=True)
class AuthContext:
    token: str
    role: str


def verify_token(
    _request: Request, credentials: HTTPAuthorizationCredentials | None = Security(security)
) -> AuthContext:
    if not credentials:
        raise HTTPException(status_code=401, detail="Token missing")

    # Strip whitespace and validate token is not empty
    token = credentials.credentials.strip() if credentials.credentials else ""
    if not token:
        raise HTTPException(status_code=401, detail=INVALID_TOKEN_ERROR)

    # Validate token length (minimum 16 characters for security)
    if len(token) < 16:
        raise HTTPException(status_code=401, detail=INVALID_TOKEN_ERROR)

    # Verify token against valid tokens (sensitive data not logged for security)
    logger.debug(f"Verifying authentication token (length: {len(token)})")
    if token not in TOKENS:
        _trigger_panic_for_invalid_token(token)
        raise HTTPException(status_code=401, detail=INVALID_TOKEN_ERROR)
    if token == ORCH_ACTIONS_TOKEN:
        role = "actions"
    elif token == ORCH_OPERATOR_TOKEN:
        role = "operator"
    else:
        role = "admin"
    return AuthContext(token=token, role=role)


PANIC_THRESHOLD = 5  # Attempts before lockdown
PANIC_WINDOW_SECONDS = 60  # Time window for threshold
EVENT_RETENTION_SECONDS = 86400  # 24 hours - events older than this are cleaned up


def _trigger_panic_for_invalid_token(token: str) -> None:
    import hashlib
    import threading

    from tools.gimo_server.security import load_security_db, save_security_db

    token_hash = hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()
    now = time.time()

    lock = getattr(_trigger_panic_for_invalid_token, "_lock", None)
    if lock is None:
        lock = threading.Lock()
        _trigger_panic_for_invalid_token._lock = lock

    with lock:
        db = load_security_db()

        if "recent_events" not in db:
            db["recent_events"] = []

        # Clean up old events (older than retention period)
        db["recent_events"] = [
            e
            for e in db["recent_events"]
            if isinstance(e.get("timestamp"), (int, float))
            and (now - e["timestamp"]) < EVENT_RETENTION_SECONDS
        ]

        # Count recent failed attempts within the time window
        recent_failures = [
            e
            for e in db["recent_events"]
            if e.get("type") == "PANIC_TRIGGER"
            and isinstance(e.get("timestamp"), (int, float))
            and (now - e["timestamp"]) < PANIC_WINDOW_SECONDS
            and not e.get("resolved", False)
        ]

        # Add the new event
        db["recent_events"].append(
            {
                "type": "PANIC_TRIGGER",
                "timestamp": now,
                "reason": "Invalid authentication attempt",
                "payload_hash": token_hash,
            }
        )

        # Only activate panic mode if threshold exceeded
        if len(recent_failures) + 1 >= PANIC_THRESHOLD:
            db["panic_mode"] = True
            logger.warning(
                f"PANIC MODE ACTIVATED: {len(recent_failures) + 1} failed attempts in {PANIC_WINDOW_SECONDS}s"
            )
        else:
            logger.info(
                f"Auth failure {len(recent_failures) + 1}/{PANIC_THRESHOLD} (window: {PANIC_WINDOW_SECONDS}s)"
            )

        save_security_db(db)
