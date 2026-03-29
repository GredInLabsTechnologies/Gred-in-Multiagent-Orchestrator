import logging
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set
from dotenv import load_dotenv

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

load_dotenv()

logger = logging.getLogger(__name__)
APP_MCP_ALLOWED_PROFILES = ("safe", "extended")


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
    actions_max_payload_bytes: int
    subprocess_timeout: int
    search_exclude_dirs: Set[str]
    audit_log_path: Path
    audit_log_max_bytes: int
    audit_log_backup_count: int
    ops_data_dir: Path
    ops_run_ttl: int
    gics_daemon_script: Path
    gics_socket_path: Path
    gics_token_path: Path
    data_dir: Path
    debug: bool
    log_level: str
    # License system
    license_key: str
    license_validate_url: str
    license_public_key_pem: str
    license_cache_path: Path
    license_grace_days: int
    license_recheck_hours: int
    license_allow_debug_bypass: bool
    worktrees_dir: Path
    ephemeral_repos_dir: Path
    repo_mirrors_dir: Path
    app_sessions_dir: Path
    purge_quarantine_dir: Path
    gimo_web_url: str
    gimo_internal_key: str
    # Cold Room (air-gapped) support
    cold_room_enabled: bool
    cold_room_license_path: Path
    cold_room_secret_path: Path
    cold_room_renewal_days: int
    cold_room_public_key_pem: str
    integrity_manifest_path: Path
    integrity_check_enabled: bool
    integrity_public_key_pem: str
    runtime_guard_enabled: bool
    runtime_guard_block_debugger: bool
    # GIMO Inference Engine (GIE) settings
    gimo_inference_enabled: bool
    gimo_model_cache_dir: Path
    gimo_model_cache_max_gb: float
    gimo_npu_enabled: bool
    gimo_max_oversized_ratio: float
    app_mcp_profile: str
    app_mcp_streamable_http: bool


def _load_or_create_token(token_file: Path | None = None, env_key: str = "ORCH_TOKEN") -> str:
    """Load or create a token. Supports both unified .gimo_credentials and legacy separate files.

    Priority:
    1. Environment variable (ORCH_TOKEN, ORCH_ACTIONS_TOKEN, ORCH_OPERATOR_TOKEN)
    2. Unified .gimo_credentials file (new format)
    3. Legacy separate token files (.orch_token, .orch_actions_token, .orch_operator_token)
    4. Generate new token and write to appropriate file
    """
    token_file = token_file or ORCH_TOKEN_FILE
    env_token = os.environ.get(env_key, "").strip()
    if env_token:
        return env_token

    # Try unified credentials file first (new format)
    base_dir = Path(__file__).parent
    unified_creds = base_dir / ".gimo_credentials"
    if unified_creds.exists():
        if not YAML_AVAILABLE:
            logger.warning(
                "Found .gimo_credentials but PyYAML is not installed. "
                "Install with: pip install PyYAML>=6.0.2"
            )
        else:
            try:
                creds_data = yaml.safe_load(unified_creds.read_text(encoding="utf-8"))
                if isinstance(creds_data, dict):
                    # Map env_key to credential key
                    role_key = None
                    if env_key == "ORCH_TOKEN":
                        role_key = "admin"
                    elif env_key == "ORCH_ACTIONS_TOKEN":
                        role_key = "actions"
                    elif env_key == "ORCH_OPERATOR_TOKEN":
                        role_key = "operator"

                    if role_key and role_key in creds_data:
                        token = str(creds_data[role_key]).strip()
                        if token:
                            os.environ[env_key] = token
                            return token
            except Exception as exc:
                logger.warning("Failed to read unified credentials file: %s", exc)

    # Fall back to legacy separate token file
    if token_file.exists():
        try:
            file_token = token_file.read_text(encoding="utf-8").strip()
            if file_token:
                os.environ[env_key] = file_token
                return file_token
        except Exception:
            logger.warning("Failed to read token file %s", token_file)

    # Generate new token
    token = secrets.token_urlsafe(48)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except Exception:
        logger.warning("Failed to chmod token file %s", token_file)
    os.environ[env_key] = token
    return token


def _read_bool_env(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes")


def _normalize_app_mcp_profile(raw_profile: str | None) -> str:
    profile = str(raw_profile or "safe").strip().lower() or "safe"
    if profile not in APP_MCP_ALLOWED_PROFILES:
        allowed = ", ".join(APP_MCP_ALLOWED_PROFILES)
        raise ValueError(f"Invalid ORCH_APP_MCP_PROFILE '{raw_profile}'. Expected one of: {allowed}")
    return profile


def _migrate_to_unified_credentials() -> None:
    """Migrate legacy separate token files to unified .gimo_credentials format.

    Only runs if .gimo_credentials doesn't exist and legacy files do exist.
    Creates a YAML file with all three tokens clearly labeled.

    Requires PyYAML to be installed. If not available, migration is skipped
    and legacy files continue to work.
    """
    if not YAML_AVAILABLE:
        # Silent skip - PyYAML is in requirements.txt but may not be installed yet
        return

    base_dir = Path(__file__).parent
    unified_creds = base_dir / ".gimo_credentials"

    # Skip if unified file already exists
    if unified_creds.exists():
        return

    # Check for legacy token files
    admin_token_file = base_dir / ".orch_token"
    actions_token_file = base_dir / ".orch_actions_token"
    operator_token_file = base_dir / ".orch_operator_token"

    # Collect existing tokens
    tokens = {}
    if admin_token_file.exists():
        try:
            tokens["admin"] = admin_token_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if actions_token_file.exists():
        try:
            tokens["actions"] = actions_token_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if operator_token_file.exists():
        try:
            tokens["operator"] = operator_token_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    # Only migrate if we have at least one legacy token
    if not tokens:
        return

    # Generate missing tokens
    if "admin" not in tokens:
        tokens["admin"] = secrets.token_urlsafe(48)
    if "actions" not in tokens:
        tokens["actions"] = secrets.token_urlsafe(48)
    if "operator" not in tokens:
        tokens["operator"] = secrets.token_urlsafe(48)

    # Write unified credentials file
    try:
        content = (
            "# GIMO Unified Credentials\n"
            "# Auto-generated from legacy token files. DO NOT share the admin token.\n"
            "#\n"
            "# Roles:\n"
            "#   admin    - Full access (only for system owner)\n"
            "#   operator - CLI/daily ops (safe for terminals)\n"
            "#   actions  - Read-only (safe for webhooks/integrations)\n"
            "\n"
            f"admin: \"{tokens['admin']}\"\n"
            f"operator: \"{tokens['operator']}\"\n"
            f"actions: \"{tokens['actions']}\"\n"
        )
        unified_creds.write_text(content, encoding="utf-8")
        try:
            os.chmod(unified_creds, 0o600)
        except Exception:
            pass
        logger.info("Migrated legacy tokens to .gimo_credentials")
    except Exception as exc:
        logger.warning("Failed to migrate tokens to unified format: %s", exc)


def _build_settings() -> Settings:
    # Migrate legacy tokens to unified format if needed
    _migrate_to_unified_credentials()

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
    service_name = os.environ.get("ORCH_SERVICE_NAME", "GIMO")
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
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,http://localhost:9325,http://127.0.0.1:9325",  # nosonar
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
    actions_max_payload_bytes = int(os.environ.get("ORCH_ACTIONS_MAX_PAYLOAD_BYTES", str(64 * 1024)))
    subprocess_timeout = int(os.environ.get("ORCH_SUBPROCESS_TIMEOUT", "10"))
    search_exclude_dirs = {"tools", "scripts"}
    audit_log_path = base_dir / "logs" / "orchestrator_audit.log"
    audit_log_max_bytes = int(os.environ.get("ORCH_AUDIT_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
    audit_log_backup_count = int(os.environ.get("ORCH_AUDIT_LOG_BACKUP_COUNT", "5"))
    ops_data_dir = repo_root_dir / ".orch_data" / "ops"
    worktrees_dir = repo_root_dir / ".orch_data" / "worktrees"
    ephemeral_repos_dir = repo_root_dir / ".orch_data" / "ephemeral_repos"
    repo_mirrors_dir = repo_root_dir / ".orch_data" / "repo_mirrors"
    app_sessions_dir = repo_root_dir / ".orch_data" / "app_sessions"
    purge_quarantine_dir = repo_root_dir / ".orch_data" / "purge_quarantine"
    ops_run_ttl = int(os.environ.get("ORCH_OPS_RUN_TTL", "86400"))
    debug = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")
    log_level = os.environ.get("LOG_LEVEL", "DEBUG" if debug else "INFO").upper()
    app_mcp_profile = _normalize_app_mcp_profile(os.environ.get("ORCH_APP_MCP_PROFILE", "safe"))
    app_mcp_streamable_http = _read_bool_env("ORCH_APP_MCP_STREAMABLE_HTTP", default=True)
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
        actions_max_payload_bytes=actions_max_payload_bytes,
        subprocess_timeout=subprocess_timeout,
        search_exclude_dirs=search_exclude_dirs,
        audit_log_path=audit_log_path,
        audit_log_max_bytes=audit_log_max_bytes,
        audit_log_backup_count=audit_log_backup_count,
        ops_data_dir=ops_data_dir,
        ops_run_ttl=ops_run_ttl,
        gics_daemon_script=_resolve_gics_daemon_script(base_dir),
        gics_socket_path=ops_data_dir / "gics.sock",
        gics_token_path=ops_data_dir / "gics.token",
        data_dir=base_dir / "tools" / "gimo_server" / "data",
        debug=debug,
        log_level=log_level,
        license_key=os.environ.get("ORCH_LICENSE_KEY", ""),
        license_validate_url=os.environ.get(
            "ORCH_LICENSE_URL",
            "https://gimo-web.vercel.app/api/license/validate",
        ),
        license_public_key_pem=os.environ.get("ORCH_LICENSE_PUBLIC_KEY", ""),
        license_cache_path=base_dir / ".gimo_license",
        license_grace_days=int(os.environ.get("ORCH_LICENSE_GRACE_DAYS", "7")),
        license_recheck_hours=int(os.environ.get("ORCH_LICENSE_RECHECK_HOURS", "24")),
        license_allow_debug_bypass=os.environ.get(
            "ORCH_LICENSE_ALLOW_DEBUG_BYPASS", "false"
        ).lower() in ("true", "1", "yes"),
        worktrees_dir=worktrees_dir,
        ephemeral_repos_dir=ephemeral_repos_dir,
        repo_mirrors_dir=repo_mirrors_dir,
        app_sessions_dir=app_sessions_dir,
        purge_quarantine_dir=purge_quarantine_dir,
        gimo_web_url=os.environ.get("GIMO_WEB_URL", "https://gimo-web.vercel.app"),
        gimo_internal_key=os.environ.get("GIMO_INTERNAL_KEY", ""),
        cold_room_enabled=os.environ.get("ORCH_COLD_ROOM_ENABLED", "false").lower() in ("true", "1", "yes"),
        cold_room_license_path=base_dir / ".gimo_cold_room",
        cold_room_secret_path=base_dir / ".gimo_cold_room",
        cold_room_renewal_days=int(os.environ.get("ORCH_COLD_ROOM_RENEWAL_DAYS", "30")),
        cold_room_public_key_pem=os.environ.get("ORCH_COLD_ROOM_PUBLIC_KEY", ""),
        integrity_manifest_path=base_dir / ".gimo_manifest",
        integrity_check_enabled=os.environ.get("ORCH_INTEGRITY_CHECK", "true").lower()
        in ("true", "1", "yes"),
        integrity_public_key_pem=os.environ.get("ORCH_INTEGRITY_PUBLIC_KEY", ""),
        runtime_guard_enabled=os.environ.get("ORCH_RUNTIME_GUARD", "true").lower()
        in ("true", "1", "yes"),
        runtime_guard_block_debugger=os.environ.get("ORCH_BLOCK_DEBUGGER", "false").lower()
        in ("true", "1", "yes"),
        gimo_inference_enabled=os.environ.get("GIMO_INFERENCE_ENABLED", "true").lower()
        in ("true", "1", "yes"),
        gimo_model_cache_dir=Path(
            os.environ.get("GIMO_MODEL_CACHE_DIR", str(Path.home() / ".gimo" / "models"))
        ),
        gimo_model_cache_max_gb=float(os.environ.get("GIMO_MODEL_CACHE_MAX_GB", "50.0")),
        gimo_npu_enabled=os.environ.get("GIMO_NPU_ENABLED", "true").lower()
        in ("true", "1", "yes"),
        gimo_max_oversized_ratio=float(os.environ.get("GIMO_MAX_OVERSIZED_RATIO", "3.0")),
        app_mcp_profile=app_mcp_profile,
        app_mcp_streamable_http=app_mcp_streamable_http,
    )


def _resolve_gics_daemon_script(base_dir: Path) -> Path:
    """Resolve GICS daemon script location with strict local vendor contract.

    Resolution order:
    1) ORCH_GICS_DAEMON_SCRIPT (explicit override)
    2) <repo_root>/vendor/gics/dist/src/daemon/server.js (canonical)

    If canonical is missing, still return canonical path so diagnostics remain clear.
    """
    env_override = os.environ.get("ORCH_GICS_DAEMON_SCRIPT", "").strip()
    if env_override:
        return Path(env_override).resolve()

    canonical = base_dir / "vendor" / "gics" / "dist" / "src" / "daemon" / "server.js"

    if canonical.exists():
        return canonical
    return canonical


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
ACTIONS_MAX_PAYLOAD_BYTES = _SETTINGS.actions_max_payload_bytes
SUBPROCESS_TIMEOUT = _SETTINGS.subprocess_timeout
SEARCH_EXCLUDE_DIRS = _SETTINGS.search_exclude_dirs
AUDIT_LOG_PATH = _SETTINGS.audit_log_path
AUDIT_LOG_MAX_BYTES = _SETTINGS.audit_log_max_bytes
AUDIT_LOG_BACKUP_COUNT = _SETTINGS.audit_log_backup_count
OPS_DATA_DIR = _SETTINGS.ops_data_dir
OPS_RUN_TTL = _SETTINGS.ops_run_ttl
GICS_DAEMON_SCRIPT = _SETTINGS.gics_daemon_script
GICS_SOCKET_PATH = _SETTINGS.gics_socket_path
GICS_TOKEN_PATH = _SETTINGS.gics_token_path
DATA_DIR = _SETTINGS.data_dir
WORKTREES_DIR = _SETTINGS.worktrees_dir
EPHEMERAL_REPOS_DIR = _SETTINGS.ephemeral_repos_dir
REPO_MIRRORS_DIR = _SETTINGS.repo_mirrors_dir
APP_SESSIONS_DIR = _SETTINGS.app_sessions_dir
PURGE_QUARANTINE_DIR = _SETTINGS.purge_quarantine_dir
DEBUG = _SETTINGS.debug
LOG_LEVEL = _SETTINGS.log_level
GIMO_WEB_URL = _SETTINGS.gimo_web_url
GIMO_INTERNAL_KEY = _SETTINGS.gimo_internal_key
GIMO_INFERENCE_ENABLED = _SETTINGS.gimo_inference_enabled
GIMO_MODEL_CACHE_DIR = _SETTINGS.gimo_model_cache_dir
GIMO_MODEL_CACHE_MAX_GB = _SETTINGS.gimo_model_cache_max_gb
GIMO_NPU_ENABLED = _SETTINGS.gimo_npu_enabled
GIMO_MAX_OVERSIZED_RATIO = _SETTINGS.gimo_max_oversized_ratio
APP_MCP_PROFILE = _SETTINGS.app_mcp_profile
APP_MCP_STREAMABLE_HTTP = _SETTINGS.app_mcp_streamable_http
