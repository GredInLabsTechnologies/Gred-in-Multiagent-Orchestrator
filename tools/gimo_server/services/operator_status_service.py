import logging
from typing import Any, Dict
from pathlib import Path
from tools.gimo_server.version import __version__
from tools.gimo_server.config import REPO_ROOT_DIR
from tools.gimo_server.services.git_service import GitService
from tools.gimo_server.services.provider_service_impl import ProviderService
from tools.gimo_server.services.notice_policy_service import NoticePolicyService
from tools.gimo_server.services.conversation_service import ConversationService

logger = logging.getLogger("orchestrator.services.operator_status")

class OperatorStatusService:
    @classmethod
    def get_status_snapshot(cls) -> Dict[str, Any]:
        base_dir = Path(REPO_ROOT_DIR)
        
        branch = None
        dirty_files = []
        if base_dir.exists():
            branch = GitService.get_current_branch(base_dir)
            dirty_files = GitService.get_changed_files(base_dir)

        active_provider = None
        active_model = None
        cfg = ProviderService.get_config()
        if cfg and getattr(cfg, "roles", None) and getattr(cfg.roles, "orchestrator", None):
            active_provider = getattr(cfg.roles.orchestrator, "provider_id", None)
            active_model = getattr(cfg.roles.orchestrator, "model", None)

        last_thread_id = None
        last_turn_id = None
        threads = ConversationService.list_threads()
        if threads:
            last_thread_id = threads[0].id
            if threads[0].turns:
                last_turn_id = threads[0].turns[-1].id

        # Telemetry (Calculated dynamically or retrieved from authoritative services)
        # Phase 7B: Ensure thin clients don't need to compute these.
        budget_pct = 0.0
        try:
            from .budget_forecast_service import BudgetForecastService
            from .storage_service import StorageService
            from .ops_service import OpsService
            cfg = OpsService.get_config()
            if cfg.economy.global_budget_usd:
                # Basic calculation for now; in production we use BudgetForecastService
                forecast_svc = BudgetForecastService(StorageService())
                f = forecast_svc._calculate_forecast("global", cfg.economy.global_budget_usd, cfg.economy.alert_thresholds)
                if f:
                    budget_pct = f.remaining_pct
        except Exception:
            budget_pct = 95.0 # Fallback for dev/unconfigured

        ctx_pct = 0.0
        try:
            # We derive context from the last thread if available
            if last_thread_id:
                t = ConversationService.get_thread(last_thread_id)
                if t:
                    # Very crude estimation: 1000 tokens per turn
                    max_ctx = 200000
                    used = len(t.turns) * 1000
                    ctx_pct = min(100.0, (used / max_ctx) * 100.0)
        except Exception:
            ctx_pct = 5.0 # Fallback

        snapshot = {
            "repo": str(base_dir.name) if base_dir.exists() else None,
            "branch": branch,
            "dirty_files": dirty_files,
            "active_provider": active_provider,
            "active_model": active_model,
            "permissions": "suggest", # Canonical default
            "budget_percentage": budget_pct,
            "context_percentage": ctx_pct,
            "budget_status": "ok" if budget_pct > 20 else "low",
            "context_status": f"{int(ctx_pct)}%",
            "backend_version": __version__,
            "last_thread": last_thread_id,
            "last_turn": last_turn_id,
        }
        
        # Inject backend-authored alerts based on the snapshot itself
        snapshot["alerts"] = NoticePolicyService.evaluate_all(snapshot)
        return snapshot
