import logging
from typing import Any, Dict, List

logger = logging.getLogger("orchestrator.services.notice_policy")

class NoticePolicyService:
    """
    Evaluates policy rules to produce backend notice objects.
    Produces reusable rule evaluations without hardcoding client UI concepts.
    """
    
    @classmethod
    def evaluate_all(cls, context_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Evaluates current system state against policy rules.
        """
        notices = []
        
        # warning: ctx > 70%
        ctx_pct = context_state.get("context_percentage", 0.0)
        if ctx_pct > 70.0:
            notices.append({
                "level": "warning",
                "code": "ctx_high",
                "message": f"Context usage is high ({ctx_pct}%)"
            })
            
        # warning: budget > 80%
        budget_pct = context_state.get("budget_percentage", 0.0)
        if budget_pct > 80.0:
            notices.append({
                "level": "warning",
                "code": "budget_high",
                "message": f"Budget usage is near limit ({budget_pct}%)"
            })
            
        # Optional dummy evaluations for the remaining contract points which will be emitted
        # when their state triggers actually exist in context_state.
        
        if context_state.get("new_version_available"):
            notices.append({"level": "info", "code": "new_version", "message": "New version available"})
            
        if context_state.get("stream_down"):
            notices.append({"level": "error", "code": "stream_down", "message": "Stream is down"})
            
        if context_state.get("purge_failed"):
            notices.append({"level": "error", "code": "purge_failed", "message": "Purge failed"})
            
        if context_state.get("merge_base_drift"):
            notices.append({"level": "warning", "code": "merge_base_drift", "message": "Merge base drift detected"})

        return notices
