from __future__ import annotations

from tools.gimo_server.schemas.draft_validation import DraftCreateRequest, DraftValidationResponse
from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.services.draft_validation_service import DraftValidationService
from tools.gimo_server.services.ops import OpsService
from tools.gimo_server.services.workspace.workspace_policy_service import WorkspacePolicyService


class AppDraftSessionNotFoundError(LookupError):
    """Raised when an App draft is requested for a session that does not exist."""


class AppDraftService:
    """Canonical backend operation for validated App draft creation."""

    _OPERATOR_CLASS = "cognitive_agent"

    @classmethod
    def create_validated_draft(
        cls,
        session_id: str,
        payload: DraftCreateRequest | dict[str, object],
    ) -> DraftValidationResponse:
        session = AppSessionService.get_session(session_id)
        if session is None:
            raise AppDraftSessionNotFoundError("Session not found")

        payload_dict = payload if isinstance(payload, dict) else payload.model_dump()
        result = DraftValidationService.validate_draft(session_id, payload_dict)
        validated_task_spec = result["validated_task_spec"]
        repo_context_pack = result["repo_context_pack"]
        prompt = cls._build_prompt(validated_task_spec)
        draft = OpsService.create_draft(
            prompt=prompt,
            content=prompt,
            context={
                "validated_task_spec": validated_task_spec,
                "repo_context_pack": repo_context_pack,
                "repo_context": {"repo_id": validated_task_spec.get("repo_handle")},
                "execution_decision": "MANUAL_REVIEW_REQUIRED",
                "intent_effective": "CODE_CHANGE",
                "commit_base": validated_task_spec.get("base_commit"),
                "operator_class": cls._OPERATOR_CLASS,
                "surface": WorkspacePolicyService.SURFACE_CHATGPT_APP,
                "workspace_mode": WorkspacePolicyService.MODE_EPHEMERAL,
            },
            operator_class=cls._OPERATOR_CLASS,
        )
        return DraftValidationResponse(
            draft_id=draft.id,
            validated_task_spec=validated_task_spec,
            repo_context_pack=repo_context_pack,
        )

    @staticmethod
    def _build_prompt(validated_task_spec: dict[str, object]) -> str:
        allowed_paths = [
            str(path).strip()
            for path in validated_task_spec.get("allowed_paths", [])
            if str(path).strip()
        ]
        acceptance_criteria = str(validated_task_spec.get("acceptance_criteria") or "").strip()
        return (
            "Implement the validated task strictly within the approved repository scope.\n\n"
            f"Acceptance criteria:\n{acceptance_criteria}\n\n"
            f"Allowed paths:\n" + "\n".join(f"- {path}" for path in allowed_paths)
        )
