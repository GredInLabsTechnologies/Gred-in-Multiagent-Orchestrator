from pathlib import Path
import json

SECURITY_DB_PATH = Path(__file__).parent.parent / "security_db.json"

from .common import load_json_db

def load_security_db():
    return load_json_db(SECURITY_DB_PATH, lambda: {"panic_mode": False, "recent_events": []})

def save_security_db(db: dict):
    SECURITY_DB_PATH.write_text(json.dumps(db, indent=2), encoding="utf-8")

from .auth import verify_token
from .audit import audit_log, redact_sensitive_data
from .validation import validate_path, get_active_repo_dir, load_repo_registry, save_repo_registry, get_allowed_paths, serialize_allowlist
from .rate_limit import check_rate_limit, rate_limit_store
