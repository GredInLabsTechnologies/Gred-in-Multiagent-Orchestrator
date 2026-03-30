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

        orchestrator = cfg.primary_orchestrator_binding() if hasattr(cfg, "primary_orchestrator_binding") else None
        if orchestrator:
            return orchestrator.provider_id, orchestrator.model

        active_provider = getattr(cfg, "active", None)
        providers = getattr(cfg, "providers", None) or {}
        active_entry = providers.get(active_provider) if active_provider else None
        active_model = active_entry.configured_model_id() if active_entry else getattr(cfg, "model_id", None)
        return active_provider, active_model

    @classmethod
    def _thread_snapshot(
        cls,
    ) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None, float | None]:
        threads = ConversationService.list_threads()
        if not threads:
            return None, None, None, None, None, None, None

        thread = threads[0]
        metadata = thread.metadata if isinstance(thread.metadata, dict) else {}
        last_turn_id = thread.turns[-1].id if thread.turns else None
        permissions = metadata.get("permissions")
        effort = metadata.get("effort")
        workspace_mode = metadata.get("workspace_mode")
        orchestrator_authority = metadata.get("orchestrator_authority")

        ctx_pct = None
        usage = metadata.get("usage")
        if isinstance(usage, dict):
            used = usage.get("total_tokens")
            limit = usage.get("max_context_tokens")
            if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
                ctx_pct = min(100.0, (float(used) / float(limit)) * 100.0)

        return thread.id, last_turn_id, permissions, effort, workspace_mode, orchestrator_authority, ctx_pct

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
        """Return the canonical backend-authored operator status snapshot.

        Defensive: each subsnapshot is wrapped in try/except to prevent 500 errors
        if any single component fails. Returns partial snapshot on failure.
        """
        # Base snapshot (always present)
        snapshot: dict[str, Any] = {
            "backend_status": "ok",
            "backend_version": __version__,
        }

        # Git snapshot (optional, fail-safe)
        try:
            repo_root = cls._repo_root()
            branch = GitService.get_current_branch(repo_root)
            dirty_files = GitService.get_changed_files(repo_root)
            snapshot["repo"] = repo_root.name if repo_root.exists() else None
            snapshot["branch"] = branch
            snapshot["dirty_files"] = dirty_files
        except Exception:
            logger.warning("Failed to get git snapshot", exc_info=True)

        # Provider snapshot (optional, fail-safe)
        try:
            active_provider, active_model = cls._provider_snapshot()
            snapshot["active_provider"] = active_provider
            snapshot["active_model"] = active_model
        except Exception:
            logger.warning("Failed to get provider snapshot", exc_info=True)

        # Thread snapshot (optional, fail-safe)
        try:
            (
                last_thread_id,
                last_turn_id,
                permissions,
                effort,
                workspace_mode,
                orchestrator_authority,
                context_percentage,
            ) = cls._thread_snapshot()
            if permissions is not None:
                snapshot["permissions"] = permissions
            if effort is not None:
                snapshot["effort"] = effort
            if workspace_mode is not None:
                snapshot["workspace_mode"] = workspace_mode
            if orchestrator_authority is not None:
                snapshot["orchestrator_authority"] = orchestrator_authority
            if last_thread_id is not None:
                snapshot["last_thread"] = last_thread_id
            if last_turn_id is not None:
                snapshot["last_turn"] = last_turn_id
            if context_percentage is not None:
                snapshot["context_percentage"] = context_percentage
                snapshot["context_status"] = f"{int(context_percentage)}%"
        except Exception:
            logger.warning("Failed to get thread snapshot", exc_info=True)

        # Run snapshot (optional, fail-safe)
        try:
            active_run_id, active_run_status, active_run_stage = cls._active_run_snapshot()
            if active_run_id is not None:
                snapshot["active_run_id"] = active_run_id
                snapshot["active_run_status"] = active_run_status
            if active_run_stage is not None:
                snapshot["active_run_stage"] = active_run_stage
        except Exception:
            logger.warning("Failed to get run snapshot", exc_info=True)

        # Budget snapshot (optional, fail-safe)
        try:
            budget_percentage, budget_status, budget_spend, budget_limit = cls._budget_snapshot()
            if budget_percentage is not None:
                snapshot["budget_percentage"] = budget_percentage
                snapshot["budget_status"] = budget_status
            if budget_spend is not None:
                snapshot["budget_spend"] = budget_spend
            if budget_limit is not None:
                snapshot["budget_limit"] = budget_limit
        except Exception:
            logger.warning("Failed to get budget snapshot", exc_info=True)

        # Alerts (optional, fail-safe)
        try:
            snapshot["alerts"] = NoticePolicyService.evaluate_all(snapshot)
        except Exception:
            logger.warning("Failed to evaluate alerts", exc_info=True)
            snapshot["alerts"] = []

        return snapshot
