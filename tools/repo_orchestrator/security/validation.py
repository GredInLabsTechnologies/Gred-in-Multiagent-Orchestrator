import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from tools.repo_orchestrator.config import ALLOWLIST_PATH, ALLOWLIST_TTL_SECONDS, REPO_REGISTRY_PATH

from .common import load_json_db

logger = logging.getLogger("orchestrator.validation")


def load_repo_registry():
    return load_json_db(REPO_REGISTRY_PATH, lambda: {"active_repo": None, "repos": []})


def save_repo_registry(data: dict):
    REPO_REGISTRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_active_repo_dir() -> Path:
    registry = load_repo_registry()
    active = registry.get("active_repo")
    if active:
        path = Path(active).resolve()
        if path.exists():
            return path
    # Fallback to current dir if nothing active
    return Path.cwd()


def _normalize_path(path_str: str | None, base_dir: Path) -> Optional[Path]:
    try:
        if not isinstance(path_str, str) or not path_str:
            return None
        # Check for null bytes
        if "\0" in path_str:
            return None

        # Check for Windows reserved names (must match exact component, not substring)
        reserved_names = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }
        # Check each path component for exact match with reserved names
        import re

        path_components = re.split(r"[\\/]", path_str)
        for component in path_components:
            # Get base name without extension (e.g., "CON.txt" -> "CON")
            base_name = component.split(".")[0].upper()
            if base_name in reserved_names:
                return None

        requested = Path(path_str)
        if requested.is_absolute():
            resolved = requested.resolve()
        else:
            resolved = (base_dir / requested).resolve()

        # Ensure resolved path is within base_dir
        base_resolved = base_dir.resolve()
        try:
            resolved.relative_to(base_resolved)
        except ValueError:
            # Path is not relative to base_dir, it's outside
            return None

        return resolved
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        logger.warning("Failed to normalize path %s: %s", path_str, exc)
        return None


def validate_path(requested_path: str, base_dir: Path) -> Path:
    target = _normalize_path(requested_path, base_dir)
    if not target:
        raise HTTPException(
            status_code=403, detail="Access denied: Path traversal detected or invalid path."
        )
    return target


def get_allowed_paths(base_dir: Path) -> set[Path]:
    """Load allowed paths from allowlist.json with TTL check."""
    if not ALLOWLIST_PATH.exists():
        return set()
    try:
        data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
        timestamp = data.get("timestamp", 0)
        if time.time() - timestamp > ALLOWLIST_TTL_SECONDS:
            return set()
        return {base_dir / p for p in data.get("paths", [])}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load allowlist: %s", exc)
        return set()


def serialize_allowlist(paths: set[Path]) -> list[dict]:
    """Convert set of paths to serializable list for API response."""
    result = []
    for p in paths:
        try:
            result.append({"path": str(p), "type": "file" if p.is_file() else "dir"})
        except Exception as exc:
            logger.warning("Failed to serialize allowlist path %s: %s", p, exc)
            continue
    return result
