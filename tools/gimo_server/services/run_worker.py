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
from pathlib import Path
from typing import Optional

from .ops_service import OpsService
from .provider_service import ProviderService

logger = logging.getLogger("orchestrator.run_worker")

# How often to poll for pending runs (seconds).
POLL_INTERVAL = 5

# Default per-run timeout if nothing else configured.
DEFAULT_RUN_TIMEOUT = 300  # 5 min


class RunWorker:
    """Async background worker for OPS run execution."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running_ids: set[str] = set()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info("RunWorker started")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("RunWorker stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("RunWorker tick error")
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self) -> None:
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

        pending = OpsService.list_pending_runs()
        for run in pending[:available_slots]:
            if run.id not in self._running_ids:
                self._running_ids.add(run.id)
                asyncio.create_task(self._execute_run(run.id))

    def _is_still_active(self, run_id: str) -> bool:
        run = OpsService.get_run(run_id)
        return run is not None and run.status in ("pending", "running")

    @staticmethod
    def _extract_target_path(text: str) -> Optional[str]:
        """Extract a full target file path (TARGET_FILE: ...) or a filename."""
        import re
        # Priority 1: Explicit TARGET_FILE directive with full path
        m = re.search(r"TARGET_FILE:\s*(\S+)", text)
        if m:
            return m.group(1).strip()
        # Priority 2: Full absolute/relative paths
        m = re.search(r"([A-Za-z]:[/\\][^\s\"']+\.\w{1,5})", text)
        if m:
            return m.group(1).strip()
        # Priority 3: Simple filenames
        patterns = [
            r"['\"]([a-zA-Z0-9_\-]+\.\w{1,5})['\"]",
            r"(?:file|named?|llamado|archivo)\s+['\"]?([a-zA-Z0-9_\-]+\.\w{1,5})",
            r"(?:create|crear|write|escribir)\s+['\"]?([a-zA-Z0-9_\-]+\.\w{1,5})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    async def _execute_file_task(
        self,
        run_id: str,
        task_id: str,
        title: str,
        description: str,
        system_prompt: str,
        model: str,
        instructions: list,  # noqa: ARG002
        base_path: Optional[Path] = None,
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
                ProviderService.static_generate(
                    prompt=generation_prompt,
                    context={"mode": "worker_file_gen", "model": model}
                ),
                timeout=DEFAULT_RUN_TIMEOUT,
            )
            content = llm_resp.get("content", "").strip()
            llm_model_used = llm_resp.get("model", model)
            # Clean markdown code fences if the LLM wrapped it
            if content.startswith("```"):
                content = re.sub(r"```\w*\n?|```", "", content).strip()

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

    async def _execute_run(self, run_id: str) -> None:
        try:
            OpsService.update_run_status(run_id, "running", msg="Execution started")

            run = OpsService.get_run(run_id)
            if not run:
                return

            approved = OpsService.get_approved(run.approved_id)
            if not approved:
                OpsService.update_run_status(run_id, "error", msg="Approved entry not found")
                return

            prompt = (
                f"Execute the following approved operation:\n\n"
                f"--- PROMPT ---\n{approved.prompt}\n\n"
                f"--- CONTENT ---\n{approved.content}\n\n"
                f"Provide the execution result."
            )

            try:
                # 1. Check if content is a structured JSON plan
                is_structured = False
                import json
                try:
                    plan_data = json.loads(approved.content)
                    if isinstance(plan_data, dict) and "tasks" in plan_data:
                        is_structured = True
                except:
                    pass

                if is_structured:
                    OpsService.append_log(run_id, level="INFO", msg="Detected structured plan. Executing steps...")
                    for task in plan_data["tasks"]:
                        tid = task.get("id", "??")
                        title = task.get("title", "")
                        desc = task.get("description", "")
                        combined = f"{title} {desc}".lower()
                        agent = task.get("agent_assignee", {})
                        agent_model = agent.get("model", "qwen2.5-coder:3b")
                        agent_prompt = agent.get("system_prompt", "")
                        agent_instructions = agent.get("instructions", [])

                        OpsService.append_log(run_id, level="INFO", msg=f"Executing Task {tid}: {title}")

                        # Skip orchestrator-type tasks (they coordinate, not execute)
                        if any(kw in combined for kw in ["orchestr", "coordinat", "lead", "monitor"]):
                            OpsService.append_log(run_id, level="INFO", msg=f"Task {tid}: Orchestrator role — delegation noted.")
                            continue

                        # Detect file write/create tasks
                        if any(kw in combined for kw in ["escribir", "write", "crear", "create", "generar", "generate", ".bat", ".txt", ".py", ".sh"]):
                            # Attempt to find if this assignee has an isolated worktree
                            base_path = None
                            if agent.get("id"):
                                from .sub_agent_manager import SubAgentManager
                                sa = SubAgentManager.get_sub_agent(agent.get("id"))
                                if sa and sa.worktreePath:
                                    base_path = Path(sa.worktreePath)
                                    OpsService.append_log(run_id, level="INFO", msg=f"Task {tid}: Using isolated worktree at {base_path}")

                            file_result = await self._execute_file_task(
                                run_id, tid, title, desc, agent_prompt, agent_model, agent_instructions,
                                base_path=base_path
                            )
                            if file_result:
                                continue

                        # For other tasks, attempt LLM execution or simulate
                        if agent_prompt:
                            try:
                                OpsService.append_log(run_id, level="INFO", msg=f"Task {tid}: Sending to LLM ({agent_model})...")
                                llm_resp = await asyncio.wait_for(
                                    ProviderService.static_generate(
                                        prompt=agent_prompt,
                                        context={"mode": "worker_execute", "model": agent_model}
                                    ),
                                    timeout=DEFAULT_RUN_TIMEOUT,
                                )
                                result_content = llm_resp.get("content", "")[:500]
                                OpsService.append_log(run_id, level="INFO", msg=f"Task {tid} LLM result: {result_content}")
                            except Exception as llm_err:
                                OpsService.append_log(run_id, level="WARN", msg=f"Task {tid} LLM call failed: {llm_err}")
                        else:
                            OpsService.append_log(run_id, level="INFO", msg=f"Task {tid} (Simulation): Success.")

                    OpsService.update_run_status(run_id, "done", msg="Structured plan execution completed")
                    return


                # 2. Legacy/Simple execution (via LLM generation)
                resp = await asyncio.wait_for(
                    ProviderService.static_generate(prompt, context={"mode": "execute"}),
                    timeout=DEFAULT_RUN_TIMEOUT,
                )
                provider_name = resp["provider"]
                result = resp["content"]
                OpsService.append_log(run_id, level="INFO", msg=f"Provider: {provider_name}")
                OpsService.append_log(run_id, level="INFO", msg=f"Result:\n{result[:2000]}")
                OpsService.update_run_status(run_id, "done", msg="Execution completed")
            except asyncio.TimeoutError:
                OpsService.update_run_status(run_id, "error", msg="Execution timed out")
            except Exception as exc:
                OpsService.update_run_status(
                    run_id, "error", msg=f"Provider error: {str(exc)[:200]}"
                )
        except Exception:
            logger.exception("Failed to execute run %s", run_id)
            try:
                OpsService.update_run_status(run_id, "error", msg="Internal worker error")
            except Exception:
                logger.debug("Could not update error status for run %s", run_id)
        finally:
            self._running_ids.discard(run_id)
