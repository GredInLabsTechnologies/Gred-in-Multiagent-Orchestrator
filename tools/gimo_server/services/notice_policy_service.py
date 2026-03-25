import logging
from typing import Any, Dict, List

logger = logging.getLogger("orchestrator.services.notice_policy")

class NoticePolicyService:
    @classmethod
    def evaluate_all(cls, context_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        notices = []
        
        ctx_val = context_state.get("context_percentage")
        ctx_pct = 0.0
        if isinstance(ctx_val, (int, float)):
            ctx_pct = float(ctx_val)
            
        if ctx_pct > 70.0:
            notices.append({
                "level": "warning",
                "code": "ctx_high",
                "message": f"Context usage is high ({ctx_pct}%)"
            })
            
        budget_pct = context_state.get("budget_percentage")
        if not isinstance(budget_pct, (int, float)):
            spend = context_state.get("budget_spend")
            limit = context_state.get("budget_limit")
            if isinstance(spend, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
                budget_pct = (float(spend) / float(limit)) * 100.0
            else:
                budget_pct = 0.0
                
        if budget_pct > 80.0:
            notices.append({
                "level": "warning",
                "code": "budget_high",
                "message": f"Budget usage is near limit ({round(budget_pct, 1)}%)"
            })
            
        if context_state.get("new_version_available"):
            notices.append({"level": "info", "code": "new_version", "message": "New version available"})
            
        if context_state.get("stream_down"):
            notices.append({"level": "error", "code": "stream_down", "message": "Stream is down"})
            
        if context_state.get("purge_failed"):
            notices.append({"level": "error", "code": "purge_failed", "message": "Purge failed"})
            
        if context_state.get("merge_base_drift"):
            notices.append({"level": "warning", "code": "merge_base_drift", "message": "Merge base drift detected"})

        return notices
