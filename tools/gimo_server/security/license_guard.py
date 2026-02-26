"""
GIMO LicenseGuard — Validación Híbrida Online/Offline
======================================================
Gate de licencia que se ejecuta en startup y periódicamente.
Soporta validación online (GIMO WEB) y offline (JWT cache cifrado).
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import platform
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orchestrator.license")

# Clave pública Ed25519 embebida como fallback si no hay env var.
# Generada con scripts/generate_license_keys.py — 2026-02-18
EMBEDDED_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEApdItyqfVuHkGDXTvzwJrfSSnL3JoXQyWtx8y1hDSA9Y=
-----END PUBLIC KEY-----"""

# Salt para derivación de clave AES del cache — fijo y embebido
_CACHE_KEY_SALT = b"GIMO-CACHE-AES-2026-v1"

# Versión del guard — incrementar en cada release para distinguir
# updates legítimos de modificaciones maliciosas.
_GUARD_VERSION = "1.0.0"


@dataclass
class LicenseStatus:
    valid: bool
    reason: str = ""
    plan: str = ""
    expires_at: Optional[str] = None
    is_lifetime: bool = False
    installations_used: int = 0
    installations_max: int = 2


@dataclass
class _OnlineResponse:
    """Estructura validada de la respuesta de /api/license/validate."""
    valid: bool
    token: str = ""
    plan: str = "standard"
    expiresAt: Optional[str] = None
    isLifetime: bool = False
    activeInstallations: int = 0
    maxInstallations: int = 2
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "_OnlineResponse":
        return cls(
            valid=bool(data.get("valid", False)),
            token=str(data.get("token", "")),
            plan=str(data.get("plan", "standard")),
            expiresAt=data.get("expiresAt"),
            isLifetime=bool(data.get("isLifetime", False)),
            activeInstallations=int(data.get("activeInstallations", 0)),
            maxInstallations=int(data.get("maxInstallations", 2)),
            error=data.get("error"),
        )


def _derive_cache_key(fingerprint: str) -> bytes:
    """Deriva una clave AES-256 del fingerprint de la máquina."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes as crypto_hashes

    kdf = PBKDF2HMAC(
        algorithm=crypto_hashes.SHA256(),
        length=32,
        salt=_CACHE_KEY_SALT,
        iterations=100_000,
    )
    return kdf.derive(fingerprint.encode("utf-8"))


def _aes_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Cifra con AES-256-GCM. Retorna nonce(12) + tag(16) + ciphertext."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def _aes_decrypt(data: bytes, key: bytes) -> bytes:
    """Descifra AES-256-GCM. Lanza excepción si el tag falla."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def _verify_jwt_ed25519(token: str, public_key_pem: str) -> Optional[dict]:
    """Verifica un JWT firmado con Ed25519. Retorna payload o None."""
    try:
        import jwt as pyjwt
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        public_key = load_pem_public_key(public_key_pem.encode("utf-8"))
        payload = pyjwt.decode(
            token,
            public_key,  # type: ignore[arg-type]
            algorithms=["EdDSA"],
            options={"verify_exp": True},
        )
        return payload
    except Exception as e:
        logger.debug("JWT verification failed: %s", e)
        return None


def _get_public_key_pem() -> str:
    """Retorna la clave pública Ed25519 (env var o embebida)."""
    env_key = os.environ.get("ORCH_LICENSE_PUBLIC_KEY", "").strip()
    if env_key:
        return env_key.replace("\\n", "\n")
    return EMBEDDED_PUBLIC_KEY


class LicenseGuard:
    CACHE_FILE = ".gimo_license"
    DEFAULT_GRACE_PERIOD_DAYS = 3
    DEFAULT_RECHECK_INTERVAL_HOURS = 24

    def __init__(self, settings=None):
        # Fix #2: Usar settings.* en vez de os.environ directamente
        if settings is not None:
            self._license_key = (settings.license_key or "").strip()
            self._validate_url = settings.license_validate_url
            self._cache_path = Path(settings.license_cache_path)
            self._grace_period_days = max(1, int(settings.license_grace_days or self.DEFAULT_GRACE_PERIOD_DAYS))
            self._recheck_interval_hours = max(
                1,
                int(settings.license_recheck_hours or self.DEFAULT_RECHECK_INTERVAL_HOURS),
            )
            self._allow_debug_bypass = bool(getattr(settings, "license_allow_debug_bypass", False))
            # Clave pública: settings tiene precedencia, luego env/embebida
            raw_key = settings.license_public_key_pem or ""
            self._public_key_pem = raw_key.replace("\\n", "\n") if raw_key else _get_public_key_pem()
        else:
            self._license_key = os.environ.get("ORCH_LICENSE_KEY", "").strip()
            self._validate_url = os.environ.get(
                "ORCH_LICENSE_URL",
                "https://gimo-web.vercel.app/api/license/validate",
            )
            self._cache_path = Path.cwd() / self.CACHE_FILE
            self._grace_period_days = max(
                1,
                int(os.environ.get("ORCH_LICENSE_GRACE_DAYS", str(self.DEFAULT_GRACE_PERIOD_DAYS))),
            )
            self._recheck_interval_hours = max(
                1,
                int(os.environ.get("ORCH_LICENSE_RECHECK_HOURS", str(self.DEFAULT_RECHECK_INTERVAL_HOURS))),
            )
            self._allow_debug_bypass = os.environ.get(
                "ORCH_LICENSE_ALLOW_DEBUG_BYPASS",
                "false",
            ).lower() in ("true", "1", "yes")
            self._public_key_pem = _get_public_key_pem()
        # Fix #6: Cache del fingerprint para evitar subprocesos dobles (wmic en Windows)
        self._cached_fingerprint: Optional[str] = None
        # Marcador: _GUARD_VERSION cambió → se actualizó el software → forzar online
        self._guard_version_updated: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate(self) -> LicenseStatus:
        """Punto de entrada principal. Intenta online, fallback offline."""
        debug_mode = os.environ.get("DEBUG", "false").lower() in ("true", "1")

        if not self._license_key:
            if debug_mode and self._allow_debug_bypass:
                logger.warning(
                    "LICENSE: ORCH_LICENSE_KEY not set (DEBUG bypass enabled by ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true)"
                )
                return LicenseStatus(valid=True, reason="debug_mode", plan="debug")
            if debug_mode and not self._allow_debug_bypass:
                logger.critical(
                    "LICENSE: ORCH_LICENSE_KEY missing in DEBUG mode. "
                    "Bypass is disabled (set ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true only for local lab)."
                )
            return LicenseStatus(valid=False, reason="ORCH_LICENSE_KEY environment variable not set")

        # ── Cold Room: air-gapped environment support ──
        try:
            from tools.gimo_server.security.cold_room import ColdRoomManager
            settings = None
            try:
                from tools.gimo_server.config import get_settings
                settings = get_settings()
            except Exception:
                pass
            if settings and settings.cold_room_enabled:
                cr = ColdRoomManager(settings)
                if cr.is_paired():
                    if cr.is_renewal_valid():
                        logger.info("LICENSE: Cold Room validation OK")
                        return LicenseStatus(valid=True, plan="cold_room", reason="cold_room_active")
                    else:
                        return LicenseStatus(valid=False, reason="cold_room_renewal_required")
        except ImportError:
            pass

        # Verificar integridad del propio archivo
        if not self._verify_file_integrity():
            return LicenseStatus(valid=False, reason="License guard file integrity check failed (anti-tamper)")

        # Intentar validación online
        try:
            result = await self._validate_online()
            if result.valid:
                if self._guard_version_updated:
                    logger.info("LICENSE: Guard updated to v%s — hash refreshed in cache", _GUARD_VERSION)
                logger.info("LICENSE: Online validation OK (plan=%s)", result.plan)
                return result
            else:
                logger.warning("LICENSE: Online validation FAILED: %s", result.reason)
                return result
        except Exception as e:
            logger.warning("LICENSE: Online validation unavailable (%s), trying offline cache...", e)

        # Si la versión cambió (update legítimo) pero no hay red:
        # Permitimos arranque offline — el hash se habrá actualizado en el próximo
        # recheck online. La licencia sigue válida.
        if self._guard_version_updated:
            logger.warning(
                "LICENSE: Guard updated to v%s but network unavailable. "
                "Allowing offline validation (hash will refresh on next online check).",
                _GUARD_VERSION,
            )

        # Fallback: validación offline
        return self._validate_offline()

    async def periodic_recheck(self):
        """Task asyncio: re-valida online cada 24h en background."""
        while True:
            try:
                # Skip periodic recheck in cold room mode
                try:
                    from tools.gimo_server.config import get_settings
                    s = get_settings()
                    if s.cold_room_enabled:
                        await asyncio.sleep(self._recheck_interval_hours * 3600)
                        continue
                except Exception:
                    pass
                await asyncio.sleep(self._recheck_interval_hours * 3600)
                result = await self._validate_online()
                if not result.valid:
                    logger.critical("LICENSE REVOKED REMOTELY: %s — shutting down.", result.reason)
                    sys.exit(1)
                else:
                    logger.debug("LICENSE: Periodic recheck OK")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("LICENSE: Periodic recheck skipped (offline): %s", e)

    # ------------------------------------------------------------------
    # Online validation
    # ------------------------------------------------------------------

    _RETRY_ATTEMPTS = 3
    _RETRY_BASE_DELAY = 1.0  # seconds — backoff: 1s, 2s, 4s

    async def _validate_online(self) -> LicenseStatus:
        """Llama a /api/license/validate en GIMO WEB con retry + backoff exponencial."""
        import httpx
        from tools.gimo_server.security.fingerprint import (
            generate_fingerprint,
            generate_fingerprint_components,
        )

        fingerprint = generate_fingerprint()
        components = generate_fingerprint_components()

        payload = {
            "licenseKey": self._license_key,
            "machineFingerprint": fingerprint,
            "machineLabel": f"{platform.system()} - {socket.gethostname()}",
            "os": platform.system().lower(),
            "hostname": socket.gethostname(),
            "appVersion": "1.0.0",
        }

        last_error: Optional[Exception] = None
        for attempt in range(self._RETRY_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(self._validate_url, json=payload)

                if resp.status_code == 200:
                    parsed = _OnlineResponse.from_dict(resp.json())
                    if parsed.valid:
                        self._save_cache(parsed.token, fingerprint, components)
                        return LicenseStatus(
                            valid=True,
                            plan=parsed.plan,
                            expires_at=parsed.expiresAt,
                            is_lifetime=parsed.isLifetime,
                            installations_used=parsed.activeInstallations,
                            installations_max=parsed.maxInstallations,
                        )
                    else:
                        # Rechazo explícito del servidor — no reintentar
                        return LicenseStatus(valid=False, reason=parsed.error or "rejected")
                else:
                    last_error = ConnectionError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                last_error = e

            # Backoff exponencial: 1s, 2s, 4s
            if attempt < self._RETRY_ATTEMPTS - 1:
                delay = self._RETRY_BASE_DELAY * (2 ** attempt)
                logger.debug("LICENSE: Online attempt %d/%d failed, retrying in %.1fs...", attempt + 1, self._RETRY_ATTEMPTS, delay)
                await asyncio.sleep(delay)

        # Todos los intentos fallaron — propagar para fallback offline
        raise last_error or ConnectionError("Online validation failed after retries")

    # ------------------------------------------------------------------
    # Offline validation
    # ------------------------------------------------------------------

    def _validate_offline(self) -> LicenseStatus:
        """Valida usando el JWT cacheado en disco."""
        # Fix #4: Detectar placeholder de clave pública antes de intentar verificar JWT
        if "PLACEHOLDER" in self._public_key_pem:
            return LicenseStatus(
                valid=False,
                reason=(
                    "Public key not configured — run scripts/generate_license_keys.py "
                    "and set ORCH_LICENSE_PUBLIC_KEY"
                ),
            )

        if "BEGIN PUBLIC KEY" not in self._public_key_pem:
            return LicenseStatus(
                valid=False,
                reason="Public key format invalid — expected PEM public key",
            )

        cached = self._load_cache()
        if not cached:
            return LicenseStatus(valid=False, reason="No valid offline cache found and network is unavailable")

        token = cached.get("token", "")
        last_online = cached.get("last_online_ts", 0)
        stored_components = cached.get("fingerprint_components", {})

        # Verificar JWT Ed25519
        payload = _verify_jwt_ed25519(token, self._public_key_pem)
        if not payload:
            return LicenseStatus(valid=False, reason="Offline JWT verification failed")

        # Anti clock-tampering: reloj del sistema no puede ser anterior a iat
        now_ts = time.time()
        iat = payload.get("iat", 0)
        if now_ts < iat - 300:  # 5 min de tolerancia
            return LicenseStatus(valid=False, reason="System clock tampered (behind JWT issue time)")

        # Grace period: última validación online < 7 días
        grace_seconds = self._grace_period_days * 86400
        if now_ts - last_online > grace_seconds:
            days_ago = int((now_ts - last_online) / 86400)
            return LicenseStatus(
                valid=False,
                reason=f"Grace period expired ({days_ago} days since last online check, max {self._grace_period_days})",
            )

        # Fuzzy fingerprint check
        if stored_components:
            from tools.gimo_server.security.fingerprint import (
                generate_fingerprint_components,
                compare_fingerprints,
            )
            current_components = generate_fingerprint_components()
            if not compare_fingerprints(stored_components, current_components):
                return LicenseStatus(valid=False, reason="Machine fingerprint mismatch — license is not valid on this machine")

        grace_remaining = int((grace_seconds - (now_ts - last_online)) / 86400)
        logger.info(
            "LICENSE: Offline validation OK (grace period: %d days remaining)",
            grace_remaining,
        )
        return LicenseStatus(
            valid=True,
            plan=payload.get("plan", "standard"),
            is_lifetime=payload.get("lifetime", False),
            installations_max=payload.get("max", 2),
            reason=f"offline_cache (grace {grace_remaining}d remaining)",
        )

    # ------------------------------------------------------------------
    # Cache management (AES-256-GCM, machine-bound)
    # ------------------------------------------------------------------

    def _save_cache(self, token: str, fingerprint: str, components: dict) -> None:
        """Guarda JWT + metadata cifrado con AES-GCM derivado del fingerprint."""
        try:
            key = _derive_cache_key(fingerprint)
            data = json.dumps({
                "token": token,
                "last_online_ts": time.time(),
                "fingerprint_components": components,
                "file_hash": self._compute_own_hash(),
                # guard_version permite distinguir updates legítimos de tamper
                "guard_version": _GUARD_VERSION,
            }).encode("utf-8")
            encrypted = _aes_encrypt(data, key)
            self._cache_path.write_bytes(base64.b64encode(encrypted))
            logger.debug("LICENSE: Cache saved to %s", self._cache_path)
        except Exception as e:
            logger.warning("LICENSE: Failed to save cache: %s", e)

    def _load_cache(self) -> Optional[dict]:
        """Lee y descifra el cache. Retorna None si no existe o no descifrable."""
        if not self._cache_path.exists():
            return None
        try:
            from tools.gimo_server.security.fingerprint import generate_fingerprint
            # Fix #6: Reutilizar fingerprint cacheado para evitar subproceso wmic doble
            if self._cached_fingerprint is None:
                self._cached_fingerprint = generate_fingerprint()
            fingerprint = self._cached_fingerprint
            key = _derive_cache_key(fingerprint)
            raw = base64.b64decode(self._cache_path.read_bytes())
            decrypted = _aes_decrypt(raw, key)
            return json.loads(decrypted.decode("utf-8"))
        except Exception as e:
            logger.debug("LICENSE: Cache load failed (different machine or corrupted): %s", e)
            return None

    # ------------------------------------------------------------------
    # Integrity check (anti-tamper)
    # ------------------------------------------------------------------

    def _compute_own_hash(self) -> str:
        """Calcula SHA-256 de este archivo."""
        try:
            own_path = Path(__file__)
            return hashlib.sha256(own_path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def _verify_file_integrity(self) -> bool:
        """
        Anti-tamper inteligente con version-tagging.

        Lógica:
        ┌──────────────────────────────────────────────────────────────────┐
        │ Versión cache == _GUARD_VERSION  →  compara hashes               │
        │   • hash igual   → OK ✅                                         │
        │   • hash distinto → TAMPER detectado ❌ (mismo código, editado)  │
        │                                                                   │
        │ Versión cache != _GUARD_VERSION  →  UPDATE LEGÍTIMO ✅           │
        │   • Se marca _guard_version_updated = True                        │
        │   • Se fuerza online recheck (actualiza hash/versión en cache)    │
        │   • Si sin red → offline con advertencia (licencia sigue válida)  │
        └──────────────────────────────────────────────────────────────────┘

        Para updates: solo incrementar _GUARD_VERSION = "x.y.z" en el release.
        Nunca más hay que borrar .gimo_license manualmente.
        """
        cached = self._load_cache()
        if not cached:
            return True  # Sin cache previo — primer arranque

        stored_hash = cached.get("file_hash", "")
        stored_version = cached.get("guard_version", "")

        if not stored_hash:
            return True  # Cache sin hash (versión muy antigua) — OK

        current_hash = self._compute_own_hash()

        # ── Versión diferente → UPDATE LEGÍTIMO ──────────────────────────
        if stored_version != _GUARD_VERSION:
            logger.info(
                "LICENSE: Guard version changed %s → %s (legitimate update). "
                "Online recheck will refresh the cache.",
                stored_version or "legacy",
                _GUARD_VERSION,
            )
            self._guard_version_updated = True
            return True  # Permitir, la validación online actualizará el hash

        # ── Misma versión, hash distinto → TAMPER ────────────────────────
        if stored_hash != current_hash:
            logger.critical(
                "LICENSE: TAMPER DETECTED — license_guard.py was modified "
                "without a version bump. stored_hash=%s... current_hash=%s...",
                stored_hash[:16],
                current_hash[:16],
            )
            return False

        return True  # Versión y hash coinciden → OK ✅
