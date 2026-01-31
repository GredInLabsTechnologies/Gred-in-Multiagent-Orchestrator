import os
import secrets
from pathlib import Path

import sys

def _get_base_dir() -> Path:
    # Caso PyInstaller: el exe vive en el directorio de instalación
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    
    # Caso dev: buscamos el archivo sentinel repo_registry.json hacia arriba
    # Esto evita depender de un número fijo de 'parent'
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if (parent / "tools" / "repo_orchestrator" / "repo_registry.json").exists():
            return parent
            
    # Fallback al directorio actual si no se encuentra
    return Path.cwd()

BASE_DIR = _get_base_dir()
REPO_ROOT_DIR = Path(os.environ.get("ORCH_REPO_ROOT", str(BASE_DIR.parent))).resolve()
REPO_REGISTRY_PATH = Path(os.environ.get(
    "ORCH_REPO_REGISTRY",
    str(Path(__file__).parent / "repo_registry.json"),
)).resolve()
VITAMINIZE_PACKAGE = {
    "tools/repo_orchestrator",
    "tools/orchestrator_ui",
    "scripts/start_orch.cmd",
    "scripts/launch_orchestrator.ps1",
}

SERVICE_NAME = os.environ.get("ORCH_SERVICE_NAME", "GILOrchestrator")

# Security Guardrails
ALLOWED_EXTENSIONS = {".ts", ".tsx", ".py", ".go", ".rs", ".c", ".cpp", ".json", ".yaml"}
DENIED_EXTENSIONS = {".md", ".rst", ".adoc", ".txt", ".env", ".pem", ".key"}
DENIED_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}

# Snapshot configuration
# GPT will only read from these temporary copies.
SNAPSHOT_DIR = BASE_DIR / ".orch_snapshots"
SNAPSHOT_TTL = int(os.environ.get("ORCH_SNAPSHOT_TTL", "240"))  # 4 minutes in seconds

# Dynamic allowlist (TTL) configuration
# Antigravity should update allowed_paths.json after modifying files.
ALLOWLIST_PATH = BASE_DIR / "tools" / "repo_orchestrator" / "allowed_paths.json"
ALLOWLIST_TTL_SECONDS = int(os.environ.get("ORCH_ALLOWLIST_TTL", "240"))
ALLOWLIST_REQUIRE = os.environ.get("ORCH_ALLOWLIST_REQUIRE", "true").lower() == "true"

# Output Limitations
MAX_LINES = 500
MAX_BYTES = 250000

# CORS (default to local dashboard/dev origins; override with ORCH_CORS_ORIGINS)
_cors_env = os.environ.get(
    "ORCH_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,http://localhost:6834,http://127.0.0.1:6834",
)
CORS_ORIGINS = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]

# Auth Configuration
# The orchestrator prefers ORCH_TOKEN, but will generate a strong local token if missing.
ORCH_TOKEN_FILE = Path(
    os.environ.get("ORCH_TOKEN_FILE", str(Path(__file__).parent / ".orch_token"))
).resolve()

def _load_or_create_token() -> str:
    env_token = os.environ.get("ORCH_TOKEN", "").strip()
    if env_token:
        return env_token
    if ORCH_TOKEN_FILE.exists():
        try:
            file_token = ORCH_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if file_token:
                os.environ["ORCH_TOKEN"] = file_token
                return file_token
        except Exception:
            pass
    token = secrets.token_urlsafe(48)
    ORCH_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    ORCH_TOKEN_FILE.write_text(token, encoding="utf-8")
    try:
        os.chmod(ORCH_TOKEN_FILE, 0o600)
    except Exception:
        pass
    os.environ["ORCH_TOKEN"] = token
    return token

TOKENS = {_load_or_create_token()}

# Rate Limiting
RATE_LIMIT_PER_MIN = 100
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("ORCH_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_CLEANUP_SECONDS = int(os.environ.get("ORCH_RATE_LIMIT_CLEANUP_SECONDS", "120"))

# Subprocess guard
SUBPROCESS_TIMEOUT = int(os.environ.get("ORCH_SUBPROCESS_TIMEOUT", "10"))

# Search guardrails
SEARCH_EXCLUDE_DIRS = {"tools", "scripts"}

# Logging
AUDIT_LOG_PATH = BASE_DIR / "logs" / "orchestrator_audit.log"
AUDIT_LOG_MAX_BYTES = int(os.environ.get("ORCH_AUDIT_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
AUDIT_LOG_BACKUP_COUNT = int(os.environ.get("ORCH_AUDIT_LOG_BACKUP_COUNT", "5"))
