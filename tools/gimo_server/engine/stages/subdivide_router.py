"""SubdivideRouter — intercepts LLM output when ACE selected the subdivide strategy.

When `ace_subdivide_mode=True` in context, the LLM was asked to produce a JSON
array of subtasks instead of executing the task directly.  This stage:

1. Parses that JSON array from the LLM output.
2. Injects `child_tasks` into the run's child_context (so engine_service detects
   multi_agent composition on the next execution cycle).
3. Returns `halt` so the pipeline stops and the current child run stays pending.

If `ace_subdivide_mode` is not set, it passes through instantly (continue).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from ..contracts import StageInput, StageOutput

logger = logging.getLogger(__name__)


class SubdivideRouter:
    name = "subdivide_router"

    async def execute(self, input: StageInput) -> StageOutput:
        if not input.context.get("ace_subdivide_mode"):
            return StageOutput(status="continue")

        from ...services.ops import OpsService

        llm_content = str(input.artifacts.get("content") or "")

        # Parse JSON array from LLM output
        child_tasks = _parse_subtasks(llm_content)

        if not child_tasks:
            OpsService.append_log(
                input.run_id, level="WARN",
                msg="[SubdivideRouter] Could not parse subtasks JSON from LLM output — falling through to FileWrite"
            )
            # Fall through: let FileWrite handle the raw output
            return StageOutput(status="continue")

        OpsService.append_log(
            input.run_id, level="INFO",
            msg=f"[SubdivideRouter] Parsed {len(child_tasks)} subtasks from LLM decomposition"
        )

        # Inject child_tasks into this run's child_context so engine_service
        # selects multi_agent composition on the next execution cycle.
        with OpsService._lock():
            run = OpsService._load_run_metadata(input.run_id)
            if run:
                ctx = dict(run.child_context or {})
                ctx["child_tasks"] = child_tasks
                # Clear subdivide mode so next cycle goes multi_agent
                ctx.pop("ace_subdivide_mode", None)
                run.child_context = ctx
                run.status = "pending"
                OpsService._persist_run(run)

        OpsService.append_log(
            input.run_id, level="INFO",
            msg=f"[SubdivideRouter] child_tasks injected. Re-queuing as multi_agent."
        )

        # Notify worker to pick up the re-queued run
        try:
            from ...services.authority import ExecutionAuthority
            ExecutionAuthority.get().run_worker.notify()
        except Exception:
            pass

        return StageOutput(
            status="halt",
            artifacts={"subdivide_child_tasks": child_tasks},
        )

    async def rollback(self, input: StageInput) -> None:
        pass


def _parse_subtasks(content: str) -> List[Dict[str, Any]]:
    """Extract a JSON array of subtasks from LLM output.

    The LLM may wrap the JSON in markdown code fences or add preamble text.
    We locate the first '[' … ']' balanced block and parse it.
    """
    # Strip markdown code fences
    cleaned = re.sub(r"```[\w]*\n?", "", content).strip()

    # Find first JSON array
    start = cleaned.find("[")
    if start == -1:
        return []

    depth = 0
    end = -1
    for i, ch in enumerate(cleaned[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return []

    try:
        data = json.loads(cleaned[start:end])
        if not isinstance(data, list):
            return []
        # Validate minimal structure: each item must have at least a prompt
        result = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            if not item.get("prompt"):
                continue
            if not item.get("id"):
                item["id"] = f"sub_{i + 1}"
            if "depends_on" not in item:
                item["depends_on"] = []
            result.append(item)
        return result
    except (json.JSONDecodeError, Exception):
        return []
