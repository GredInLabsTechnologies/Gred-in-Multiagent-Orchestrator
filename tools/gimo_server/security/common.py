import json
import logging
from pathlib import Path

logger = logging.getLogger("orchestrator.security")


def load_json_db(path: Path, default_factory):
    """Generic JSON loader with fallback to default factory."""
    if not path.exists():
        return default_factory()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load JSON db %s: %s", path, exc)
        return default_factory()


def get_safe_actor(actor: str | None) -> str:
    """Sanitize actor name for logging, truncating long tokens."""
    if not actor:
        return "unknown"
    if len(actor) > 20:
        return f"{actor[:8]}...{actor[-4:]}"
    return actor
