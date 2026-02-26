"""Cold Room Fortress v2: licencia offline firmada con Ed25519."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from tools.gimo_server.security.fingerprint import generate_fingerprint
from tools.gimo_server.security.license_guard import _aes_decrypt, _aes_encrypt, _derive_cache_key

logger = logging.getLogger("orchestrator.cold_room")

# Fallback: clave pública de validación (debe corresponder al emisor de blobs cold-room).
_EMBEDDED_COLD_ROOM_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEApdItyqfVuHkGDXTvzwJrfSSnL3JoXQyWtx8y1hDSA9Y=
-----END PUBLIC KEY-----"""


class ColdRoomManager:
    def __init__(self, settings):
        self._enabled: bool = bool(getattr(settings, "cold_room_enabled", False))
        # Nuevo campo, fallback por compatibilidad.
        self._secret_path: Path = Path(
            getattr(
                settings,
                "cold_room_license_path",
                getattr(settings, "cold_room_secret_path", ".gimo_cold_room"),
            )
        )
        self._renewal_days: int = int(getattr(settings, "cold_room_renewal_days", 30))
        self._fingerprint: str = generate_fingerprint()
        self._machine_id: str = self._build_machine_id(self._fingerprint)

        raw_key = str(getattr(settings, "cold_room_public_key_pem", "") or "").strip()
        pem = raw_key.replace("\\n", "\n") if raw_key else _EMBEDDED_COLD_ROOM_PUBLIC_KEY
        self._public_key = self._load_public_key(pem)

    @staticmethod
    def _load_public_key(pem: str) -> Optional[Ed25519PublicKey]:
        try:
            loaded = load_pem_public_key(pem.encode("utf-8"))
            if not isinstance(loaded, Ed25519PublicKey):
                return None
            return loaded
        except Exception:
            return None

    @staticmethod
    def _build_machine_id(fingerprint: str) -> str:
        digest = hashlib.sha256(fingerprint.encode("utf-8")).digest()
        b32 = base64.b32encode(digest[:6]).decode("ascii").rstrip("=")
        b32 = b32[:8].upper().ljust(8, "A")
        return f"GIMO-{b32[:4]}-{b32[4:8]}"

    def get_machine_id(self) -> str:
        return self._machine_id

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    def _verify_blob(self, license_blob: str, *, check_expiry: bool = True) -> tuple[bool, str, Optional[dict[str, Any]]]:
        if not self._public_key:
            return False, "missing_public_key", None
        if not license_blob.strip():
            return False, "empty_license_blob", None

        try:
            raw = self._b64url_decode(license_blob.strip())
        except Exception:
            return False, "invalid_blob_encoding", None

        if len(raw) <= 64:
            return False, "invalid_blob_size", None

        payload_bytes, signature = raw[:-64], raw[-64:]
        try:
            self._public_key.verify(signature, payload_bytes)
        except InvalidSignature:
            return False, "invalid_signature", None
        except Exception:
            return False, "signature_verification_error", None

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return False, "invalid_payload", None

        if payload.get("v") != 2:
            return False, "unsupported_license_version", None
        if payload.get("mid") != self._machine_id:
            return False, "machine_mismatch", None

        nonce = payload.get("nonce")
        if nonce is not None and not isinstance(nonce, str):
            return False, "invalid_nonce", None

        if check_expiry:
            now = int(time.time())
            exp = int(payload.get("exp", 0))
            if exp <= 0 or now > exp:
                return False, "cold_room_renewal_required", None

        return True, "ok", payload

    def activate(self, license_blob: str) -> tuple[bool, str]:
        ok, reason, payload = self._verify_blob(license_blob)
        if not ok or payload is None:
            return False, reason

        nonce = payload.get("nonce")
        state = self._load_state() or {}
        used_nonces = state.get("used_nonces", [])
        if not isinstance(used_nonces, list):
            used_nonces = []
        if nonce and nonce in used_nonces:
            return False, "nonce_replay_detected"
        if nonce:
            used_nonces.append(nonce)
            # Keep bounded history to avoid unbounded growth.
            used_nonces = used_nonces[-128:]

        state = {
            "license_blob": license_blob.strip(),
            "payload": payload,
            "used_nonces": used_nonces,
            "paired_at": time.time(),
            "updated_at": time.time(),
        }
        self._save_state(state)
        return True, "ok"

    def renew(self, license_blob: str) -> tuple[bool, str]:
        # Mismo flujo criptográfico que activate; semántica distinta en API.
        return self.activate(license_blob)

    def is_paired(self) -> bool:
        state = self._load_state()
        if not state:
            return False
        blob = str(state.get("license_blob") or "")
        ok, _, _ = self._verify_blob(blob, check_expiry=False)
        return ok

    def is_renewal_valid(self) -> bool:
        state = self._load_state()
        if not state:
            return False
        blob = str(state.get("license_blob") or "")
        ok, _, _ = self._verify_blob(blob, check_expiry=True)
        return ok

    def get_status(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "machine_id": self._machine_id,
            "paired": False,
            "vm_detected": False,
            "renewal_valid": False,
            "renewal_needed": False,
            "days_remaining": 0,
        }

        state = self._load_state()
        if not state:
            return base

        blob = str(state.get("license_blob") or "")
        ok, reason, payload = self._verify_blob(blob)
        if not ok or payload is None:
            base["renewal_needed"] = reason == "cold_room_renewal_required"
            return base

        exp = int(payload.get("exp", 0))
        now = int(time.time())
        days_remaining = max(0, int((exp - now) / 86400))

        base.update(
            {
                "paired": True,
                "renewal_valid": True,
                "renewal_needed": False,
                "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(),
                "days_remaining": days_remaining,
                "plan": payload.get("plan"),
                "features": payload.get("feat", []),
                "renewals_remaining": payload.get("rnw"),
            }
        )
        return base

    def get_info(self) -> dict[str, Any]:
        status = self.get_status()
        if not status.get("paired"):
            return {
                "machine_id": self._machine_id,
                "paired": False,
            }
        return {
            "machine_id": status.get("machine_id"),
            "paired": True,
            "expires_at": status.get("expires_at"),
            "plan": status.get("plan"),
            "features": status.get("features", []),
            "renewals_remaining": status.get("renewals_remaining"),
            "days_remaining": status.get("days_remaining", 0),
        }

    def _load_state(self) -> Optional[dict[str, Any]]:
        if not self._secret_path.exists():
            return None
        try:
            key = _derive_cache_key(self._fingerprint)
            raw = base64.b64decode(self._secret_path.read_bytes())
            decrypted = _aes_decrypt(raw, key)
            parsed = json.loads(decrypted.decode("utf-8"))
            if not isinstance(parsed, dict):
                return None
            return parsed
        except Exception as exc:
            logger.debug("COLD ROOM: state load failed: %s", exc)
            return None

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            key = _derive_cache_key(self._fingerprint)
            data = json.dumps(state, separators=(",", ":"), sort_keys=True).encode("utf-8")
            encrypted = _aes_encrypt(data, key)
            self._secret_path.parent.mkdir(parents=True, exist_ok=True)
            self._secret_path.write_bytes(base64.b64encode(encrypted))
        except Exception as exc:
            logger.error("COLD ROOM: failed to save state: %s", exc)
