import logging
from typing import Any, Dict, Optional
from ..ops_models import GimoThread
from .conversation_service import ConversationService

logger = logging.getLogger("orchestrator.services.thread_session")

class ThreadSessionService:
    """
    Centralizes thread/session state operations:
    - reset context without destroying thread identity
    - update session configuration (effort, permissions)
    - add context references
    - retrieve usage snapshots
    """

    @classmethod
    def reset_thread(cls, thread_id: str) -> bool:
        """Clears thread context (metadata context keys) but preserves identity."""
        def _mutate(thread: GimoThread) -> bool:
            if "context" in thread.metadata:
                thread.metadata["context"] = []
            if "attached_files" in thread.metadata:
                thread.metadata["attached_files"] = []
            return True
        
        result = ConversationService.mutate_thread(thread_id, _mutate)
        return bool(result)

    @classmethod
    def update_config(cls, thread_id: str, config_data: Dict[str, Any]) -> bool:
        """Updates session effort and permission modes."""
        def _mutate(thread: GimoThread) -> bool:
            if "effort" in config_data:
                thread.metadata["effort"] = config_data["effort"]
            if "permissions" in config_data:
                thread.metadata["permissions"] = config_data["permissions"]
            return True
        
        result = ConversationService.mutate_thread(thread_id, _mutate)
        return bool(result)

    @classmethod
    def add_context(cls, thread_id: str, context_data: Dict[str, Any]) -> bool:
        """Appends a context item or file reference to the thread's active context."""
        def _mutate(thread: GimoThread) -> bool:
            ctx = thread.metadata.get("context", [])
            if not isinstance(ctx, list):
                ctx = []
            ctx.append(context_data)
            thread.metadata["context"] = ctx
            return True
        
        result = ConversationService.mutate_thread(thread_id, _mutate)
        return bool(result)

    @classmethod
    def get_usage(cls, thread_id: str) -> Optional[Dict[str, Any]]:
        """Returns a snapshot of usage for the thread.
        Currently, threads do not natively store usage, so we return a default structure
        until the agentic loop aggregates it persistently here.
        """
        thread = ConversationService.get_thread(thread_id)
        if not thread:
            return None
        return thread.metadata.get("usage", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0
        })
