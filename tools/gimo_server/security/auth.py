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
    request: Request, credentials: HTTPAuthorizationCredentials | None = Security(security)
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
        _report_auth_failure(request, token)
        raise HTTPException(status_code=401, detail=INVALID_TOKEN_ERROR)
    if token == ORCH_ACTIONS_TOKEN:
        role = "actions"
    elif token == ORCH_OPERATOR_TOKEN:
        role = "operator"
    else:
        role = "admin"
    return AuthContext(token=token, role=role)


def _report_auth_failure(request: Request, token: str) -> None:
    import hashlib

    from tools.gimo_server.security import threat_engine

    token_hash = hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()
    client_ip = request.client.host if request.client else "unknown"

    threat_engine.record_auth_failure(
        source=client_ip,
        detail=f"Invalid token hash: {token_hash[:16]}..."
    )
    # Note: escalation is handled inside threat_engine. No need to loop/save here,
    # it's shared in-memory and persisted periodically or at shutdown.


