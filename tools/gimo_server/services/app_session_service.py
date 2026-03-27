import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.gimo_server.config import get_settings
from tools.gimo_server.services.workspace_policy_service import WorkspacePolicyService

logger = logging.getLogger("orchestrator.services.app_session")

class AppSessionService:
    @classmethod
    def _get_sessions_dir(cls) -> Path:
        settings = get_settings()
        path = settings.app_sessions_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _get_session_path(cls, session_id: str) -> Path:
        return cls._get_sessions_dir() / f"{session_id}.json"

    @classmethod
    def create_session(cls, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        session_metadata = dict(metadata or {})
        session_metadata.update(
            WorkspacePolicyService.default_metadata_for_surface(
                WorkspacePolicyService.SURFACE_CHATGPT_APP
            )
        )
        session_data = {
            "id": session_id,
            "repo_id": None, # handle opaco
            "status": "idle",
            "created_at": now,
            "updated_at": now,
            "metadata": session_metadata
        }
        cls._save_session(session_id, session_data)
        return session_data

    @classmethod
    def get_session(cls, session_id: str) -> Optional[Dict[str, Any]]:
        path = cls._get_session_path(session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Error reading session {session_id}: {e}")
            return None

    @classmethod
    def bind_repo(cls, session_id: str, repo_handle: str) -> bool:
        session = cls.get_session(session_id)
        if not session:
            return False
        
        # Validar el handle mediante el registry sin exponer host paths
        if not cls.validate_handle(repo_handle):
            return False

        session["repo_id"] = repo_handle
        cls._save_session(session_id, session)
        return True

    @classmethod
    def validate_handle(cls, repo_handle: str) -> bool:
        mapping = cls.get_handle_mapping()
        return repo_handle in mapping

    @classmethod
    def get_handle_mapping(cls) -> Dict[str, str]:
        """Returns map of opaque_handle -> real_path"""
        settings = get_settings()
        registry_path = settings.repo_registry_path
        if not registry_path.exists():
            return {}
        
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            repos = data.get("repos", [])
            mapping = {}
            for r in repos:
                # Opaque handle is a short hash of the path
                path_str = str(r)
                path = Path(path_str)
                if not path.exists() or not path.is_dir():
                    continue
                handle = hashlib.sha256(path_str.encode("utf-8")).hexdigest()[:12]
                mapping[handle] = path_str
            return mapping
        except Exception:
            return {}

    @classmethod
    def get_path_from_handle(cls, handle: str) -> Optional[str]:
        return cls.get_handle_mapping().get(handle)

    @classmethod
    def update_status(cls, session_id: str, status: str) -> bool:
        session = cls.get_session(session_id)
        if not session:
            return False
        session["status"] = status
        cls._save_session(session_id, session)
        return True

    @classmethod
    def purge_session(cls, session_id: str) -> bool:
        path = cls._get_session_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    @classmethod
    def list_sessions(cls) -> List[Dict[str, Any]]:
        sessions = []
        for path in cls._get_sessions_dir().glob("*.json"):
            try:
                sessions.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sessions

    @classmethod
    def _save_session(cls, session_id: str, data: Dict[str, Any]):
        path = cls._get_session_path(session_id)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
