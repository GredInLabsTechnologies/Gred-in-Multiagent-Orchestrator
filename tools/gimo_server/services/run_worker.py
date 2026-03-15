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
from typing import Optional

from ..ops_models import ExecutorReport
from .ops_service import OpsService
from .provider_service import ProviderService
from .notification_service import NotificationService
from .merge_gate_service import MergeGateService
from .critic_service import CriticService

logger = logging.getLogger("orchestrator.run_worker")

# How often to poll for pending runs (seconds).
POLL_INTERVAL = 5


def _task_weight_for_run(run) -> "TaskWeight":
    """Infer ResourceGovernor TaskWeight from the run's approved/draft context."""
    from .resource_governor import TaskWeight
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
            from .authority import ExecutionAuthority
            authority = ExecutionAuthority.get()
            from .resource_governor import AdmissionDecision, TaskWeight
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
        return run is not None and run.status in ("pending", "running", "awaiting_subagents")

    @staticmethod
    def _extract_target_path(text: str) -> Optional[str]:
        """Extract a full target file path (TARGET_FILE: ...) or a filename.

        Handles:
        - Explicit TARGET_FILE directive (highest priority)
        - Windows absolute paths  (C:/... or C:\\...)
        - Relative paths with directory components (docs/DISEÑO_CALCULADORA.md)
        - Unicode filenames (e.g. names with Ñ, accents, etc.)
        - Quoted or bare filenames as fallback
        """
        import re

        # Priority 1: Explicit TARGET_FILE directive
        m = re.search(r"TARGET_FILE:\s*(\S+)", text)
        if m:
            return m.group(1).strip()

        # Priority 2: Windows absolute path
        m = re.search(r"([A-Za-z]:[/\\][^\s\"']+\.\w{1,5})", text)
        if m:
            return m.group(1).strip()

        # Priority 3: Relative path with at least one directory component
        # Matches e.g. "docs/DISEÑO_CALCULADORA.md" or "src/foo/bar.py"
        # Uses \S to allow Unicode characters in the path.
        m = re.search(r"(\S+/[^\s\"']+\.\w{1,5})", text)
        if m:
            candidate = m.group(1).strip().strip("'\",")
            if "." in candidate.split("/")[-1]:  # last segment has extension
                return candidate

        # Priority 4: Quoted filename (with Unicode support via \S)
        m = re.search(r"['\"]([^\s\"']+\.\w{1,5})['\"]", text)
        if m:
            return m.group(1)

        # Priority 5: Bare filename after action keyword (Unicode-aware)
        m = re.search(
            r"(?:create|crear|write|escribir|generar|generate|file|archivo|llamado|named?)"
            r"\s+['\"]?(\S+\.\w{1,5})",
            text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip("'\",")

        return None

    async def _execute_file_task(
        self,
        run_id: str,
        task_id: str,
        title: str,
        description: str,
        system_prompt: str,
        model: str,
        base_path: Optional[Path] = None,
        intent_effective: str = "",
        path_scope: Optional[list[str]] = None,
    ) -> bool:
        """
        Execute a file-write task via LLM. Returns True if handled.

        Strategy:
        1. Extract target path from description or system_prompt
        2. Always call the LLM to generate the file content
        3. Write via FileService
        """
        from .file_service import FileService
        from ..config import get_settings
        import re

        combined_text = f"{title} {description} {system_prompt}"
        target = self._extract_target_path(combined_text)

        if not target:
            OpsService.append_log(
                run_id, level="WARN",
                msg=f"Task {task_id}: Detected file op but couldn't extract target path. Skipping."
            )
            return False

        # Determine full path: absolute path or relative to repo root
        target_path = Path(target)
        if not target_path.is_absolute():
            settings = get_settings()
            repo_root = base_path or settings.repo_root_dir
            target_path = repo_root / target

        OpsService.append_log(
            run_id, level="INFO",
            msg=f"Task {task_id}: File target → {target_path} (model: {model})"
        )

        # Always call the LLM to generate the file content
        try:
            OpsService.append_log(
                run_id, level="INFO",
                msg=f"Task {task_id}: Calling LLM ({model}) to generate file content..."
            )
            generation_prompt = (
                f"{system_prompt}\n\n"
                f"Generate ONLY the raw file content for '{target_path.name}'. "
                f"Do not include explanations, markdown fences, or anything else — "
                f"just the exact content that should be written to the file."
            )
            llm_resp = await asyncio.wait_for(
                ProviderService.static_generate_phase6_strategy(
                    prompt=generation_prompt,
                    context={"mode": "worker_file_gen", "model": model},
                    intent_effective=intent_effective,
                    path_scope=list(path_scope or []),
                ),
                timeout=DEFAULT_RUN_TIMEOUT,
            )
            content = llm_resp.get("content", "").strip()
            llm_model_used = llm_resp.get("model", model)
            # Clean markdown code fences if the LLM wrapped it
            if content.startswith("```"):
                content = re.sub(r"```\w*\n?", "", content).strip()

            OpsService.append_log(
                run_id, level="INFO",
                msg=f"Task {task_id}: LLM ({llm_model_used}) generated content ({len(content)} chars)"
            )
        except Exception as e:
            OpsService.append_log(
                run_id, level="ERROR",
                msg=f"Task {task_id}: LLM generation failed: {e}"
            )
            return False

        # Write the file
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            FileService.write_file(target_path, content, f"gimo_worker_{llm_model_used}")
            OpsService.append_log(
                run_id, level="INFO",
                msg=f"Task {task_id}: ✅ File written → {target_path}"
            )
            return True
        except Exception as write_err:
            OpsService.append_log(
                run_id, level="ERROR",
                msg=f"Task {task_id}: ❌ File write failed: {write_err}"
            )
            return False

    async def _process_task(self, run_id: str, task: dict, intent_effective: str, path_scope: list[str]) -> None:
        tid = task.get("id", "??")
        title = task.get("title", "")
        desc = task.get("description", "")
        combined = f"{title} {desc}".lower()
        agent = task.get("agent_assignee", {})
        agent_model = agent.get("model", "qwen2.5-coder:3b")
        agent_prompt = agent.get("system_prompt", "")

        OpsService.append_log(run_id, level="INFO", msg=f"Executing Task {tid}: {title}")

        if any(kw in combined for kw in ["orchestr", "coordinat", "lead", "monitor"]):
            OpsService.append_log(run_id, level="INFO", msg=f"Task {tid}: Orchestrator role — delegation noted.")
            return

        if any(kw in combined for kw in ["escribir", "write", "crear", "create", "generar", "generate", ".bat", ".txt", ".py", ".sh", ".md", ".yaml", ".json", "docs/", "doc/"]):
            base_path = None
            if agent.get("id"):
                from .sub_agent_manager import SubAgentManager
                sa = SubAgentManager.get_sub_agent(agent.get("id"))
                if sa and sa.worktreePath:
                    base_path = Path(sa.worktreePath)
                    OpsService.append_log(run_id, level="INFO", msg=f"Task {tid}: Using isolated worktree at {base_path}")

            file_result = await self._execute_file_task(
                run_id, tid, title, desc, agent_prompt, agent_model,
                base_path=base_path,
                intent_effective=intent_effective,
                path_scope=path_scope,
            )
            if file_result:
                return

        if agent_prompt:
            try:
                OpsService.append_log(run_id, level="INFO", msg=f"Task {tid}: Sending to LLM ({agent_model})...")
                llm_resp = await asyncio.wait_for(
                    ProviderService.static_generate_phase6_strategy(
                        prompt=agent_prompt,
                        context={"mode": "worker_execute", "model": agent_model},
                        intent_effective=intent_effective,
                        path_scope=path_scope,
                    ),
                    timeout=DEFAULT_RUN_TIMEOUT,
                )
                result_content = llm_resp.get("content", "")[:500]
                OpsService.append_log(run_id, level="INFO", msg=f"Task {tid} LLM result: {result_content}")
            except Exception as llm_err:
                OpsService.append_log(run_id, level="WARN", msg=f"Task {tid} LLM call failed: {llm_err}")
        else:
            OpsService.append_log(run_id, level="INFO", msg=f"Task {tid} (Simulation): Success.")

    async def _execute_structured_plan(self, run_id: str, plan_data: dict, intent_effective: str, path_scope: list[str]) -> None:
        OpsService.append_log(run_id, level="INFO", msg="Detected structured plan. Executing steps...")
        for task in plan_data.get("tasks", []):
            await self._process_task(run_id, task, intent_effective, path_scope)

        report = self._build_executor_report(run_id, output_text="Structured plan executed", run_result={})
        OpsService.append_log(run_id, level="INFO", msg=f"ExecutorReport: {report.model_dump_json()}")

        OpsService.update_run_status(run_id, "done", msg="Structured plan execution completed")

    async def _critic_with_retry(
        self,
        *,
        run_id: str,
        output_text: str,
        base_prompt: str,
        intent_effective: str,
        path_scope: list[str],
    ) -> tuple[bool, str, dict]:
        """Hidden critic loop with max 2 retries for non-critical verdicts."""
        current_output = output_text
        current_raw: dict = {"content": output_text}

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
                return True, current_output, current_raw

            if verdict.severity == "critical" or attempt >= 2:
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

    async def _handle_legacy_execution(self, run_id: str, prompt: str, intent_effective: str, path_scope: list[str]) -> None:
        try:
            resp = await asyncio.wait_for(
                ProviderService.static_generate_phase6_strategy(
                    prompt=prompt,
                    context={"mode": "execute"},
                    intent_effective=intent_effective,
                    path_scope=path_scope,
                ),
                timeout=DEFAULT_RUN_TIMEOUT,
            )
            provider_name = resp.get("provider", "unknown")
            result = resp.get("content", "")

            critic_ok, result, resp = await self._critic_with_retry(
                run_id=run_id,
                output_text=str(result),
                base_prompt=prompt,
                intent_effective=intent_effective,
                path_scope=path_scope,
            )
            if not critic_ok:
                OpsService.update_run_status(run_id, "error", msg="Critic rejected output")
                return

            OpsService.append_log(
                run_id,
                level="INFO",
                msg=(
                    "Model strategy: "
                    f"attempted={resp.get('model_attempted','')} "
                    f"failure_reason={resp.get('failure_reason','')} "
                    f"final_model={resp.get('final_model_used', resp.get('model',''))} "
                    f"fallback_used={bool(resp.get('fallback_used', False))}"
                ),
            )
            OpsService.append_log(run_id, level="INFO", msg=f"Provider: {provider_name}")
            OpsService.append_log(run_id, level="INFO", msg=f"Result:\n{result[:2000]}")

            report = self._build_executor_report(run_id, output_text=str(result), run_result=resp)
            # Validator enforces rollback_plan non-empty
            ExecutorReport.model_validate(report.model_dump())
            OpsService.append_log(run_id, level="INFO", msg=f"ExecutorReport: {report.model_dump_json()}")

            OpsService.update_run_status(run_id, "done", msg="Execution completed")
        except asyncio.TimeoutError:
            OpsService.update_run_status(run_id, "error", msg="Execution timed out")
        except Exception as exc:
            OpsService.update_run_status(run_id, "error", msg=f"Provider error: {str(exc)[:200]}")

    async def _handle_child_completion(self, child_run_id: str) -> None:
        """Called when a child run finishes. Decrements parent counter and wakes if zero."""
        child_run = OpsService.get_run(child_run_id)
        if not child_run or not child_run.parent_run_id:
            return

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
            self.notify()

    async def _execute_run(self, run_id: str) -> None:
        try:
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
