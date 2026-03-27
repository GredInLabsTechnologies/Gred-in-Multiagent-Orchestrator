import logging
from typing import Any, Dict, Optional
from ..ops_models import GimoThread
from .conversation_service import ConversationService
from .workspace_policy_service import WorkspacePolicyService

logger = logging.getLogger("orchestrator.services.thread_session")

class ThreadSessionService:
    @classmethod
    def reset_thread(cls, thread_id: str) -> bool:
        def _mutate(thread: GimoThread) -> bool:
            thread.metadata["context"] = []
            thread.metadata["attached_files"] = []
            return True
        return bool(ConversationService.mutate_thread(thread_id, _mutate))

    @classmethod
    def update_config(cls, thread_id: str, config_data: Dict[str, Any]) -> bool:
        def _mutate(thread: GimoThread) -> bool:
            backend_controlled = {
                "surface",
                "orchestrator_authority",
                "orchestrator_selection_allowed",
                "worker_model_selection_allowed",
            }
            if backend_controlled.intersection(config_data):
                raise ValueError(
                    "surface, orchestrator_authority, and surface selection authority are backend-controlled and cannot be overridden"
                )
            if "effort" in config_data:
                thread.metadata["effort"] = config_data["effort"]
            if "permissions" in config_data:
                thread.metadata["permissions"] = config_data["permissions"]
            if "workspace_mode" in config_data:
                surface = str(thread.metadata.get("surface") or WorkspacePolicyService.SURFACE_OPERATOR)
                thread.metadata["workspace_mode"] = WorkspacePolicyService.resolve_effective_mode(
                    requested_mode=str(config_data["workspace_mode"]),
                    surface=surface,
                )
            return True
        return bool(ConversationService.mutate_thread(thread_id, _mutate))

    @classmethod
    def add_context(cls, thread_id: str, context_data: Dict[str, Any]) -> bool:
        def _mutate(thread: GimoThread) -> bool:
            ctx = thread.metadata.get("context", [])
            if not isinstance(ctx, list): ctx = []
            ctx.append(context_data)
            thread.metadata["context"] = ctx

            if context_data.get("type") == "file" or "path" in context_data or "file" in context_data:
                attached = thread.metadata.get("attached_files", [])
                if not isinstance(attached, list): attached = []
                attached.append(context_data)
                thread.metadata["attached_files"] = attached
                
            return True
        return bool(ConversationService.mutate_thread(thread_id, _mutate))

    @classmethod
    def get_usage(cls, thread_id: str) -> Optional[Dict[str, Any]]:
        thread = ConversationService.get_thread(thread_id)
        if not thread:
            return None
        usage = thread.metadata.get("usage")
        if usage is None:
            return {}
        return usage
