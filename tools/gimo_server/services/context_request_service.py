import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from tools.gimo_server.services.app_session_service import AppSessionService

logger = logging.getLogger("orchestrator.services.context_request")

class ContextRequestService:
    """
    P5.3 ContextRequestService: Persistent contract for requesting additional context.
    Allows for structured pause/resume points before execution.
    """

    @classmethod
    def create_request(cls, session_id: str, description: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Creates a pending request for additional context or human-in-the-loop validation."""
        session = AppSessionService.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
            
        request_id = str(uuid.uuid4())
        request = {
            "id": request_id,
            "session_id": session_id,
            "description": description,
            "status": "pending",
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Store in session state
        if "context_requests" not in session:
            session["context_requests"] = {}
            
        session["context_requests"][request_id] = request
        AppSessionService._save_session(session_id, session)
        
        return request

    @classmethod
    def update_request_status(cls, session_id: str, request_id: str, status: str, result: Optional[str] = None) -> bool:
        """Updates the status of a context request."""
        session = AppSessionService.get_session(session_id)
        if not session or "context_requests" not in session:
            return False
            
        if request_id not in session["context_requests"]:
            return False
            
        req = session["context_requests"][request_id]
        req["status"] = status
        if result:
            req["result"] = result
        req["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        AppSessionService._save_session(session_id, session)
        return True

    @classmethod
    def list_requests(cls, session_id: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves context requests for a session, optionally filtered by status."""
        session = AppSessionService.get_session(session_id)
        if not session or "context_requests" not in session:
            return []
            
        requests = list(session["context_requests"].values())
        if status_filter:
            requests = [r for r in requests if r["status"] == status_filter]
            
        # Return sorted by creation date (newest first)
        return sorted(requests, key=lambda x: x["created_at"], reverse=True)

    @classmethod
    def resolve_request(cls, session_id: str, request_id: str, evidence: str) -> bool:
        """Marks a request as resolved with evidence."""
        return cls.update_request_status(session_id, request_id, "resolved", result=evidence)

    @classmethod
    def get_resolved_requests(cls, session_id: str) -> List[Dict[str, Any]]:
        """Returns all resolved requests that haven't been archived yet."""
        return cls.list_requests(session_id, "resolved")

    @classmethod
    def archive_resolved_requests(cls, session_id: str):
        """Moves resolved requests to archived status."""
        resolved = cls.get_resolved_requests(session_id)
        for r in resolved:
            cls.update_request_status(session_id, r["id"], "archived")

    @classmethod
    def get_request_history(cls, session_id: str) -> List[Dict[str, Any]]:
        """Returns all requests (active and archived) for the session."""
        return cls.list_requests(session_id)

    @classmethod
    def get_active_requests(cls, session_id: str) -> List[Dict[str, Any]]:
        """Returns pending or resolved requests."""
        all_reqs = cls.list_requests(session_id)
        return [r for r in all_reqs if r["status"] in ("pending", "resolved")]

    @classmethod
    def cancel_request(cls, session_id: str, request_id: str, reason: str) -> bool:
        """Cancels a context request."""
        return cls.update_request_status(session_id, request_id, "cancelled", result=reason)
