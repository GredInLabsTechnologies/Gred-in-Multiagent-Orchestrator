"""Background worker that processes pending OPS runs.

The worker polls for runs in ``pending`` status and dispatches them
to the active LLM provider for execution.  It respects
``max_concurrent_runs`` from :class:`OpsConfig` and enforces a
per-run timeout.

Lifecycle is managed by the FastAPI lifespan in ``main.py``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...ops_models import ExecutorReport
from ..ops_service import OpsService
from ..provider_service import ProviderService
from ..notification_service import NotificationService
from ..critic_service import CriticService
from ..quality_service import QualityService
from ..app_session_service import AppSessionService
from ..repo_recon_service import RepoReconService

logger = logging.getLogger("orchestrator.run_worker")

# How often to poll for pending runs (seconds).
POLL_INTERVAL = 5


def _task_weight_for_run(run) -> "TaskWeight":
    """Infer ResourceGovernor TaskWeight from the run's approved/draft context."""
    from ..resource_governor import TaskWeight
    try:
        approved = OpsService.get_approved(run.approved_id) if getattr(run, "approved_id", None) else None
        draft = OpsService.get_draft(approved.draft_id) if approved and getattr(approved, "draft_id", None) else None
        ctx = dict((draft.context if draft and draft.context else {}) or {})
        intent = str(ctx.get("intent_effective") or "").upper()
        if intent in {"MERGE_REQUEST", "CORE_RUNTIME_CHANGE", "SECURITY_CHANGE"}:
            return TaskWeight.HEAVY
        if ctx.get("target_path") or ctx.get("target_file"):
            return TaskWeight.LIGHT
    except Exception:
        pass
    return TaskWeight.MEDIUM

# Default per-run timeout if nothing else configured.
DEFAULT_RUN_TIMEOUT = 300  # 5 min


class RunWorker:
    """Async background worker for OPS run execution."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running_ids: set[str] = set()
        self._wake_event = asyncio.Event()
        self._running = False

    async def start(self) -> None:
        await asyncio.sleep(0)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            self._running = True
            logger.info("RunWorker started")

    def notify(self) -> None:
        """Wake the worker immediately to process pending runs."""
        self._wake_event.set()

    async def stop(self) -> None:
        self._running = False
        self._wake_event.set()  # Wake up to exit cleanly
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            logger.info("RunWorker stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                pass
            self._wake_event.clear()
            if not self._running:
                break
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("RunWorker tick error")

    async def _tick(self) -> None:
        await asyncio.sleep(0)
        config = OpsService.get_config()
        max_concurrent = config.max_concurrent_runs

        # Clean finished IDs
        self._running_ids = {
            rid for rid in self._running_ids
            if self._is_still_active(rid)
        }

        available_slots = max_concurrent - len(self._running_ids)
        if available_slots <= 0:
            return

        # Admission control via ResourceGovernor
        try:
            from ..authority import ExecutionAuthority
            authority = ExecutionAuthority.get()
            from ..resource_governor import AdmissionDecision, TaskWeight
            pending_preview = OpsService.list_pending_runs()
            weight = _task_weight_for_run(pending_preview[0]) if pending_preview else TaskWeight.MEDIUM
            decision = authority.resource_governor.evaluate(weight)
            if decision != AdmissionDecision.ALLOW:
                logger.info("ResourceGovernor deferred runs (decision=%s)", decision.value)
                return
        except RuntimeError:
            pass  # Authority not yet initialized

        pending = OpsService.list_pending_runs()
        for run in pending[:available_slots]:
            if run.id not in self._running_ids:
                self._running_ids.add(run.id)
                asyncio.create_task(self._execute_run(run.id))

    def _is_still_active(self, run_id: str) -> bool:
        run = OpsService.get_run(run_id)
        return run is not None and run.status in ("pending", "running", "awaiting_subagents", "awaiting_review")

    # --- LEGACY PATHS REMOVED (OBSOLETE) ---
    @staticmethod
    def _extract_target_path(text: str) -> Optional[str]:
        """OBSOLETE: Use EngineService and tools."""
        return None

    async def _execute_file_task(
        self,
        *args, **kwargs
    ) -> bool:
        """OBSOLETE: Replaced by ToolExecutor/EngineService."""
        return False

    async def _process_task(self, *args, **kwargs) -> None:
        """OBSOLETE: Replaced by ToolExecutor/EngineService."""
        pass

    async def _execute_structured_plan(self, *args, **kwargs) -> None:
        """OBSOLETE: Replaced by EngineService."""
        pass

    async def _critic_with_retry(
        self,
        *,
        run_id: str,
        output_text: str,
        base_prompt: str,
        intent_effective: str,
        path_scope: list[str],
        requested_model: str = "",
        initial_raw: dict | None = None,
    ) -> tuple[bool, str, dict]:
        """Hidden critic loop with max 2 retries for non-critical verdicts."""
        current_output = output_text
        current_raw: dict = dict(initial_raw or {})
        current_raw.setdefault("content", output_text)
        gics = getattr(OpsService, "_gics", None)
        quality = QualityService.analyze_output(output_text)
        model_name = str(
            current_raw.get("final_model_used")
            or current_raw.get("model")
            or current_raw.get("model_attempted")
            or requested_model
            or "unknown"
        )

        def _fields(record: dict | None) -> dict:
            if not isinstance(record, dict):
                return {}
            nested = record.get("fields")
            return dict(nested) if isinstance(nested, dict) else dict(record)

        def _stats_key(name: str) -> str:
            return f"ops:task:run_worker_execution:{name}"

        def _update_stats(*, approved: bool, critic_needed: bool, raw: dict) -> None:
            if not gics:
                return
            resolved_model = str(
                raw.get("final_model_used")
                or raw.get("model")
                or raw.get("model_attempted")
                or model_name
                or "unknown"
            )
            key = _stats_key(resolved_model)
            try:
                fields = _fields(gics.get(key))
                samples = int(fields.get("samples", 0) or 0) + 1
                successes = int(fields.get("successes", 0) or 0) + (1 if approved else 0)
                critic_calls = int(fields.get("critic_calls", 0) or 0) + (1 if critic_needed else 0)
                critic_skips = int(fields.get("critic_skips", 0) or 0) + (0 if critic_needed else 1)
                updated = {
                    **fields,
                    "samples": samples,
                    "successes": successes,
                    "success_rate": successes / max(1, samples),
                    "critic_calls": critic_calls,
                    "critic_skips": critic_skips,
                    "last_used": datetime.now(timezone.utc).timestamp(),
                }
                usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
                completion_tokens = int(usage.get("completion_tokens", 0) or 0)
                if completion_tokens > 0:
                    prev_samples = int(fields.get("avg_output_samples", fields.get("samples", 0)) or 0)
                    avg_output = float(fields.get("avg_output_tokens", 0) or 0)
                    updated["avg_output_samples"] = prev_samples + 1
                    updated["avg_output_tokens"] = ((avg_output * prev_samples) + completion_tokens) / max(1, prev_samples + 1)
                gics.put(key, updated)
            except Exception:
                logger.debug("Failed to update critic gate stats for %s", resolved_model, exc_info=True)

        if gics:
            try:
                stats = _fields(gics.get(_stats_key(model_name)))
            except Exception:
                stats = {}
        else:
            stats = {}

        if (
            quality.score >= 80
            and int(stats.get("samples", 0) or 0) >= 15
            and float(stats.get("success_rate", 0) or 0.0) >= 0.90
        ):
            OpsService.append_log(
                run_id,
                level="INFO",
                msg=f"Critic skipped: quality={quality.score} samples={stats.get('samples', 0)} success_rate={stats.get('success_rate', 0)}",
            )
            _update_stats(approved=True, critic_needed=False, raw=current_raw)
            return True, current_output, current_raw

        for attempt in range(0, 3):
            verdict = await CriticService.evaluate(
                current_output,
                context={"run_id": run_id, "attempt": attempt + 1, "intent_effective": intent_effective},
            )
            OpsService.append_log(
                run_id,
                level="INFO",
                msg=f"Critic verdict: approved={verdict.approved} severity={verdict.severity} issues={verdict.issues}",
            )

            if verdict.approved:
                _update_stats(approved=True, critic_needed=True, raw=current_raw)
                return True, current_output, current_raw

            if verdict.severity == "critical" or attempt >= 2:
                _update_stats(approved=False, critic_needed=True, raw=current_raw)
                return False, current_output, current_raw

            retry_prompt = (
                f"{base_prompt}\n\n"
                f"CRITIC FEEDBACK (MUST FIX): {verdict.issues}\n"
                "Rewrite the execution output with concise, safe and actionable format."
            )
            current_raw = await ProviderService.static_generate_phase6_strategy(
                prompt=retry_prompt,
                context={"mode": "execute_retry"},
                intent_effective=intent_effective,
                path_scope=path_scope,
            )
            current_output = str(current_raw.get("content") or "")
            model_name = str(
                current_raw.get("final_model_used")
                or current_raw.get("model")
                or current_raw.get("model_attempted")
                or model_name
                or "unknown"
            )

        _update_stats(approved=False, critic_needed=True, raw=current_raw)
        return False, current_output, current_raw

    def _build_executor_report(self, run_id: str, *, output_text: str, run_result: dict) -> ExecutorReport:
        modified_files = sorted(set(re.findall(r"[\w./\\-]+\.[a-zA-Z0-9]{1,8}", output_text)))
        if not modified_files:
            modified_files = []

        rollback_plan = [
            "git reset --hard HEAD",
            "git clean -fd",
        ]
        if run_result.get("commit_before"):
            rollback_plan.insert(0, f"git reset --hard {run_result['commit_before']}")

        return ExecutorReport(
            run_id=run_id,
            agent_id="executor",
            modified_files=modified_files,
            safety_summary="Execution completed with policy + critic checks.",
            rollback_plan=rollback_plan,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def _handle_legacy_execution(self, *args, **kwargs) -> None:
        """OBSOLETE: Replaced by ToolExecutor/EngineService."""
        pass

    async def _handle_child_completion(self, child_run_id: str) -> None:
        """Called when a child run finishes. Decrements parent counter and wakes if zero."""
        child_run = OpsService.get_run(child_run_id)
        if not child_run or not child_run.parent_run_id:
            return

        # Record outcome in CapabilityProfile (ACE learning loop)
        try:
            from ..capability_profile_service import CapabilityProfileService
            child_ctx = child_run.child_context or {}
            task_type = child_ctx.get("role") or child_ctx.get("task_type") or "general"
            model_id = child_ctx.get("model") or ""
            provider_type = child_ctx.get("provider_type") or "unknown"
            if model_id:
                CapabilityProfileService.record_task_outcome(
                    provider_type=provider_type,
                    model_id=model_id,
                    task_type=task_type,
                    success=(child_run.status == "done"),
                    failure_reason="" if child_run.status == "done" else f"Run ended with status: {child_run.status}",
                )
        except Exception:
            pass  # Non-critical: don't block completion flow

        # Publish event before acquiring lock
        await NotificationService.publish("child_run_completed", {
            "parent_run_id": child_run.parent_run_id,
            "child_run_id": child_run_id,
            "child_status": child_run.status,
            "critical": True,
        })

        # Reload from disk, decrement, and persist under lock to avoid lost-update
        with OpsService._lock():
            fresh = OpsService._load_run_metadata(child_run.parent_run_id)
            if not fresh:
                return
            fresh.awaiting_count = max(0, fresh.awaiting_count - 1)
            OpsService._persist_run(fresh)
            remaining = fresh.awaiting_count

        OpsService.append_log(fresh.id, level="INFO",
            msg=f"Child {child_run_id} completed ({child_run.status}). Remaining: {remaining}")

        if remaining == 0:
            OpsService.update_run_status(fresh.id, "running", msg="All child runs completed. Resuming.")
            await NotificationService.publish("all_children_completed", {
                "parent_run_id": fresh.id,
                "critical": True,
            })
            self._running_ids.add(fresh.id)
            asyncio.create_task(self._execute_run(fresh.id))

    def _validate_task_spec(self, spec: Any) -> tuple[bool, str]:
        """Strict validation of the Phase 5B task specification using Pydantic."""
        from ...schemas.draft_validation import ValidatedTaskSpec
        if not isinstance(spec, dict):
            return False, "TaskSpec must be a dictionary"
        try:
            ValidatedTaskSpec.model_validate(spec)
            # Extra Phase 5B constraints
            if not spec.get("allowed_paths"):
                return False, "allowed_paths cannot be empty for bounded execution"
            if spec.get("requires_manual_merge") is not True:
                return False, "requires_manual_merge must be True in Phase 5"
            return True, ""
        except Exception as e:
            return False, f"Schema validation failed: {str(e)}"

    async def _execute_run(self, run_id: str) -> None:
        try:
            from ..ops_service import OpsService
            run = OpsService.get_run(run_id)
            if not run:
                return

            # Phase 5B: No run without ValidatedTaskSpec
            task_spec = getattr(run, "validated_task_spec", None)
            if not task_spec:
                msg = "[Phase 5B] Execution rejected: No ValidatedTaskSpec found. Recon required."
                OpsService.append_log(run_id, level="ERROR", msg=msg)
                OpsService.update_run_status(run_id, "error", msg="Missing ValidatedTaskSpec")
                return

            # Strict validation (B2)
            valid, err = self._validate_task_spec(task_spec)
            if not valid:
                msg = f"[Phase 5B] Execution rejected: Malformed TaskSpec - {err}"
                OpsService.append_log(run_id, level="ERROR", msg=msg)
                OpsService.update_run_status(run_id, "error", msg=f"Invalid TaskSpec: {err}")
                return

            # Build bounded worker context (Phase 5B)
            try:
                workspace_path = str(task_spec.get("workspace_path") or "").strip()
                if not workspace_path:
                    msg = "[Phase 5B] Execution rejected: Missing canonical workspace_path."
                    OpsService.append_log(run_id, level="ERROR", msg=msg)
                    OpsService.update_run_status(run_id, "error", msg="Workspace resolution failed")
                    return
                repo_path = Path(workspace_path)
                if not repo_path.exists() or not repo_path.is_dir():
                    msg = "[Phase 5B] Execution rejected: workspace_path does not exist."
                    OpsService.append_log(run_id, level="ERROR", msg=msg)
                    OpsService.update_run_status(run_id, "error", msg="Workspace resolution failed")
                    return

                # Inject bounded context into the run context (Phase 5B 5.4)
                if run.child_context is None:
                    run.child_context = {}
                
                # Bounded context builder logic (5.4)
                bounded_files = self._build_worker_context(
                    task=task_spec,
                    repo_root=repo_path,
                    max_files=5
                )
                
                # B2 Fail-Closed: If bounded context construction fails or is empty, block.
                if not bounded_files:
                    msg = "[Phase 5B] Execution rejected: Failed to construct bounded context (no files found)."
                    OpsService.append_log(run_id, level="ERROR", msg=msg)
                    OpsService.update_run_status(run_id, "error", msg="Bounded context empty")
                    return

                run.child_context["gen_context"] = {
                    "bounded_files": bounded_files
                }
                # Ensure allowed_paths are strictly respected by tool executor too
                run.child_context["allowed_paths"] = task_spec.get("allowed_paths", [])
                OpsService._persist_run(run)

            except Exception as e:
                msg = f"[Phase 5B] Bounded context failure: {str(e)}"
                logger.error(msg)
                OpsService.append_log(run_id, level="ERROR", msg=msg)
                OpsService.update_run_status(run_id, "error", msg="Context construction failure")
                return

            from .engine_service import EngineService
            await EngineService.execute_run(run_id)
        except Exception:
            logger.exception("Failed to execute run %s via EngineService", run_id)
            try:
                OpsService.update_run_status(run_id, "error", msg="Internal engine error")
            except Exception:
                pass
        finally:
            self._running_ids.discard(run_id)
            run = OpsService.get_run(run_id)
            if run and run.parent_run_id and run.status in ("done", "error"):
                await self._handle_child_completion(run_id)

    def _build_worker_context(self, task: dict, repo_root: Path, max_files: int = 5) -> List[Dict[str, Any]]:
        """
        P5.4: Builds a bounded worker context from the repo.
        No global scans. Bounded by allowed_paths, same-dir, and imports.
        Hard cap of 10 files.
        """
        # Hard cap (GIMO B4)
        MAX_FILES_HARD_CAP = 10
        limit = min(max_files, MAX_FILES_HARD_CAP)
        
        allowed_paths = task.get("allowed_paths", [])
        if not allowed_paths:
            return []

        # Start with exact allowed_paths
        selected_rel_paths = set(allowed_paths[:limit])
        
        # B4: Adjacency enrichment (same-dir files)
        # Only enrich for seed files that actually exist.
        enriched = set(selected_rel_paths)
        if len(enriched) < limit:
            for path_str in list(selected_rel_paths):
                if len(enriched) >= limit:
                    break
                try:
                    # B4: Strict seeding. Only enrich if the seed file is verified on disk.
                    abs_seed = (repo_root / path_str).resolve()
                    # Ensure it is within repo
                    abs_seed.relative_to(repo_root.resolve())
                    if not abs_seed.exists() or not abs_seed.is_file():
                        continue

                    p = Path(path_str)
                    parent = p.parent
                    full_parent = (repo_root / parent).resolve()
                    # Ensure parent is inside repo
                    full_parent.relative_to(repo_root.resolve())
                    
                    if full_parent.is_dir():
                        for neighbor in sorted(list(full_parent.iterdir())):
                            if len(enriched) >= limit:
                                break
                            if neighbor.is_file() and not neighbor.name.startswith("."):
                                rel_neighbor = str(neighbor.relative_to(repo_root)).replace("\\", "/")
                                enriched.add(rel_neighbor)
                except Exception:
                    continue

        # Convert back to list and sort for determinism
        final_rel_paths = sorted(list(enriched))[:limit]
        
        context_items = []
        for rel_path in final_rel_paths:
            try:
                abs_path = (repo_root / rel_path).resolve()
                # B2/B4: Strict containment check
                abs_path.relative_to(repo_root.resolve())
            except (ValueError, Exception):
                continue

            if abs_path.exists() and abs_path.is_file():
                try:
                    content = abs_path.read_text(encoding="utf-8", errors="ignore")
                    symbols = []
                    # Simple symbol extraction (first 500 lines only)
                    lines = content.splitlines()
                    for line in lines[:500]:
                        m = re.match(r"^\s*(?:def|class)\s+([a-zA-Z_]\w*)", line)
                        if m:
                            symbols.append(m.group(1))
                    
                    context_items.append({
                        "path": rel_path,
                        "content": content,
                        "symbols": symbols[:20] 
                    })
                except Exception:
                    continue

        return context_items
