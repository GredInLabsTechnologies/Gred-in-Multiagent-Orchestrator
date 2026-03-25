import logging
from typing import Any, Dict, Optional
from ..ops_models import GimoThread
from .conversation_service import ConversationService

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
            if "effort" in config_data:
                thread.metadata["effort"] = config_data["effort"]
            if "permissions" in config_data:
                thread.metadata["permissions"] = config_data["permissions"]
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
