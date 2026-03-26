import logging
from typing import Any, Dict, List

logger = logging.getLogger("orchestrator.services.notice_policy")

class NoticePolicyService:
    @classmethod
    def evaluate_all(cls, context_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        notices = []
        
        ctx_pct = context_state.get("context_percentage")
        if isinstance(ctx_pct, (int, float)) and ctx_pct > 70.0:
            notices.append({
                "level": "warning",
                "code": "ctx_high",
                "message": f"Context usage is high ({float(ctx_pct)}%)"
            })
            
        budget_pct = context_state.get("budget_percentage")
        if not isinstance(budget_pct, (int, float)):
            spend = context_state.get("budget_spend")
            limit = context_state.get("budget_limit")
            if isinstance(spend, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
                budget_pct = (float(spend) / float(limit)) * 100.0
            else:
                budget_pct = None
                
        if budget_pct is not None and budget_pct > 80.0:
            notices.append({
                "level": "warning",
                "code": "budget_high",
                "message": f"Budget usage is near limit ({float(budget_pct):.1f}%)"
            })
            
        if context_state.get("new_version_available") is True:
            notices.append({"level": "info", "code": "new_version", "message": "New version available"})
            
        if context_state.get("stream_down") is True:
            notices.append({"level": "error", "code": "stream_down", "message": "Stream is down"})
            
        if context_state.get("purge_failed") is True:
            notices.append({"level": "error", "code": "purge_failed", "message": "Purge failed"})
            
        if context_state.get("merge_base_drift") is True:
            notices.append({"level": "warning", "code": "merge_base_drift", "message": "Merge base drift detected"})

        if context_state.get("active_run_status") == "AWAITING_MERGE":
            run_id = context_state.get("active_run_id", "?")
            notices.append({
                "level": "info",
                "code": "awaiting_merge",
                "message": f"Run {run_id} is AWAITING_MERGE. Use /merge to finalize."
            })

        return notices
