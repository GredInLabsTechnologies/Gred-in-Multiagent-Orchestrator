import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tools.gimo_server.config import ORCH_ACTIONS_TOKEN, ORCH_OPERATOR_TOKEN, TOKENS

logger = logging.getLogger("orchestrator.auth")

security = HTTPBearer(auto_error=False)

INVALID_TOKEN_ERROR = "Invalid token"
SESSION_COOKIE_NAME = "gimo_session"
SESSION_TTL_SECONDS = 86400  # 24 hours
FIREBASE_SESSION_TTL = 86400 * 30  # 30 days


# ---------------------------------------------------------------------------
# Session dataclass (used in-memory after decode)
# ---------------------------------------------------------------------------
@dataclass
class _Session:
    session_id: str
    role: str
    uid: str = ""
    email: str = ""
    display_name: str = ""
    plan: str = ""
    firebase_user: bool = False
    profile_cache: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Stateless SessionStore — cookie is a signed JWT-like token.
#
# Format: base64url(payload_json) + "." + hmac_hex
# The payload contains all session fields + created_at.
# No server-side state → survives backend restarts unchanged.
# Revocation is handled via a small in-memory revocation set (only logout
# needs it; restarts clear revocations, which is acceptable for dev).
# ---------------------------------------------------------------------------
class SessionStore:
    def __init__(self):
        self._signing_key = hashlib.sha256(
            "|".join(sorted(TOKENS)).encode()
        ).digest()
        self._revoked: set[str] = set()  # revoked session_ids (cleared on restart)
        self._lock = Lock()

    def _sign(self, payload_b64: str) -> str:
        return hmac.new(self._signing_key, payload_b64.encode(), hashlib.sha256).hexdigest()

    def create(self, role: str, **kwargs: Any) -> str:
        session_id = secrets.token_urlsafe(16)
        payload = {
            "sid": session_id,
            "role": role,
            "uid": str(kwargs.get("uid", "")),
            "email": str(kwargs.get("email", "")),
            "dn": str(kwargs.get("display_name", "")),
            "plan": str(kwargs.get("plan", "")),
            "fb": bool(kwargs.get("firebase_user", False)),
            "iat": time.time(),
            "profile": dict(kwargs.get("profile_cache") or {}),
        }
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        sig = self._sign(payload_b64)
        return f"{payload_b64}.{sig}"

    def _decode(self, cookie_value: str) -> Optional[tuple[dict, str]]:
        """Decode and verify cookie. Returns (payload_dict, session_id) or None."""
        parts = cookie_value.split(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected = self._sign(payload_b64)
        if not hmac.compare_digest(sig, expected):
            return None
        try:
            padding = 4 - len(payload_b64) % 4
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * padding))
        except Exception:
            return None
        return payload, payload.get("sid", "")

    def validate(self, cookie_value: str) -> Optional[_Session]:
        result = self._decode(cookie_value)
        if not result:
            return None
        payload, session_id = result
        with self._lock:
            if session_id in self._revoked:
                return None
        firebase_user = bool(payload.get("fb"))
        ttl = FIREBASE_SESSION_TTL if firebase_user else SESSION_TTL_SECONDS
        created_at = float(payload.get("iat", 0))
        if time.time() - created_at > ttl:
            return None
        return _Session(
            session_id=session_id,
            role=str(payload.get("role", "admin")),
            uid=str(payload.get("uid", "")),
            email=str(payload.get("email", "")),
            display_name=str(payload.get("dn", "")),
            plan=str(payload.get("plan", "")),
            firebase_user=firebase_user,
            profile_cache=dict(payload.get("profile") or {}),
            created_at=created_at,
            last_seen=time.time(),
        )

    def get_session_info(self, cookie_value: str) -> Optional[Dict[str, Any]]:
        session = self.validate(cookie_value)
        if not session:
            return None
        ttl = FIREBASE_SESSION_TTL if session.firebase_user else SESSION_TTL_SECONDS
        now = time.time()
        return {
            "role": session.role,
            "uid": session.uid,
            "email": session.email,
            "displayName": session.display_name,
            "plan": session.plan,
            "firebaseUser": session.firebase_user,
            "createdAt": session.created_at,
            "lastSeen": session.last_seen,
            "ttlSeconds": ttl,
            "expiresInSeconds": max(0, int((session.created_at + ttl) - now)),
            "profile": dict(session.profile_cache),
        }

    def revoke(self, cookie_value: str) -> None:
        result = self._decode(cookie_value)
        if result:
            _, session_id = result
            with self._lock:
                self._revoked.add(session_id)

    def cleanup_expired(self) -> int:
        # Stateless — nothing to clean up server-side
        return 0


session_store = SessionStore()


# ---------------------------------------------------------------------------
# Auth context
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthContext:
    token: str
    role: str


def _resolve_role(token: str) -> str:
    if token == ORCH_ACTIONS_TOKEN:
        return "actions"
    elif token == ORCH_OPERATOR_TOKEN:
        return "operator"
    return "admin"


# ---------------------------------------------------------------------------
# Unified verify: Bearer header OR session cookie
# ---------------------------------------------------------------------------
def _verify_cli_bond_jwt(token: str, request: Request) -> AuthContext | None:
    """Verify a CLI Bond JWT (Ed25519-signed, scope:cli).

    Returns AuthContext if valid, None otherwise.
    """
    # Quick check: JWTs have 3 dot-separated parts
    if token.count(".") != 2:
        return None

    try:
        from tools.gimo_server.security.license_guard import (
            _verify_jwt_ed25519,
            _get_public_key_pem,
        )

        public_key_pem = _get_public_key_pem()
        payload = _verify_jwt_ed25519(token, public_key_pem)
        if not payload:
            return None

        # Must be a CLI-scoped bond
        if payload.get("scope") != "cli":
            return None

        # Verify machine_id matches request header (if provided)
        bond_machine_id = payload.get("machine_id", "")
        request_machine_id = request.headers.get("X-Machine-Id", "")
        if request_machine_id and bond_machine_id:
            if request_machine_id != bond_machine_id:
                logger.warning(
                    "CLI Bond JWT machine_id mismatch: jwt=%s... req=%s...",
                    bond_machine_id[:8],
                    request_machine_id[:8],
                )
                return None

        # Map JWT plan to role
        jwt_plan = payload.get("plan", "standard")
        role = "operator"  # CLI bonds are always operator-level
        if jwt_plan in ("admin", "enterprise"):
            role = "admin"

        return AuthContext(token="cli_bond", role=role)

    except Exception as e:
        logger.debug("CLI Bond JWT verification failed: %s", e)
        return None


def verify_token(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Security(security)
) -> AuthContext:
    # 1. Try Bearer header first (API/CLI callers)
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()

        # 1a. Static token match
        if token and len(token) >= 16 and token in TOKENS:
            ctx = AuthContext(token=token, role=_resolve_role(token))
            request.state.auth_role = ctx.role
            return ctx

        # 1b. CLI Bond JWT (Ed25519-signed)
        if token:
            bond_ctx = _verify_cli_bond_jwt(token, request)
            if bond_ctx:
                request.state.auth_role = bond_ctx.role
                return bond_ctx

        if token:
            _report_auth_failure(request, token)
            raise HTTPException(status_code=401, detail=INVALID_TOKEN_ERROR)

    # 2. Try session cookie (browser/UI callers)
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_value:
        session = session_store.validate(cookie_value)
        if session:
            request.state.auth_role = session.role
            return AuthContext(token="session", role=session.role)
        # Invalid/expired cookie — don't escalate threat, just reject
        raise HTTPException(status_code=401, detail="Session expired")

    raise HTTPException(status_code=401, detail="Token missing")


def _report_auth_failure(request: Request, token: str) -> None:
    from tools.gimo_server.security import threat_engine

    token_hash = hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()
    client_ip = request.client.host if request.client else "unknown"

    threat_engine.record_auth_failure(
        source=client_ip,
        detail=f"Invalid token hash: {token_hash[:16]}..."
    )
