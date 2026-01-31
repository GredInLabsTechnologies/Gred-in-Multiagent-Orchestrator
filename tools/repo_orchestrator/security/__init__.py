import json
from pathlib import Path

SECURITY_DB_PATH = Path(__file__).parent.parent / "security_db.json"

from .common import load_json_db


def load_security_db():
    return load_json_db(SECURITY_DB_PATH, lambda: {"panic_mode": False, "recent_events": []})


def save_security_db(db: dict):
    SECURITY_DB_PATH.write_text(json.dumps(db, indent=2), encoding="utf-8")


from .audit import audit_log, redact_sensitive_data
from .auth import verify_token
from .rate_limit import check_rate_limit, rate_limit_store
from .validation import (
    get_active_repo_dir,
    get_allowed_paths,
    load_repo_registry,
    save_repo_registry,
    serialize_allowlist,
    validate_path,
)
