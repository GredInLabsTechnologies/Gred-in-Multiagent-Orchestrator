from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


_EMBEDDED_INTEGRITY_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA5E1Dqf8m7bYQYICcT6VNojJJEcR4cSxC11K3P0kVh6s=
-----END PUBLIC KEY-----"""


def _sha256_normalized(file_path: Path) -> str:
    data = file_path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


class IntegrityVerifier:
    def __init__(self, settings):
        self._enabled = bool(getattr(settings, "integrity_check_enabled", True))
        self._manifest_path = Path(getattr(settings, "integrity_manifest_path", ".gimo_manifest"))
        self._base_dir = Path(getattr(settings, "base_dir", Path.cwd()))
        self._debug = bool(getattr(settings, "debug", False))

        configured_key = str(getattr(settings, "integrity_public_key_pem", "") or "").strip()
        pem = configured_key.replace("\\n", "\n") if configured_key else _EMBEDDED_INTEGRITY_PUBLIC_KEY
        self._public_key = self._load_public_key(pem)

    @staticmethod
    def _load_public_key(pem: str) -> Ed25519PublicKey | None:
        try:
            loaded = load_pem_public_key(pem.encode("utf-8"))
            if not isinstance(loaded, Ed25519PublicKey):
                return None
            return loaded
        except Exception:
            return None

    @staticmethod
    def _decode_signature(signature: str) -> bytes | None:
        try:
            return base64.b64decode(signature)
        except Exception:
            return None

    def _should_fail_open(self, reason: str) -> tuple[bool, str]:
        if self._debug:
            return True, f"{reason}_debug_bypass"
        return False, reason

    def verify_manifest(self) -> tuple[bool, str]:
        if not self._enabled:
            return True, "disabled"

        if not self._manifest_path.exists():
            return self._should_fail_open("manifest_missing")

        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False, "invalid_manifest"

        if not isinstance(payload, dict):
            return False, "invalid_manifest"

        # Backward compatibility: manifest antiguo sin firma
        if "manifest" in payload or "signature" in payload:
            manifest = payload.get("manifest")
            signature_b64 = payload.get("signature")
            if not isinstance(manifest, dict):
                return False, "invalid_manifest"
            if not isinstance(signature_b64, str) or not signature_b64.strip():
                return self._should_fail_open("missing_signature")
            if not self._public_key:
                return self._should_fail_open("missing_public_key")

            manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
            signature = self._decode_signature(signature_b64)
            if not signature:
                return False, "invalid_signature_encoding"
            try:
                self._public_key.verify(signature, manifest_bytes)
            except InvalidSignature:
                return False, "invalid_manifest_signature"
            except Exception:
                return False, "manifest_signature_verification_error"
        else:
            # Formato legacy {"files": ...}
            return self._should_fail_open("unsigned_manifest_legacy")

        files = manifest.get("files")
        if not isinstance(files, dict):
            return False, "invalid_manifest"

        for rel_path, expected_hash in files.items():
            if not isinstance(rel_path, str) or not isinstance(expected_hash, str):
                return False, "invalid_manifest"

            abs_path = (self._base_dir / rel_path).resolve()
            if not abs_path.exists() or not abs_path.is_file():
                return False, "file_missing"

            actual_hash = _sha256_normalized(abs_path)
            if actual_hash != expected_hash:
                return False, "hash_mismatch"

        return True, "ok"
