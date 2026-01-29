from pathlib import Path
import json

SECURITY_DB_PATH = Path(__file__).parent.parent / "security_db.json"

def load_security_db():
    if not SECURITY_DB_PATH.exists():
        return {"panic_mode": False, "recent_events": []}
    try:
        return json.loads(SECURITY_DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"panic_mode": False, "recent_events": []}

def save_security_db(db: dict):
    SECURITY_DB_PATH.write_text(json.dumps(db, indent=2), encoding="utf-8")

from .auth import verify_token
from .audit import audit_log, redact_sensitive_data
from .validation import validate_path, get_active_repo_dir, load_repo_registry, save_repo_registry
from .rate_limit import check_rate_limit, rate_limit_store
