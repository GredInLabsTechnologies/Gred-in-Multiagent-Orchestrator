"""
Configuración del gateway de GPT Actions.

Todas las variables de entorno relevantes tienen el prefijo GPTGW_.
Los valores por defecto son seguros: allowlist requerido, localhost no bypaseado.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").lower().strip()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def _find_repo_root() -> Path:
    """Localiza la raíz del repositorio subiendo desde este archivo."""
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if (parent / "tools" / "gimo_server" / "repo_registry.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()


# ------------------------------------------------------------------
# Rutas
# ------------------------------------------------------------------

# Raíz del jail donde Actions puede escribir patches
JAIL_ROOT: Path = Path(
    os.environ.get(
        "GPTGW_JAIL_ROOT",
        str(_REPO_ROOT.parent / "worktrees" / "gptactions"),
    )
).resolve()

# Directorio de logs del gateway
LOG_DIR: Path = Path(
    os.environ.get("GPTGW_LOG_DIR", str(_REPO_ROOT / "logs" / "gptactions"))
).resolve()

# Archivo del allowlist de IPs de OpenAI
IP_ALLOWLIST_PATH: Path = Path(
    os.environ.get(
        "GPTGW_IP_ALLOWLIST",
        str(_REPO_ROOT / "tools" / "gptactions_gateway" / "openai_ips.json"),
    )
).resolve()

# Archivo de clave pública del validador (Ed25519, PEM)
# El validador tiene la clave PRIVADA; el integrador/gateway solo necesita la pública
ATTESTATION_PUBLIC_KEY_PATH: Path = Path(
    os.environ.get(
        "GPTGW_ATTESTATION_PUBKEY",
        str(_REPO_ROOT / "tools" / "patch_validator" / "keys" / "attestation_public.pem"),
    )
).resolve()

# Directorio de datos del gateway (fuera del jail)
GATEWAY_DATA_DIR: Path = Path(
    os.environ.get("GPTGW_DATA_DIR", str(_REPO_ROOT / ".gptgw_data"))
).resolve()

# Manifest de archivos accesibles a Actions (allowlist de lectura)
MANIFEST_PATH: Path = JAIL_ROOT / "manifest" / "readable_files.json"


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

def _load_or_create_token(path: Path, env_key: str) -> str:
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        return env_val
    if path.exists():
        val = path.read_text(encoding="utf-8").strip()
        if val:
            return val
    token = secrets.token_urlsafe(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    try:
        import stat
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except Exception:
        pass
    return token


GATEWAY_TOKEN_FILE = GATEWAY_DATA_DIR / ".gptgw_token"
GATEWAY_TOKEN: str = _load_or_create_token(GATEWAY_TOKEN_FILE, "GPTGW_TOKEN")


# ------------------------------------------------------------------
# Seguridad de red
# ------------------------------------------------------------------

# Si True, permite IPs de loopback (127.x) sin pasar por allowlist.
# SOLO para desarrollo. Produción: False.
BYPASS_LOOPBACK: bool = _env_bool("GPTGW_BYPASS_LOOPBACK", False)

# Si True, permite IPs privadas RFC-1918. Solo para pruebas internas.
BYPASS_PRIVATE: bool = _env_bool("GPTGW_BYPASS_PRIVATE", False)

# Si True, bloquea con 503 cuando el allowlist de IPs está desactualizado
BLOCK_ON_STALE_ALLOWLIST: bool = _env_bool("GPTGW_BLOCK_ON_STALE_ALLOWLIST", True)


# ------------------------------------------------------------------
# Rate limiting
# ------------------------------------------------------------------

# Máximo de requests por minuto por IP (global)
RATE_LIMIT_PER_MIN: int = _env_int("GPTGW_RATE_LIMIT_PER_MIN", 20)

# Máximo de propuestas de patch por hora por IP
PATCH_RATE_LIMIT_PER_HOUR: int = _env_int("GPTGW_PATCH_RATE_LIMIT_PER_HOUR", 5)


# ------------------------------------------------------------------
# Patches
# ------------------------------------------------------------------

# TTL en segundos antes de que un patch pendiente sea archivado automáticamente
PATCH_TTL_SECONDS: int = _env_int("GPTGW_PATCH_TTL_SECONDS", 86_400)  # 24h


# ------------------------------------------------------------------
# Servidor
# ------------------------------------------------------------------

HOST: str = os.environ.get("GPTGW_HOST", "127.0.0.1")
PORT: int = _env_int("GPTGW_PORT", 9326)
DEBUG: bool = _env_bool("GPTGW_DEBUG", False)
LOG_LEVEL: str = os.environ.get("GPTGW_LOG_LEVEL", "DEBUG" if DEBUG else "INFO").upper()
