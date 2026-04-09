import hashlib
import logging
from pathlib import PurePosixPath
from typing import Dict, Any, List, Optional
from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.services.model_router_service import ModelRouterService
from tools.gimo_server.services.providers.service import ProviderService

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
        cls._reject_surface_topology_overrides(payload)

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
        evidence_paths: List[str] = []
        evidence_path_set: set[str] = set()
        evidence_base_commits: set[str] = set()
        evidence_parts = []
        for p in sorted_proofs:
            # P5C-DELTA: Harden validation to ensure no missing or whitespace-only fields.
            # Every proof must be valid to be used in the task spec.
            required_fields = ["artifact_handle", "kind", "evidence_hash", "base_commit"]
            for field in required_fields:
                val = p.get(field)
                if val is None or not str(val).strip():
                    raise ValueError(f"Draft creation rejected: Evidence record is invalid. Field '{field}' is missing or empty in proof.")

            proof_kind = str(p.get("kind")).strip()
            if proof_kind != "read":
                raise ValueError("Draft creation rejected: Evidence record kind must be 'read'.")
            evidence_base_commits.add(str(p.get("base_commit")).strip())
            rel_path = cls._get_path_from_handle(session, str(p.get("artifact_handle", "")))
            if not rel_path:
                raise ValueError("Draft creation rejected: Evidence record cannot be resolved to a reconnaissance artifact.")
            normalized_path = cls._normalize_allowed_path(rel_path)
            if normalized_path not in evidence_path_set:
                evidence_path_set.add(normalized_path)
                evidence_paths.append(normalized_path)

            # We use artifact_handle, kind, content_hash (evidence_hash), and base_commit.
            part = f"{p.get('artifact_handle')}:{p.get('kind')}:{p.get('evidence_hash')}:{p.get('base_commit')}"
            evidence_parts.append(part)
        evidence_content = "|".join(evidence_parts)
        if not evidence_content:
             # B2 Fail-Closed: Evidence set must contain content.
             raise ValueError("Draft validation failed: Reconnaissance evidence content is missing or empty.")
        if len(evidence_base_commits) != 1:
            raise ValueError("Draft creation rejected: Reconnaissance evidence spans multiple base commits.")
        evidence_hash = hashlib.sha256(evidence_content.encode("utf-8")).hexdigest()
        
        # 2. Preparation of Allowed Paths (never wildcard by default)
        raw_allowed_paths = payload.get("allowed_paths", [])
        if not evidence_paths:
            raise ValueError("Draft creation rejected: No readable reconnaissance artifacts were recorded.")

        if raw_allowed_paths:
            requested_allowed_paths = {
                cls._normalize_allowed_path(path)
                for path in raw_allowed_paths
                if path is not None and str(path).strip()
            }
            if not requested_allowed_paths:
                raise ValueError("Draft creation rejected: allowed_paths must contain at least one valid repository path.")
            invalid_paths = sorted(path for path in requested_allowed_paths if path not in evidence_path_set)
            if invalid_paths:
                raise ValueError(
                    "Draft creation rejected: allowed_paths must be drawn from reconnaissance reads only."
                )
            allowed_paths = [path for path in evidence_paths if path in requested_allowed_paths]
        else:
            allowed_paths = evidence_paths.copy()

        # 3. Acceptance Criteria (mandatory)
        acceptance_criteria = payload.get("acceptance_criteria")
        if not acceptance_criteria:
            raise ValueError("acceptance_criteria is mandatory for ValidatedTaskSpec.")
            
        # 4. Generate ValidatedTaskSpec (Mandatory 5A contract)
        # base_commit from the latest read proof or session
        base_commit = next(iter(evidence_base_commits))
        
        worker_model = cls._resolve_backend_worker_model()

        validated_task_spec = {
            "base_commit": base_commit,
            "repo_handle": repo_handle,
            "allowed_paths": allowed_paths,
            "acceptance_criteria": acceptance_criteria,
            "evidence_hash": evidence_hash,
            "context_pack_id": f"ctx_{session_id[:8]}_{evidence_hash[:8]}", # Opaque handle
            "worker_model": worker_model,
            "requires_manual_merge": True # Hard rule 5A
        }
        
        # 5. Generate RepoContextPack
        repo_context_pack = {
            "id": validated_task_spec["context_pack_id"],
            "session_id": session_id,
            "repo_handle": repo_handle,
            "base_commit": base_commit,
            "read_proofs": sorted_proofs,
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
    def _reject_surface_topology_overrides(cls, payload: Dict[str, Any]) -> None:
        forbidden_keys = (
            "worker_model",
            "worker_provider",
            "orchestrator_model",
            "orchestrator_provider",
            "provider_type",
            "model_id",
            "roles",
        )
        present = [key for key in forbidden_keys if str(payload.get(key) or "").strip()]
        if present:
            raise ValueError(
                "Draft creation rejected: App surface cannot override provider/model topology."
            )

    @classmethod
    def _resolve_backend_worker_model(cls) -> str:
        cfg = ProviderService.get_config()
        if cfg:
            _provider_id, requested_model = ModelRouterService.resolve_tier_routing("worker", cfg)
            if requested_model:
                return requested_model

            _provider_id, requested_model = ModelRouterService.resolve_tier_routing("analysis", cfg)
            if requested_model:
                return requested_model

            if cfg.model_id:
                return str(cfg.model_id).strip()

            entry = cfg.providers.get(cfg.active)
            if entry:
                resolved = entry.configured_model_id()
                if resolved:
                    return resolved

        return "gpt-4o"

    @classmethod
    def _get_path_from_handle(cls, session: Dict[str, Any], handle: str) -> Optional[str]:
        mapping = session.get("recon_handles", {})
        return mapping.get(handle)

    @classmethod
    def _normalize_allowed_path(cls, raw_path: str) -> str:
        path = str(raw_path or "").replace("\\", "/").strip()
        if not path or path == "*" or path == ".":
            raise ValueError("Draft creation rejected: allowed_paths must contain explicit repository-relative paths.")
        normalized = PurePosixPath(path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Draft creation rejected: allowed_paths cannot escape repository bounds.")
        cleaned = PurePosixPath(*[part for part in normalized.parts if part not in ("", ".")]).as_posix()
        if not cleaned:
            raise ValueError("Draft creation rejected: allowed_paths must contain explicit repository-relative paths.")
        return cleaned
