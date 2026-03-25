import hashlib
import logging
from typing import Dict, Any, List, Optional
from tools.gimo_server.services.app_session_service import AppSessionService

logger = logging.getLogger("orchestrator.services.draft_validation")

class DraftValidationService:
    """
    P5.2 DraftValidationService: Validation based on recon evidence.
    Produces RepoContextPack and ValidatedTaskSpec.
    Ensures that every draft creation is backed by real recon evidence.
    """

    @classmethod
    def validate_draft(cls, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates a draft creation request using recorded ReadProofs.
        """
        session = AppSessionService.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
            
        read_proofs = session.get("read_proofs", [])
        if not read_proofs:
            # 5A: No ValidatedTaskSpec without evidence.
            raise ValueError("Draft creation rejected: No reconnaissance evidence recorded. Recon is mandatory.")
            
        repo_handle = session.get("repo_id")
        if not repo_handle:
            raise ValueError("Session has no repository selected.")
            
        # 1. Extraction of evidence hash (deterministic representation of recon state)
        # B2: Deterministic hash built from real evidence content, using stable ordering.
        # We use artifact_handle and kind for a stable, unique sort key.
        sorted_proofs = sorted(read_proofs, key=lambda p: (str(p.get("artifact_handle", "")), str(p.get("kind", ""))))
        evidence_parts = []
        for p in sorted_proofs:
            # P5C-DELTA: Harden validation to ensure no missing or whitespace-only fields.
            # Every proof must be valid to be used in the task spec.
            required_fields = ["artifact_handle", "kind", "evidence_hash", "base_commit"]
            for field in required_fields:
                val = p.get(field)
                if val is None or not str(val).strip():
                    raise ValueError(f"Draft creation rejected: Evidence record is invalid. Field '{field}' is missing or empty in proof.")
            
            # We use artifact_handle, kind, content_hash (evidence_hash), and base_commit.
            part = f"{p.get('artifact_handle')}:{p.get('kind')}:{p.get('evidence_hash')}:{p.get('base_commit')}"
            evidence_parts.append(part)
        evidence_content = "|".join(evidence_parts)
        if not evidence_content:
             # B2 Fail-Closed: Evidence set must contain content.
             raise ValueError("Draft validation failed: Reconnaissance evidence content is missing or empty.")
        evidence_hash = hashlib.sha256(evidence_content.encode("utf-8")).hexdigest()
        
        # 2. Preparation of Allowed Paths (never wildcard by default)
        raw_allowed_paths = payload.get("allowed_paths", [])
        if not raw_allowed_paths:
            # P5C-DELTA: Fallback to extraction from read_proofs in deterministic order.
            # We use the same stable order as the evidence hash for fallback consistency.
            seen = set()
            raw_allowed_paths = []
            for p in sorted_proofs:
                if p.get("kind") == "read":
                    path = cls._get_path_from_handle(session, p.get("artifact_handle", ""))
                    if path and path not in seen:
                        seen.add(path)
                        raw_allowed_paths.append(path)
            
        allowed_paths = [str(p).replace("\\", "/") for p in raw_allowed_paths if p]
        
        # 3. Acceptance Criteria (mandatory)
        acceptance_criteria = payload.get("acceptance_criteria")
        if not acceptance_criteria:
            raise ValueError("acceptance_criteria is mandatory for ValidatedTaskSpec.")
            
        # 4. Generate ValidatedTaskSpec (Mandatory 5A contract)
        # base_commit from the latest read proof or session
        latest_proof = read_proofs[-1]
        base_commit = latest_proof.get("base_commit", "HEAD")
        
        validated_task_spec = {
            "base_commit": base_commit,
            "repo_handle": repo_handle,
            "allowed_paths": allowed_paths,
            "acceptance_criteria": acceptance_criteria,
            "evidence_hash": evidence_hash,
            "context_pack_id": f"ctx_{session_id[:8]}_{evidence_hash[:8]}", # Opaque handle
            "worker_model": payload.get("worker_model", "gpt-4o"), # Default worker model
            "requires_manual_merge": True # Hard rule 5A
        }
        
        # 5. Generate RepoContextPack
        repo_context_pack = {
            "id": validated_task_spec["context_pack_id"],
            "session_id": session_id,
            "repo_handle": repo_handle,
            "base_commit": base_commit,
            "read_proofs": read_proofs,
            "allowed_paths": allowed_paths
        }
        
        # Persistent storage of context pack in session if needed
        if "context_packs" not in session:
            session["context_packs"] = {}
        session["context_packs"][repo_context_pack["id"]] = repo_context_pack
        AppSessionService._save_session(session_id, session)
        
        return {
            "validated_task_spec": validated_task_spec,
            "repo_context_pack": repo_context_pack
        }

    @classmethod
    def _get_path_from_handle(cls, session: Dict[str, Any], handle: str) -> Optional[str]:
        mapping = session.get("recon_handles", {})
        return mapping.get(handle)
