from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ...config import OPS_DATA_DIR
from .service import ProviderService

UNKNOWN_PROVIDER_ERROR = "Unknown provider"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProviderAccountService:
    """Minimal account-mode flow persistence and lifecycle operations (Phase 6.5).

    Notes:
    - We keep tokens out of provider.json by storing only env references in auth_ref.
    - Flow state is persisted in OPS state for restart survivability.
    """

    # Fixed filename under OPS_DATA_DIR (server config) — no user-controlled
    # segment. Sonar S2083/S6549 reports here are false positives.
    FLOWS_PATH: Path = OPS_DATA_DIR / "state" / "provider_account_flows.json"

    @classmethod
    def _ensure_parent(cls) -> None:
        cls.FLOWS_PATH.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _load_flows(cls) -> Dict[str, Any]:
        cls._ensure_parent()
        if not cls.FLOWS_PATH.exists():
            return {"flows": {}}
        try:
            return json.loads(cls.FLOWS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"flows": {}}

    @classmethod
    def _save_flows(cls, payload: Dict[str, Any]) -> None:
        cls._ensure_parent()
        cls.FLOWS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def start_flow(
        cls,
        *,
        provider_id: Optional[str],
        verification_url: str,
        user_code: str,
        poll_id: Optional[str],
    ) -> Dict[str, Any]:
        cfg = ProviderService.get_config()
        if not cfg:
            raise ValueError("Provider config missing")
        pid = provider_id or cfg.active
        if pid not in cfg.providers:
            raise ValueError(UNKNOWN_PROVIDER_ERROR)

        flow_id = hashlib.sha256(f"{pid}|{_utc_iso()}|{secrets.token_hex(8)}".encode("utf-8")).hexdigest()[:20]
        payload = cls._load_flows()
        flow = {
            "flow_id": flow_id,
            "provider_id": pid,
            "status": "pending",
            "verification_url": verification_url,
            "user_code": user_code,
            "poll_id": poll_id,
            "created_at": _utc_iso(),
            "updated_at": _utc_iso(),
            "auth_ref": None,
        }
        payload.setdefault("flows", {})[flow_id] = flow
        cls._save_flows(payload)
        return flow

    @classmethod
    def get_flow(cls, flow_id: str) -> Dict[str, Any]:
        payload = cls._load_flows()
        flow = (payload.get("flows") or {}).get(flow_id)
        if not flow:
            raise ValueError("flow not found")
        return flow

    @classmethod
    def refresh_account_ref(cls, *, provider_id: str, account_token: Optional[str]) -> Dict[str, Any]:
        cfg = ProviderService.get_config()
        if not cfg or provider_id not in cfg.providers:
            raise ValueError(UNKNOWN_PROVIDER_ERROR)

        entry = cfg.providers[provider_id]
        auth_ref = entry.auth_ref
        if account_token:
            env_name = f"ORCH_PROVIDER_{provider_id.upper()}_ACCOUNT_TOKEN"
            os.environ[env_name] = account_token
            auth_ref = f"env:{env_name}"

        ProviderService.upsert_provider_entry(
            provider_id=provider_id,
            provider_type=entry.provider_type or entry.type,
            display_name=entry.display_name,
            base_url=entry.base_url,
            auth_mode="account",
            auth_ref=auth_ref,
            model=entry.model_id or entry.model,
            activate=False,
        )

        payload = cls._load_flows()
        for _fid, flow in (payload.get("flows") or {}).items():
            if flow.get("provider_id") == provider_id and flow.get("status") == "pending":
                flow["status"] = "approved"
                flow["auth_ref"] = auth_ref
                flow["updated_at"] = _utc_iso()
        cls._save_flows(payload)

        return {
            "provider_id": provider_id,
            "status": "PROVIDER_AUTH_APPROVED",
            "auth_mode": "account",
            "auth_ref": auth_ref,
        }

    @classmethod
    def logout(cls, *, provider_id: str) -> Dict[str, Any]:
        cfg = ProviderService.get_config()
        if not cfg or provider_id not in cfg.providers:
            raise ValueError(UNKNOWN_PROVIDER_ERROR)

        entry = cfg.providers[provider_id]
        updated_entry = entry.model_copy(update={"auth_mode": "none", "auth_ref": None})
        cfg.providers[provider_id] = updated_entry
        ProviderService.set_config(cfg)

        payload = cls._load_flows()
        for _fid, flow in (payload.get("flows") or {}).items():
            if flow.get("provider_id") == provider_id and flow.get("status") in {"pending", "approved"}:
                flow["status"] = "revoked"
                flow["updated_at"] = _utc_iso()
        cls._save_flows(payload)

        return {
            "provider_id": provider_id,
            "status": "PROVIDER_AUTH_REVOKED",
            "auth_mode": "none",
            "auth_ref": None,
        }
