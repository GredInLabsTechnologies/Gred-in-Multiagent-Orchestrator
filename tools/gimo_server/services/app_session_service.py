import hashlib
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.gimo_server.config import get_settings
from tools.gimo_server.security.path_safety import PathTraversalError, safe_join
from tools.gimo_server.services.git_service import GitService
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
    def _get_bound_repos_dir(cls) -> Path:
        path = cls._get_sessions_dir() / "_repos"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _get_session_path(cls, session_id: str) -> Path:
        # Guard against path traversal via untrusted session_id (S2083/S6549).
        return safe_join(cls._get_sessions_dir(), f"{session_id}.json")

    @classmethod
    def _get_bound_repo_workspace(cls, session_id: str) -> Path:
        # Guard against path traversal via untrusted session_id (S2083/S6549).
        return safe_join(cls._get_bound_repos_dir(), session_id)

    @classmethod
    def _remove_tree(cls, path: Path) -> None:
        if not path.exists():
            return

        def _remove_readonly(func, target, _exc_info):
            try:
                Path(target).chmod(0o700)
                func(target)
            except Exception:
                pass

        shutil.rmtree(path, onerror=_remove_readonly)

    @classmethod
    def _provision_bound_repo_workspace(cls, session_id: str, source_repo: Path) -> Path:
        workspace_path = cls._get_bound_repo_workspace(session_id)
        cls._remove_tree(workspace_path)
        workspace_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            GitService.clone_local(source_repo.parent, source_repo, workspace_path)
            logger.info(
                "Provisioned App repo snapshot via local clone for session %s at %s",
                session_id,
                workspace_path,
            )
        except Exception as exc:
            logger.info(
                "Falling back to filesystem snapshot for App session %s: %s",
                session_id,
                exc,
            )
            cls._remove_tree(workspace_path)
            shutil.copytree(source_repo, workspace_path)

        return workspace_path

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
        try:
            path = cls._get_session_path(session_id)
        except PathTraversalError:
            logger.warning("Rejected session fetch with unsafe id")
            return None
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Error reading session: %s", e)
            return None

    @classmethod
    def bind_repo(cls, session_id: str, repo_handle: str) -> bool:
        session = cls.get_session(session_id)
        if not session:
            return False

        repo_path_str = cls.get_path_from_handle(repo_handle)
        if not repo_path_str:
            return False
        repo_path = Path(repo_path_str).resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            return False

        try:
            cls._provision_bound_repo_workspace(session_id, repo_path)
        except Exception as exc:
            logger.error("Failed to provision App-bound repo snapshot for session %s: %s", session_id, exc)
            return False

        session["repo_id"] = repo_handle
        for key in ("recon_handles", "read_proofs", "context_packs", "context_requests"):
            session.pop(key, None)
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
    def get_bound_repo_path(cls, session_id: str) -> Optional[str]:
        session = cls.get_session(session_id)
        if not session or not session.get("repo_id"):
            return None
        try:
            workspace_path = cls._get_bound_repo_workspace(session_id)
        except PathTraversalError:
            logger.warning("Rejected bound repo resolve with unsafe id")
            return None
        if not workspace_path.exists() or not workspace_path.is_dir():
            return None
        return str(workspace_path)

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
        try:
            path = cls._get_session_path(session_id)
            workspace_path = cls._get_bound_repo_workspace(session_id)
        except PathTraversalError:
            logger.warning("Rejected session purge with unsafe id")
            return False
        deleted = False

        if workspace_path.exists():
            cls._remove_tree(workspace_path)

        if path.exists():
            path.unlink()
            deleted = True

        return deleted

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
