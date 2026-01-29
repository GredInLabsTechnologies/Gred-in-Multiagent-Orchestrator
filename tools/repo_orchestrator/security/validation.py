import os
import re
import json
from pathlib import Path
from fastapi import HTTPException
from tools.repo_orchestrator.config import (
    REPO_REGISTRY_PATH,
    ALLOWLIST_PATH,
    ALLOWLIST_TTL_SECONDS,
)

def load_repo_registry():
    if not REPO_REGISTRY_PATH.exists():
        return {"active_repo": None, "repos": []}
    try:
        return json.loads(REPO_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"active_repo": None, "repos": []}

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

def _normalize_path(path_str: str, base_dir: Path) -> Path:
    try:
        requested = Path(path_str)
        if requested.is_absolute():
            resolved = requested.resolve()
        else:
            resolved = (base_dir / requested).resolve()
        
        if not str(resolved).startswith(str(base_dir)):
            return None
        return resolved
    except Exception:
        return None

def validate_path(requested_path: str, base_dir: Path) -> Path:
    target = _normalize_path(requested_path, base_dir)
    if not target:
        raise HTTPException(status_code=403, detail="Acceso denegado: Path traversal detectado o path inválido.")
    return target
