from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..version import __version__
from .budget_forecast_service import BudgetForecastService
from .conversation_service import ConversationService
from .git_service import GitService
from .notice_policy_service import NoticePolicyService
from .ops_service import OpsService
from .provider_service_impl import ProviderService
from .storage_service import StorageService

logger = logging.getLogger("orchestrator.services.operator_status")


class OperatorStatusService:
    _TERMINAL_RUN_STATUSES = {"done", "error", "cancelled"}

    @classmethod
    def _repo_root(cls) -> Path:
        settings = get_settings()
        return Path(settings.repo_root_dir)

    @classmethod
    def _provider_snapshot(cls) -> tuple[str | None, str | None]:
        cfg = ProviderService.get_config()
        if not cfg:
            return None, None

        roles = getattr(cfg, "roles", None)
        orchestrator = getattr(roles, "orchestrator", None) if roles else None
        if orchestrator:
            return orchestrator.provider_id, orchestrator.model
        return getattr(cfg, "orchestrator_provider", None) or getattr(cfg, "active", None), getattr(
            cfg,
            "orchestrator_model",
            None,
        ) or getattr(cfg, "model_id", None)

    @classmethod
    def _thread_snapshot(cls) -> tuple[str | None, str | None, str | None, str | None, float | None]:
        threads = ConversationService.list_threads()
        if not threads:
            return None, None, None, None, None

        thread = threads[0]
        metadata = thread.metadata if isinstance(thread.metadata, dict) else {}
        last_turn_id = thread.turns[-1].id if thread.turns else None
        permissions = metadata.get("permissions")
        effort = metadata.get("effort")

        ctx_pct = None
        usage = metadata.get("usage")
        if isinstance(usage, dict):
            used = usage.get("total_tokens")
            limit = usage.get("max_context_tokens")
            if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
                ctx_pct = min(100.0, (float(used) / float(limit)) * 100.0)

        return thread.id, last_turn_id, permissions, effort, ctx_pct

    @classmethod
    def _active_run_snapshot(cls) -> tuple[str | None, str | None, str | None]:
        for run in OpsService.list_runs():
            status = str(run.status or "")
            if status in cls._TERMINAL_RUN_STATUSES:
                continue
            return run.id, status, getattr(run, "stage", None)
        return None, None, None

    @classmethod
    def _budget_snapshot(cls) -> tuple[float | None, str | None, float | None, float | None]:
        try:
            ops_cfg = OpsService.get_config()
            forecast = BudgetForecastService(storage=StorageService())._calculate_forecast(
                "global",
                ops_cfg.economy.global_budget_usd,
                ops_cfg.economy.alert_thresholds,
            )
        except Exception:
            logger.exception("Failed to compute budget snapshot")
            return None, None, None, None

        if not forecast:
            return None, None, None, None

        remaining_pct = float(forecast.remaining_pct)
        budget_limit = float(forecast.limit)
        budget_spend = max(0.0, float(forecast.current_spend))
        return remaining_pct, ("ok" if remaining_pct > 20.0 else "low"), budget_spend, budget_limit

    @classmethod
    def get_status_snapshot(cls) -> dict[str, Any]:
        """Return the canonical backend-authored operator status snapshot."""
        repo_root = cls._repo_root()
        branch = GitService.get_current_branch(repo_root)
        dirty_files = GitService.get_changed_files(repo_root)

        active_provider, active_model = cls._provider_snapshot()
        last_thread_id, last_turn_id, permissions, effort, context_percentage = cls._thread_snapshot()
        active_run_id, active_run_status, active_run_stage = cls._active_run_snapshot()
        budget_percentage, budget_status, budget_spend, budget_limit = cls._budget_snapshot()

        snapshot: dict[str, Any] = {
            "repo": repo_root.name if repo_root.exists() else None,
            "branch": branch,
            "dirty_files": dirty_files,
            "active_provider": active_provider,
            "active_model": active_model,
            "backend_status": "ok",
            "backend_version": __version__,
        }

        if permissions is not None:
            snapshot["permissions"] = permissions
        if effort is not None:
            snapshot["effort"] = effort
        if last_thread_id is not None:
            snapshot["last_thread"] = last_thread_id
        if last_turn_id is not None:
            snapshot["last_turn"] = last_turn_id
        if context_percentage is not None:
            snapshot["context_percentage"] = context_percentage
            snapshot["context_status"] = f"{int(context_percentage)}%"
        if active_run_id is not None:
            snapshot["active_run_id"] = active_run_id
            snapshot["active_run_status"] = active_run_status
        if active_run_stage is not None:
            snapshot["active_run_stage"] = active_run_stage
        if budget_percentage is not None:
            snapshot["budget_percentage"] = budget_percentage
            snapshot["budget_status"] = budget_status
        if budget_spend is not None:
            snapshot["budget_spend"] = budget_spend
        if budget_limit is not None:
            snapshot["budget_limit"] = budget_limit

        snapshot["alerts"] = NoticePolicyService.evaluate_all(snapshot)
        return snapshot
