import logging
import time

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tools.repo_orchestrator.config import TOKENS

logger = logging.getLogger("orchestrator.auth")

security = HTTPBearer(auto_error=False)

INVALID_TOKEN_ERROR = "Invalid token"


def verify_token(
    _request: Request, credentials: HTTPAuthorizationCredentials | None = Security(security)
):
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
    return token


def _trigger_panic_for_invalid_token(token: str) -> None:
    import hashlib
    import json

    from tools.repo_orchestrator.security import (
        SECURITY_DB_PATH,
        load_security_db,
        save_security_db,
    )

    token_hash = hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()

    try:
        db = json.loads(SECURITY_DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        db = load_security_db()
    db["panic_mode"] = True
    if "recent_events" not in db:
        db["recent_events"] = []
    db["recent_events"].append(
        {
            "type": "PANIC_TRIGGER",
            "timestamp": time.time(),
            "reason": "Invalid authentication attempt",
            "payload_hash": token_hash,  # Observability: Hash of the malicious payload
        }
    )
    save_security_db(db)
