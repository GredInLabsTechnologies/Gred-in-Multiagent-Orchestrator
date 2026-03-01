import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response  # noqa: F811
from pydantic import BaseModel

from ..config import GIMO_INTERNAL_KEY, GIMO_WEB_URL, TOKENS, get_settings
from ..security.auth import (
    FIREBASE_SESSION_TTL,
    SESSION_COOKIE_NAME,
    _resolve_role,
    session_store,
)
from ..security.cold_room import ColdRoomManager

logger = logging.getLogger("orchestrator.auth_router")

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    token: str


class LoginResponse(BaseModel):
    role: str
    message: str


class FirebaseLoginRequest(BaseModel):
    idToken: str


class ColdRoomActivateRequest(BaseModel):
    license_blob: str


class ColdRoomRenewRequest(BaseModel):
    license_blob: str


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    if forwarded_proto == "https":
        return True
    return request.url.scheme == "https"


def _map_firebase_role_to_session_role(firebase_role: str) -> str:
    """
    Maps GIMO WEB role model (user/admin) to orchestrator RBAC role model
    (actions/operator/admin).
    """
    if firebase_role == "admin":
        return "admin"
    return "operator"


def _get_cold_room_manager() -> ColdRoomManager:
    settings = get_settings()
    return ColdRoomManager(settings)


def _cold_room_enabled() -> bool:
    return bool(getattr(get_settings(), "cold_room_enabled", False))


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response, request: Request):
    """Validate a token and set a session cookie. The token is never stored in the browser."""
    token = body.token.strip()
    if not token or len(token) < 16 or token not in TOKENS:
        from ..security.auth import _report_auth_failure
        if token:
            _report_auth_failure(request, token)
        raise HTTPException(status_code=401, detail="Invalid token")

    role = _resolve_role(token)
    cookie_value = session_store.create(role)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        samesite="lax",
        secure=_is_secure_request(request),
        max_age=86400,
        path="/",
    )
    return LoginResponse(role=role, message="Authenticated")


@router.post("/firebase-login")
async def firebase_login(body: FirebaseLoginRequest, response: Response, request: Request):
    """Authenticate using Firebase ID token via GIMO WEB verify endpoint."""
    id_token = body.idToken.strip()
    if not id_token:
        raise HTTPException(status_code=400, detail="idToken required")

    if not GIMO_INTERNAL_KEY:
        raise HTTPException(status_code=500, detail="GIMO_INTERNAL_KEY is not configured")

    verify_url = f"{GIMO_WEB_URL.rstrip('/')}/api/orchestrator/verify"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            verify_response = await client.post(
                verify_url,
                json={"idToken": id_token},
                headers={"X-Internal-Key": GIMO_INTERNAL_KEY},
            )
    except httpx.HTTPError as exc:
        logger.warning("Firebase verify request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Unable to reach auth upstream") from exc

    if verify_response.status_code >= 400:
        upstream_error = ""
        upstream_code = ""
        upstream_detail = ""
        try:
            parsed = verify_response.json()
            if isinstance(parsed, dict):
                upstream_error = str(parsed.get("error") or "")
                upstream_code = str(parsed.get("code") or "")
                upstream_detail = str(parsed.get("detail") or "")
        except Exception:
            upstream_error = (verify_response.text or "").strip()

        logger.warning(
            "Auth upstream rejected (status=%s, error=%s, code=%s, detail=%s)",
            verify_response.status_code,
            upstream_error or "<empty>",
            upstream_code or "<empty>",
            upstream_detail[:200] if upstream_detail else "<empty>",
        )

        status = 401 if verify_response.status_code in (401, 403) else 502
        detail = f"[{upstream_code or 'UPSTREAM_' + str(verify_response.status_code)}] {upstream_error}"
        if upstream_detail:
            detail = f"{detail} — {upstream_detail[:300]}"
        raise HTTPException(status_code=status, detail=detail)

    payload = verify_response.json()
    firebase_role = payload.get("role") if payload.get("role") in ("admin", "user") else "user"
    role = _map_firebase_role_to_session_role(firebase_role)
    email = str(payload.get("email") or "")
    display_name = str(payload.get("displayName") or "")

    license_data = payload.get("license") or {}
    plan = str(license_data.get("plan") or "none")

    cookie_value = session_store.create(
        role=role,
        uid=str(payload.get("uid") or ""),
        email=email,
        display_name=display_name,
        plan=plan,
        firebase_user=True,
        profile_cache={
            "license": license_data,
            "subscription": payload.get("subscription") or {},
        },
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        samesite="lax",
        secure=_is_secure_request(request),
        max_age=FIREBASE_SESSION_TTL,
        path="/",
    )

    return {
        "role": role,
        "firebaseRole": firebase_role,
        "email": email,
        "displayName": display_name,
        "plan": plan,
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Revoke the session and clear the cookie."""
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_value:
        session_store.revoke(cookie_value)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"message": "Logged out"}


@router.get("/cold-room/status")
async def cold_room_status() -> dict[str, Any]:
    """Pre-auth endpoint: return cold-room capability and status."""
    if not _cold_room_enabled():
        return {
            "enabled": False,
            "paired": False,
        }

    manager = _get_cold_room_manager()
    status = manager.get_status()
    status["enabled"] = True
    return status


@router.post("/cold-room/activate")
async def cold_room_activate(body: ColdRoomActivateRequest) -> dict[str, Any]:
    """Pre-auth endpoint: activate machine with a signed cold-room license blob."""
    if not _cold_room_enabled():
        raise HTTPException(status_code=404, detail="Cold Room disabled")

    license_blob = body.license_blob.strip()
    if not license_blob:
        raise HTTPException(status_code=400, detail="license_blob is required")

    manager = _get_cold_room_manager()
    ok, reason = manager.activate(license_blob)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    status = manager.get_status()
    status["enabled"] = True
    return {
        "paired": True,
        "machine_id": status.get("machine_id"),
        "vm_detected": status.get("vm_detected", False),
        "expires_at": status.get("expires_at"),
        "renewal_valid": status.get("renewal_valid"),
        "renewal_needed": status.get("renewal_needed"),
        "days_remaining": status.get("days_remaining"),
    }


@router.get("/cold-room/info")
async def cold_room_info() -> dict[str, Any]:
    """Pre-auth endpoint: return machine and current cold-room license info."""
    if not _cold_room_enabled():
        raise HTTPException(status_code=404, detail="Cold Room disabled")

    manager = _get_cold_room_manager()
    return manager.get_info()


@router.post("/cold-room/renew")
async def cold_room_renew(body: ColdRoomRenewRequest) -> dict[str, Any]:
    """Pre-auth endpoint: renew machine with a newly signed cold-room license blob."""
    if not _cold_room_enabled():
        raise HTTPException(status_code=404, detail="Cold Room disabled")

    manager = _get_cold_room_manager()
    license_blob = body.license_blob.strip()
    if not license_blob:
        raise HTTPException(status_code=400, detail="license_blob is required")

    renewed, reason = manager.renew(license_blob)
    if not renewed:
        raise HTTPException(status_code=400, detail=reason)

    status = manager.get_status()
    return {
        "renewed": renewed,
        "vm_detected": status.get("vm_detected", False),
        "renewal_valid": status.get("renewal_valid", False),
        "renewal_needed": status.get("renewal_needed", False),
        "expires_at": status.get("expires_at"),
        "days_remaining": status.get("days_remaining", 0),
        "machine_id": status.get("machine_id"),
    }


@router.post("/cold-room/access", response_model=LoginResponse)
async def cold_room_access(response: Response, request: Request) -> LoginResponse:
    """Pre-auth endpoint: authenticate when Cold Room license is already valid."""
    if not _cold_room_enabled():
        raise HTTPException(status_code=404, detail="Cold Room disabled")

    manager = _get_cold_room_manager()
    status = manager.get_status()
    if not status.get("paired"):
        raise HTTPException(status_code=401, detail="cold_room_not_paired")
    if not status.get("renewal_valid"):
        raise HTTPException(status_code=401, detail="cold_room_renewal_required")

    role = "operator"
    cookie_value = session_store.create(
        role=role,
        plan=str(status.get("plan") or "cold_room"),
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        samesite="lax",
        secure=_is_secure_request(request),
        max_age=86400,
        path="/",
    )
    return LoginResponse(role=role, message="Authenticated via Cold Room")


@router.get("/check")
async def check_session(request: Request):
    """Check if the current session cookie is valid. No auth required."""
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        return {"authenticated": False}
    session = session_store.validate(cookie_value)
    if not session:
        return {"authenticated": False}

    data = {
        "authenticated": True,
        "role": session.role,
    }

    if session.firebase_user:
        data.update(
            {
                "email": session.email,
                "displayName": session.display_name,
                "plan": session.plan,
                "firebaseUser": True,
                "sessionRole": session.role,
            }
        )

    return data


@router.get("/profile")
async def profile(request: Request):
    """Return full profile for authenticated session, refreshing from GIMO WEB for Firebase users."""
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        raise HTTPException(status_code=401, detail="Session missing")

    session = session_store.validate(cookie_value)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")

    if not session.firebase_user:
        session_info = session_store.get_session_info(cookie_value)
        if not session_info:
            raise HTTPException(status_code=401, detail="Session expired")
        return {
            "user": {
                "role": session.role,
                "email": session.email,
                "displayName": session.display_name,
            },
            "license": {
                "plan": session.plan or "none",
                "status": "none",
                "isLifetime": False,
                "keyPreview": "",
                "installationsUsed": 0,
                "installationsMax": 0,
                "expiresAt": None,
            },
            "subscription": {
                "status": "none",
                "currentPeriodEnd": None,
                "cancelAtPeriodEnd": False,
            },
            "session": session_info,
        }

    upstream_payload = None
    if GIMO_INTERNAL_KEY and GIMO_WEB_URL:
        verify_url = f"{GIMO_WEB_URL.rstrip('/')}/api/orchestrator/verify"
        try:
            auth_header = request.headers.get("Authorization", "")
            id_token = ""
            if auth_header.lower().startswith("bearer "):
                id_token = auth_header[7:].strip()

            if id_token:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    upstream = await client.post(
                        verify_url,
                        json={"idToken": id_token},
                        headers={"X-Internal-Key": GIMO_INTERNAL_KEY},
                    )
                if upstream.status_code < 400:
                    upstream_payload = upstream.json()
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Profile refresh from upstream failed, using cache: %s", exc)

    if upstream_payload:
        session.email = str(upstream_payload.get("email") or session.email)
        session.display_name = str(upstream_payload.get("displayName") or session.display_name)
        session.plan = str((upstream_payload.get("license") or {}).get("plan") or session.plan)
        session.profile_cache = {
            "license": upstream_payload.get("license") or {},
            "subscription": upstream_payload.get("subscription") or {},
        }

    license_data = session.profile_cache.get("license") or {
        "plan": session.plan or "none",
        "status": "none",
        "isLifetime": False,
        "keyPreview": "",
        "installationsUsed": 0,
        "installationsMax": 0,
        "expiresAt": None,
    }
    subscription_data = session.profile_cache.get("subscription") or {
        "status": "none",
        "currentPeriodEnd": None,
        "cancelAtPeriodEnd": False,
    }

    session_info = session_store.get_session_info(cookie_value)
    if not session_info:
        raise HTTPException(status_code=401, detail="Session expired")

    return {
        "user": {
            "uid": session.uid,
            "role": session.role,
            "email": session.email,
            "displayName": session.display_name,
        },
        "license": license_data,
        "subscription": subscription_data,
        "profileSource": "upstream" if upstream_payload else "session_cache",
        "session": session_info,
    }
