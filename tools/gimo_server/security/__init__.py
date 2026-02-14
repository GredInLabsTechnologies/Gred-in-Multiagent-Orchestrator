import json
from pathlib import Path

SECURITY_DB_PATH = Path(__file__).parent.parent / "security_db.json"

from .common import load_json_db
from .threat_level import ThreatEngine, ThreatLevel


# Global shared threat engine instance
# Initialised at import but can be reset by main.py
threat_engine = ThreatEngine()


def load_security_db():
    data = load_json_db(SECURITY_DB_PATH, lambda: {"panic_mode": False, "recent_events": [], "threat_level": 0})
    # Ensure current levels are synced to threat_engine if needed (normally engine manages its own state)
    # But for backward compat with manual DB edits:
    if "threat_level" in data:
        try:
            threat_engine.level = ThreatLevel(data["threat_level"])
        except (ValueError, TypeError):
            pass
    return data


def save_security_db(db: dict | None = None):
    # If no db provided, save the current threat engine state
    if db is None:
        db = threat_engine.to_dict()
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
