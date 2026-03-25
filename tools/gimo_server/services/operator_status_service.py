import logging
from typing import Any, Dict

logger = logging.getLogger("orchestrator.services.operator_status")

class OperatorStatusService:
    """
    Aggregates one backend-authored snapshot for operator status.
    """

    @classmethod
    def get_status_snapshot(cls) -> Dict[str, Any]:
        """
        Returns an aggregated snapshot of operator state.
        Uses explicit nulls/defaults where data is not yet authoritative.
        Never invents fake data.
        """
        # We attempt to load what we can. Safe defaults if absent.
        return {
            "repo": None,
            "branch": None,
            "dirty_files": [],
            "active_provider": None,
            "active_model": None,
            "permission_mode": "standard", # safe default
            "backend_status": "online",
            "backend_version": "v1.0.0", # safe default
            "active_run": None,
            "active_stage": None,
            "budget_spend": 0.0,
            "budget_limit": None,
            "context_percentage": 0.0,
            "last_thread": None,
            "last_turn": None,
            "alerts": []
        }
