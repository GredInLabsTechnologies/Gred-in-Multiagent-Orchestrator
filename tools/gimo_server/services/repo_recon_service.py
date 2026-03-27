import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import List, Dict, Any, Optional

from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.services.repo_service import RepoService
from tools.gimo_server.services.git_service import GitService

logger = logging.getLogger("orchestrator.services.repo_recon")

class RepoReconService:
    """
    P5.1 RepoReconService: Controlled reconnaissance over bound repositories.
    Never exposes host paths in app-facing payloads.
    Generates ReadProofs for every relevant read operation.
    """

    @classmethod
    def _get_repo_path(cls, session_id: str) -> Path:
        session = AppSessionService.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        repo_handle = session.get("repo_id")
        if not repo_handle:
            raise ValueError(f"No repository bound to session {session_id}")
        
        repo_path_str = AppSessionService.get_path_from_handle(repo_handle)
        if not repo_path_str:
            raise ValueError(f"Invalid repo handle: {repo_handle}")

        repo_path = Path(repo_path_str).resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            raise ValueError("Bound repository is unavailable")

        return repo_path

    @classmethod
    def _normalize_rel_path(cls, rel_path: str, *, allow_root: bool = False) -> str:
        raw = str(rel_path or "").replace("\\", "/").strip()
        if not raw:
            raise ValueError("Invalid handle")
        if raw == ".":
            if allow_root:
                return "."
            raise ValueError("Invalid handle")
        normalized = PurePosixPath(raw)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Access outside repository bounds")
        cleaned = PurePosixPath(*[part for part in normalized.parts if part not in ("", ".")]).as_posix()
        if not cleaned:
            if allow_root:
                return "."
            raise ValueError("Invalid handle")
        return cleaned

    @classmethod
    def _resolve_repo_target(cls, repo_path: Path, rel_path: str) -> Path:
        target = (repo_path / rel_path).resolve()
        try:
            target.relative_to(repo_path.resolve())
        except ValueError as exc:
            raise ValueError("Access outside repository bounds") from exc
        return target

    @classmethod
    def _generate_file_handle(cls, rel_path: str) -> str:
        """Generates an opaque handle for a file/dir relative path."""
        # We use a hash to hide the real structure if needed, but it should be consistent
        return hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def _register_handle(cls, session_id: str, handle: str, rel_path: str):
        """Registers a handle in the session for later resolution."""
        session = AppSessionService.get_session(session_id)
        if not session:
            return
        
        if "recon_handles" not in session:
            session["recon_handles"] = {}
        
        session["recon_handles"][handle] = rel_path
        AppSessionService._save_session(session_id, session)

    @classmethod
    def _resolve_handle(cls, session_id: str, handle: str) -> Optional[str]:
        """Resolves an opaque handle back to a relative path."""
        session = AppSessionService.get_session(session_id)
        if not session:
            return None
        
        mapping = session.get("recon_handles", {})
        return mapping.get(handle)

    @classmethod
    def list_files(cls, session_id: str, path_handle: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists files in a directory using an opaque handle or root."""
        repo_path = cls._get_repo_path(session_id)
        
        rel_path = "."
        if path_handle:
            rel_path = cls._resolve_handle(session_id, path_handle)
            if rel_path is None:
                raise ValueError("Invalid directory handle")
            rel_path = cls._normalize_rel_path(rel_path)

        if rel_path == ".":
            target_dir = repo_path
        else:
            target_dir = cls._resolve_repo_target(repo_path, rel_path)

        if not target_dir.exists():
            raise ValueError("Directory not found")
        if not target_dir.is_dir():
            raise ValueError("Handle does not refer to a directory")

        entries = []
        for item in target_dir.iterdir():
            # Filter hidden and denied
            if item.name.startswith(".") or item.name in ["node_modules", ".venv", ".git", "__pycache__"]:
                continue
            
            item_rel = str(item.relative_to(repo_path)).replace("\\", "/")
            handle = cls._generate_file_handle(item_rel)
            cls._register_handle(session_id, handle, item_rel)
            
            entries.append({
                "name": item.name,
                "handle": handle,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
                "last_modified": datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc).isoformat()
            })
        
        return sorted(entries, key=lambda x: (x["type"] != "directory", x["name"].lower()))

    @classmethod
    def search(cls, session_id: str, query: str) -> List[Dict[str, Any]]:
        """Performs a search over the repository and returns matches with opaque handles."""
        repo_path = cls._get_repo_path(session_id)
        
        # We reuse RepoService search but adapt results to opaque handles
        hits = RepoService.perform_search(repo_path, query, None)
        
        results = []
        for hit in hits:
            rel_path = hit["file"].replace("\\", "/")
            handle = cls._generate_file_handle(rel_path)
            cls._register_handle(session_id, handle, rel_path)
            
            results.append({
                "handle": handle,
                "line": hit["line"],
                "content": hit.get("content", "")
            })
        return results

    @classmethod
    def read_file(cls, session_id: str, file_handle: str) -> Dict[str, Any]:
        """Reads a file content and generates a ReadProof."""
        repo_path = cls._get_repo_path(session_id)
        rel_path = cls._resolve_handle(session_id, file_handle)
        
        if not rel_path:
            raise ValueError("Invalid file handle")

        rel_path = cls._normalize_rel_path(rel_path)
        full_path = cls._resolve_repo_target(repo_path, rel_path)

        if not full_path.exists():
            raise ValueError("File not found")
        if not full_path.is_file():
            raise ValueError("Handle does not refer to a file")

        # Check size limits
        if full_path.stat().st_size > 500000: # 500KB limit for app recon
            raise ValueError("File too large for reconnaissance")

        content = full_path.read_text(encoding="utf-8", errors="ignore")
        
        # Generate ReadProof (Mandatory 5A)
        proof = cls.generate_read_proof(session_id, rel_path, "read")
        
        return {
            "handle": file_handle,
            "content": content,
            "proof": proof
        }

    @classmethod
    def generate_read_proof(cls, session_id: str, rel_path: str, kind: str) -> Dict[str, Any]:
        """
        Creates and persists a ReadProof evidence in the session.
        Required by DraftValidationService.
        """
        session = AppSessionService.get_session(session_id)
        repo_path = cls._get_repo_path(session_id)
        normalized_rel_path = cls._normalize_rel_path(rel_path)
        
        repo_handle = session.get("repo_id")
        file_handle = cls._generate_file_handle(normalized_rel_path)
        
        # Get head commit for evidence consistency
        try:
            base_commit = GitService.get_head_commit(repo_path)
        except Exception:
            base_commit = "unknown"

        # Read artifact hash for evidence
        try:
            full_path = cls._resolve_repo_target(repo_path, normalized_rel_path)
            content_bytes = full_path.read_bytes()
            evidence_hash = hashlib.sha256(content_bytes).hexdigest()
        except Exception:
            evidence_hash = hashlib.sha256(normalized_rel_path.encode()).hexdigest()

        proof = {
            "proof_id": str(uuid.uuid4()),
            "repo_handle": repo_handle,
            "artifact_handle": file_handle,
            "kind": kind,
            "evidence_hash": evidence_hash,
            "base_commit": base_commit,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if "read_proofs" not in session:
            session["read_proofs"] = []
            
        session["read_proofs"].append(proof)
        AppSessionService._save_session(session_id, session)
        
        return proof
