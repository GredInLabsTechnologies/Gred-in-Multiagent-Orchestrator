import logging
from typing import Any, Dict
from pathlib import Path
from ..version import __version__
from ..config import get_settings
from .git_service import GitService
from .provider_service_impl import ProviderServiceImpl
from .notice_policy_service import NoticePolicyService
from .conversation_service import ConversationService
from .storage_service import StorageService
from .ops_service import OpsService
from .budget_forecast_service import BudgetForecastService

logger = logging.getLogger("orchestrator.services.operator_status")

class OperatorStatusService:
    @classmethod
    def get_status_snapshot(cls) -> Dict[str, Any]:
        """Provides a complete system status snapshot (Single Source of Truth)."""
        settings = get_settings()
        base_dir = Path(settings.workspace_root)
        
        # 1. Git State
        branch_res = GitService._run_git(base_dir, ["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_res[1].strip() if branch_res[0] == 0 else "unknown"
        dirty_files = len(GitService.get_changed_files(base_dir))
        
        # 2. Provider State
        ps = ProviderServiceImpl(storage=StorageService())
        active_provider = ps.get_active_provider_id()
        active_model = ps.get_active_model_id()
        
        # 3. Session & Permissions State
        last_thread_id = ConversationService.get_last_active_thread_id()
        last_turn_id = None
        permissions = "suggest"
        ctx_pct = None

        if last_thread_id:
            t = ConversationService.get_thread(last_thread_id)
            if t:
                last_turn_id = t.turns[-1].id if t.turns else None
                permissions = t.metadata.get("permissions") or "suggest"
                usage = t.metadata.get("usage")
                if isinstance(usage, dict):
                    used, limit = usage.get("total_tokens"), usage.get("max_context_tokens")
                    if used is not None and limit:
                        ctx_pct = min(100.0, (used / limit) * 100.0)

        # 4. Budget State
        budget_pct = 100.0
        try:
            forecast_svc = BudgetForecastService(storage=StorageService())
            ops_cfg = OpsService.get_config()
            f = forecast_svc._calculate_forecast("global", ops_cfg.economy.global_budget_usd, ops_cfg.economy.alert_thresholds)
            if f: budget_pct = f.remaining_pct
        except Exception:
            pass

        # 5. Snapshot Finalization
        snapshot = {
            "repo": str(base_dir.name) if base_dir.exists() else None,
            "branch": branch,
            "dirty_files": dirty_files,
            "active_provider": active_provider,
            "active_model": active_model,
            "permissions": permissions,
            "budget_percentage": budget_pct,
            "context_percentage": ctx_pct,
            "budget_status": "ok" if (budget_pct and budget_pct > 20) else (None if budget_pct is None else "low"),
            "context_status": f"{int(ctx_pct)}%" if ctx_pct is not None else None,
            "backend_version": __version__,
            "last_thread": last_thread_id,
            "last_turn": last_turn_id,
        }
        
        snapshot["alerts"] = NoticePolicyService.evaluate_all(snapshot)
        return snapshot
