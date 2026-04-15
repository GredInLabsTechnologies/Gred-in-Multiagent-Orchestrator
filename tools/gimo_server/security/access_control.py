"""Role-based path access control for routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.security import verify_token

READ_ONLY_ACTIONS_PATHS = {
    "/file",
    "/tree",
    "/search",
    "/diff",
    "/status",
    "/health",
    "/health/deep",
    "/ui/repos",
    "/ui/repos/active",
    "/ui/repos/select",
    "/ops/plan",
    "/ops/drafts",
    "/ops/approved",
    "/ops/runs",
    "/ops/config",
}

OPERATOR_EXTRA_PREFIXES = (
    "/ops/",
)

OPERATOR_EMERGENCY_PATHS = {
    "/ui/security/events",
    "/ui/security/resolve",
    "/ui/repos/revoke",
    "/ui/audit",
}


def _is_actions_allowed_path(path: str) -> bool:
    if path in READ_ONLY_ACTIONS_PATHS:
        return True
    if path.startswith("/ops/drafts/"):
        return True
    if path.startswith("/ops/approved/"):
        return True
    if path.startswith("/ops/runs/"):
        return True
    return False


def _is_operator_allowed_path(path: str) -> bool:
    if _is_actions_allowed_path(path):
        return True
    if path in OPERATOR_EMERGENCY_PATHS:
        return True
    for prefix in OPERATOR_EXTRA_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def require_read_only_access(
    request: Request, auth: Annotated[AuthContext, Depends(verify_token)]
) -> AuthContext:
    path = request.url.path
    if auth.role == "actions":
        if not _is_actions_allowed_path(path):
            raise HTTPException(
                status_code=403, detail="Read-only token cannot access this endpoint"
            )
    elif auth.role == "operator" and not _is_operator_allowed_path(path):
        raise HTTPException(
            status_code=403, detail="Operator token cannot access this endpoint"
        )
    return auth
