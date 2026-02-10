import logging
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

logger = logging.getLogger(__name__)


def _get_base_dir() -> Path:
    # Caso PyInstaller: el exe vive en el directorio de instalación
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    # Caso dev: buscamos el archivo sentinel repo_registry.json hacia arriba
    # Esto evita depender de un número fijo de 'parent'
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if (parent / "tools" / "gimo_server" / "repo_registry.json").exists():
            return parent

    # Fallback al directorio actual si no se encuentra
    return Path.cwd()


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    repo_root_dir: Path
    repo_registry_path: Path
    vitaminize_package: Set[str]
    service_name: str
    allowed_extensions: Set[str]
    denied_extensions: Set[str]
    denied_dirs: Set[str]
    snapshot_dir: Path
    snapshot_ttl: int
    allowlist_path: Path
    allowlist_ttl_seconds: int
    allowlist_require: bool
    max_lines: int
    max_bytes: int
    cors_origins: List[str]
    orch_token_file: Path
    tokens: Set[str]
    actions_token: str
    operator_token: str
    rate_limit_per_min: int
    rate_limit_window_seconds: int
    rate_limit_cleanup_seconds: int
    subprocess_timeout: int
    search_exclude_dirs: Set[str]
    audit_log_path: Path
    audit_log_max_bytes: int
    audit_log_backup_count: int
    ops_data_dir: Path
    ops_run_ttl: int


def _load_or_create_token(token_file: Path | None = None, env_key: str = "ORCH_TOKEN") -> str:
    token_file = token_file or ORCH_TOKEN_FILE
    env_token = os.environ.get(env_key, "").strip()
    if env_token:
        return env_token
    if token_file.exists():
        try:
            file_token = token_file.read_text(encoding="utf-8").strip()
            if file_token:
                os.environ[env_key] = file_token
                return file_token
        except Exception:
            logger.warning("Failed to read token file %s", token_file)
    token = secrets.token_urlsafe(48)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except Exception:
        logger.warning("Failed to chmod token file %s", token_file)
    os.environ[env_key] = token
    return token


def _build_settings() -> Settings:
    base_dir = _get_base_dir()
    repo_root_dir = Path(os.environ.get("ORCH_REPO_ROOT", str(base_dir.parent))).resolve()
    repo_registry_path = Path(
        os.environ.get(
            "ORCH_REPO_REGISTRY",
            str(Path(__file__).parent / "repo_registry.json"),
        )
    ).resolve()
    vitaminize_package = {
        "tools/gimo_server",
        "tools/orchestrator_ui",
        "scripts/ops/start_orch.cmd",
        "scripts/ops/launch_orchestrator.ps1",
    }
    service_name = os.environ.get("ORCH_SERVICE_NAME", "GILOrchestrator")
    allowed_extensions = {".ts", ".tsx", ".py", ".go", ".rs", ".c", ".cpp", ".json", ".yaml"}
    denied_extensions = {
        ".md",
        ".markdown",
        ".rst",
        ".adoc",
        ".txt",
        ".env",
        ".pem",
        ".key",
    }
    denied_dirs = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}
    snapshot_dir = base_dir / ".orch_snapshots"
    snapshot_ttl = int(os.environ.get("ORCH_SNAPSHOT_TTL", "240"))
    allowlist_path = base_dir / "tools" / "gimo_server" / "allowed_paths.json"
    allowlist_ttl_seconds = int(os.environ.get("ORCH_ALLOWLIST_TTL", "240"))
    allowlist_require = os.environ.get("ORCH_ALLOWLIST_REQUIRE", "true").lower() == "true"
    max_lines = 500
    max_bytes = 250000
    cors_env = os.environ.get(
        "ORCH_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,http://localhost:9325,http://127.0.0.1:9325",
    )
    cors_origins = [origin.strip() for origin in cors_env.split(",") if origin.strip()]
    orch_token_file = Path(
        os.environ.get("ORCH_TOKEN_FILE", str(Path(__file__).parent / ".orch_token"))
    ).resolve()
    actions_token_file = Path(
        os.environ.get(
            "ORCH_ACTIONS_TOKEN_FILE",
            str(Path(__file__).parent / ".orch_actions_token"),
        )
    ).resolve()
    operator_token_file = Path(
        os.environ.get(
            "ORCH_OPERATOR_TOKEN_FILE",
            str(Path(__file__).parent / ".orch_operator_token"),
        )
    ).resolve()
    main_token = _load_or_create_token(orch_token_file, "ORCH_TOKEN")
    actions_token = _load_or_create_token(actions_token_file, "ORCH_ACTIONS_TOKEN")
    operator_token = _load_or_create_token(operator_token_file, "ORCH_OPERATOR_TOKEN")
    tokens = {main_token, actions_token, operator_token}
    rate_limit_per_min = 100
    rate_limit_window_seconds = int(os.environ.get("ORCH_RATE_LIMIT_WINDOW_SECONDS", "60"))
    rate_limit_cleanup_seconds = int(os.environ.get("ORCH_RATE_LIMIT_CLEANUP_SECONDS", "120"))
    subprocess_timeout = int(os.environ.get("ORCH_SUBPROCESS_TIMEOUT", "10"))
    search_exclude_dirs = {"tools", "scripts"}
    audit_log_path = base_dir / "logs" / "orchestrator_audit.log"
    audit_log_max_bytes = int(os.environ.get("ORCH_AUDIT_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
    audit_log_backup_count = int(os.environ.get("ORCH_AUDIT_LOG_BACKUP_COUNT", "5"))
    ops_data_dir = base_dir / ".orch_data" / "ops"
    ops_run_ttl = int(os.environ.get("ORCH_OPS_RUN_TTL", "86400"))
    return Settings(
        base_dir=base_dir,
        repo_root_dir=repo_root_dir,
        repo_registry_path=repo_registry_path,
        vitaminize_package=vitaminize_package,
        service_name=service_name,
        allowed_extensions=allowed_extensions,
        denied_extensions=denied_extensions,
        denied_dirs=denied_dirs,
        snapshot_dir=snapshot_dir,
        snapshot_ttl=snapshot_ttl,
        allowlist_path=allowlist_path,
        allowlist_ttl_seconds=allowlist_ttl_seconds,
        allowlist_require=allowlist_require,
        max_lines=max_lines,
        max_bytes=max_bytes,
        cors_origins=cors_origins,
        orch_token_file=orch_token_file,
        tokens=tokens,
        actions_token=actions_token,
        operator_token=operator_token,
        rate_limit_per_min=rate_limit_per_min,
        rate_limit_window_seconds=rate_limit_window_seconds,
        rate_limit_cleanup_seconds=rate_limit_cleanup_seconds,
        subprocess_timeout=subprocess_timeout,
        search_exclude_dirs=search_exclude_dirs,
        audit_log_path=audit_log_path,
        audit_log_max_bytes=audit_log_max_bytes,
        audit_log_backup_count=audit_log_backup_count,
        ops_data_dir=ops_data_dir,
        ops_run_ttl=ops_run_ttl,
    )


_SETTINGS = _build_settings()


def get_settings() -> Settings:
    return _SETTINGS


BASE_DIR = _SETTINGS.base_dir
REPO_ROOT_DIR = _SETTINGS.repo_root_dir
REPO_REGISTRY_PATH = _SETTINGS.repo_registry_path
VITAMINIZE_PACKAGE = _SETTINGS.vitaminize_package
SERVICE_NAME = _SETTINGS.service_name
ALLOWED_EXTENSIONS = _SETTINGS.allowed_extensions
DENIED_EXTENSIONS = _SETTINGS.denied_extensions
DENIED_DIRS = _SETTINGS.denied_dirs
SNAPSHOT_DIR = _SETTINGS.snapshot_dir
SNAPSHOT_TTL = _SETTINGS.snapshot_ttl
ALLOWLIST_PATH = _SETTINGS.allowlist_path
ALLOWLIST_TTL_SECONDS = _SETTINGS.allowlist_ttl_seconds
ALLOWLIST_REQUIRE = _SETTINGS.allowlist_require
MAX_LINES = _SETTINGS.max_lines
MAX_BYTES = _SETTINGS.max_bytes
CORS_ORIGINS = _SETTINGS.cors_origins
ORCH_TOKEN_FILE = _SETTINGS.orch_token_file
TOKENS = _SETTINGS.tokens
ORCH_ACTIONS_TOKEN = _SETTINGS.actions_token
ORCH_OPERATOR_TOKEN = _SETTINGS.operator_token
RATE_LIMIT_PER_MIN = _SETTINGS.rate_limit_per_min
RATE_LIMIT_WINDOW_SECONDS = _SETTINGS.rate_limit_window_seconds
RATE_LIMIT_CLEANUP_SECONDS = _SETTINGS.rate_limit_cleanup_seconds
SUBPROCESS_TIMEOUT = _SETTINGS.subprocess_timeout
SEARCH_EXCLUDE_DIRS = _SETTINGS.search_exclude_dirs
AUDIT_LOG_PATH = _SETTINGS.audit_log_path
AUDIT_LOG_MAX_BYTES = _SETTINGS.audit_log_max_bytes
AUDIT_LOG_BACKUP_COUNT = _SETTINGS.audit_log_backup_count
OPS_DATA_DIR = _SETTINGS.ops_data_dir
OPS_RUN_TTL = _SETTINGS.ops_run_ttl
