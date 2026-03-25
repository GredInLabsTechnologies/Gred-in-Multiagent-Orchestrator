import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
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
        
        return Path(repo_path_str)

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

        target_dir = (repo_path / rel_path).resolve()
        # Scope guard
        if not str(target_dir).startswith(str(repo_path.resolve())):
            raise ValueError("Access outside repository bounds")

        if not target_dir.exists() or not target_dir.is_dir():
            return []

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
        
        full_path = (repo_path / rel_path).resolve()
        if not str(full_path).startswith(str(repo_path.resolve())):
            raise ValueError("Access outside repository bounds")
            
        if not full_path.exists() or not full_path.is_file():
            raise ValueError("File not found")

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
        
        repo_handle = session.get("repo_id")
        file_handle = cls._generate_file_handle(rel_path)
        
        # Get head commit for evidence consistency
        try:
            base_commit = GitService.get_head_commit(repo_path)
        except Exception:
            base_commit = "unknown"

        # Read artifact hash for evidence
        try:
            full_path = repo_path / rel_path
            content_bytes = full_path.read_bytes()
            evidence_hash = hashlib.sha256(content_bytes).hexdigest()
        except Exception:
            evidence_hash = hashlib.sha256(rel_path.encode()).hexdigest()

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
