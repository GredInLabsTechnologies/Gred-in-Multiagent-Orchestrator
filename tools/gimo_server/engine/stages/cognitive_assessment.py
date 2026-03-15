"""Adaptive Cognitive Engine (ACE) — Pre-flight self-assessment stage.

Before a node executes its task, ACE evaluates:
1. Historical capability of this model for this task_type (via GICS)
2. Context richness (how well-specified is the task?)
3. Sibling outputs (what have parallel agents already produced?)
4. Task scope estimation (how large is this task?)

From these signals it computes a confidence score and selects a strategy:
    >= 0.8  →  DIRECT_EXECUTE   (fast path, high confidence)
    >= 0.6  →  ENRICH_CONTEXT   (pull sibling outputs into prompt)
    >= 0.4  →  MULTI_PASS       (iterative refinement, multiple LLM calls)
    >= 0.2  →  SUBDIVIDE        (decompose into child_tasks, go fractal)
    <  0.2  →  ESCALATE         (notify orchestrator via complexity_escalation)

Every decision is logged with full reasoning so the orchestrator (and humans)
can see WHY the agent chose its strategy. This is the key differentiator:
transparent, data-driven autonomy.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ..contracts import StageInput, StageOutput

logger = logging.getLogger(__name__)

# Strategy thresholds (configurable via context)
DEFAULT_THRESHOLDS = {
    "direct_execute": 0.8,
    "enrich_context": 0.6,
    "multi_pass": 0.4,
    "subdivide": 0.2,
    # Below 0.2 → escalate
}

# Weights for confidence computation
W_HISTORICAL = 0.40   # GICS historical success rate
W_CONTEXT = 0.25      # How well-specified the task is
W_SCOPE = 0.20        # Estimated task scope (smaller = higher confidence)
W_SIBLING = 0.15      # Whether sibling context is available


class CognitiveAssessmentStage:
    """Pre-flight self-assessment: the agent evaluates its own capability
    for the assigned task and selects an execution strategy autonomously."""

    name = "cognitive_assessment"

    async def execute(self, input: StageInput) -> StageOutput:
        from ...services.ops_service import OpsService

        run = OpsService.get_run(input.run_id)
        if not run:
            return StageOutput(status="fail", error="Run not found")

        # Only run ACE for child agents (nodes with a parent)
        if not run.parent_run_id:
            return StageOutput(status="continue")

        child_ctx = run.child_context or {}
        task_type = child_ctx.get("role") or child_ctx.get("task_type") or "general"
        model_id = child_ctx.get("model") or input.context.get("model") or ""
        provider_type = input.context.get("provider_type") or "unknown"

        # Feedback from a previous NO-GO? Include it but still assess
        feedback = child_ctx.get("feedback")

        # --- 1. Historical capability from GICS ---
        hist_score, hist_reasoning = _assess_historical(provider_type, model_id, task_type)

        # --- 2. Context richness ---
        ctx_score, ctx_reasoning = _assess_context_richness(input.context, child_ctx)

        # --- 3. Scope estimation ---
        scope_score, scope_reasoning = _assess_scope(run.child_prompt or "", child_ctx)

        # --- 4. Sibling awareness ---
        sibling_outputs, sib_score, sib_reasoning = _gather_sibling_context(
            run.id, run.parent_run_id
        )

        # --- Compute confidence ---
        confidence = (
            hist_score * W_HISTORICAL
            + ctx_score * W_CONTEXT
            + scope_score * W_SCOPE
            + sib_score * W_SIBLING
        )
        confidence = round(max(0.0, min(1.0, confidence)), 3)

        # If we have feedback from a NO-GO, boost confidence slightly
        # (we have more context now)
        if feedback:
            confidence = min(1.0, confidence + 0.1)

        # --- Strategy selection ---
        thresholds = {**DEFAULT_THRESHOLDS, **(input.context.get("ace_thresholds") or {})}
        strategy = _select_strategy(confidence, thresholds)

        # --- Gap E: Prompt adaptation from failure history ---
        last_failure_reason = ""
        try:
            from ...services.capability_profile_service import CapabilityProfileService as _CPS
            cap = _CPS.get_capability(
                provider_type=provider_type, model_id=model_id, task_type=task_type,
            ) if model_id else None
            if cap and cap.last_failure_reason:
                last_failure_reason = cap.last_failure_reason
        except Exception:
            pass

        if last_failure_reason:
            current_prompt = input.context.get("prompt", "")
            input.context["prompt"] = (
                f"{current_prompt}\n\n"
                f"IMPORTANT: Previous attempts on similar tasks failed because: "
                f"{last_failure_reason}. Adjust your approach to avoid this."
            )

        # --- Log the full reasoning chain ---
        reasoning_lines = [
            f"[ACE] === Cognitive Self-Assessment for task '{child_ctx.get('task_id', '?')}' ===",
            f"[ACE] Model: {model_id} | Task type: {task_type} | Depth: {run.spawn_depth}",
            f"[ACE] Historical ({W_HISTORICAL:.0%}): {hist_score:.2f} — {hist_reasoning}",
            f"[ACE] Context   ({W_CONTEXT:.0%}): {ctx_score:.2f} — {ctx_reasoning}",
            f"[ACE] Scope     ({W_SCOPE:.0%}): {scope_score:.2f} — {scope_reasoning}",
            f"[ACE] Siblings  ({W_SIBLING:.0%}): {sib_score:.2f} — {sib_reasoning}",
        ]
        if feedback:
            reasoning_lines.append(f"[ACE] Feedback from NO-GO: {feedback[:200]}")
            reasoning_lines.append(f"[ACE] Confidence boosted +0.1 due to feedback context")
        reasoning_lines.append(f"[ACE] ── Confidence: {confidence} ── Strategy: {strategy.upper()} ──")

        for line in reasoning_lines:
            OpsService.append_log(input.run_id, level="INFO", msg=line)

        # --- Act on strategy ---
        artifacts = {
            "ace_confidence": confidence,
            "ace_strategy": strategy,
            "ace_task_type": task_type,
            "ace_model_id": model_id,
        }

        if strategy == "enrich_context":
            # Inject sibling outputs into the prompt so the LLM has more context
            if sibling_outputs:
                enrichment = _format_sibling_enrichment(sibling_outputs)
                current_prompt = input.context.get("prompt", "")
                input.context["prompt"] = f"{current_prompt}\n\n{enrichment}"
                OpsService.append_log(
                    input.run_id, level="INFO",
                    msg=f"[ACE] Enriched prompt with {len(sibling_outputs)} sibling output(s)"
                )
            return StageOutput(status="continue", artifacts=artifacts)

        elif strategy == "multi_pass":
            # Set multi-pass flag so LlmExecute runs multiple iterations
            input.context["ace_multi_pass"] = True
            input.context["ace_max_passes"] = int(input.context.get("ace_max_passes", 3))
            # Also enrich with siblings if available
            if sibling_outputs:
                enrichment = _format_sibling_enrichment(sibling_outputs)
                current_prompt = input.context.get("prompt", "")
                input.context["prompt"] = f"{current_prompt}\n\n{enrichment}"
            OpsService.append_log(
                input.run_id, level="INFO",
                msg=f"[ACE] Multi-pass mode: up to {input.context['ace_max_passes']} iterations"
            )
            return StageOutput(status="continue", artifacts=artifacts)

        elif strategy == "subdivide":
            # The agent autonomously decides to decompose its task
            # Inject a decomposition prompt: ask the LLM to split the task
            decomp_prompt = (
                f"IMPORTANT — DECOMPOSITION MODE:\n"
                f"You have been assessed as having LOW confidence ({confidence}) "
                f"for this task type ('{task_type}').\n"
                f"Instead of attempting the full task directly, you MUST:\n"
                f"1. Analyze the task and break it into 2-4 smaller, independent subtasks\n"
                f"2. Output ONLY a JSON array of subtasks, each with: "
                f'{{"id": "sub_N", "prompt": "...", "role": "{task_type}", "depends_on": []}}\n'
                f"3. Do NOT attempt to execute the task itself\n\n"
                f"Original task:\n{run.child_prompt or input.context.get('prompt', '')}"
            )
            input.context["prompt"] = decomp_prompt
            input.context["ace_subdivide_mode"] = True
            OpsService.append_log(
                input.run_id, level="INFO",
                msg="[ACE] Subdivide mode: asking LLM to decompose task into subtasks"
            )
            return StageOutput(status="continue", artifacts=artifacts)

        elif strategy == "escalate":
            # Confidence too low — escalate to orchestrator
            reason = (
                f"ACE confidence {confidence} is below escalation threshold. "
                f"Model '{model_id}' has insufficient capability for task type '{task_type}'. "
                f"Historical: {hist_reasoning}"
            )
            OpsService.append_log(
                input.run_id, level="WARN",
                msg=f"[ACE] ESCALATING: {reason}"
            )
            # Record failure in capability profile
            try:
                from ...services.capability_profile_service import CapabilityProfileService
                CapabilityProfileService.record_task_outcome(
                    provider_type=provider_type,
                    model_id=model_id,
                    task_type=task_type,
                    success=False,
                    failure_reason="ACE pre-flight escalation: confidence too low",
                )
            except Exception:
                pass

            # Emit escalation via the spawn_agents mechanism
            from .spawn_agents import _emit_escalation
            await _emit_escalation(input.run_id, reason, input.context)

            OpsService.update_run_status(
                input.run_id, "awaiting_review",
                msg=f"ACE escalation: confidence {confidence}. Awaiting orchestrator."
            )
            return StageOutput(status="halt", artifacts=artifacts)

        else:  # direct_execute
            # High confidence — proceed normally
            if sibling_outputs:
                # Still enrich even on direct execute (free context)
                enrichment = _format_sibling_enrichment(sibling_outputs)
                current_prompt = input.context.get("prompt", "")
                input.context["prompt"] = f"{current_prompt}\n\n{enrichment}"
            return StageOutput(status="continue", artifacts=artifacts)

    async def rollback(self, input: StageInput) -> None:
        pass


# ---------------------------------------------------------------------------
# Assessment sub-functions
# ---------------------------------------------------------------------------

def _assess_historical(
    provider_type: str, model_id: str, task_type: str,
) -> tuple[float, str]:
    """Query GICS for this model's historical performance on this task type."""
    if not model_id:
        return 0.5, "No model specified, using neutral baseline"

    try:
        from ...services.capability_profile_service import CapabilityProfileService
        cap = CapabilityProfileService.get_capability(
            provider_type=provider_type, model_id=model_id, task_type=task_type,
        )
        if not cap or cap.samples == 0:
            return 0.5, f"No historical data for '{model_id}' on '{task_type}' (first attempt)"

        reasoning = (
            f"{cap.successes}/{cap.samples} successes ({cap.success_rate:.0%}) "
            f"on '{task_type}'"
        )
        if cap.failure_streak >= 2:
            reasoning += f" [ALERT: {cap.failure_streak} consecutive failures]"
        if cap.last_failure_reason:
            reasoning += f" [Last failure: {cap.last_failure_reason[:80]}]"

        score = cap.success_rate
        # Penalize active failure streaks
        if cap.failure_streak >= 3:
            score *= 0.5
        elif cap.failure_streak >= 2:
            score *= 0.7

        return max(0.0, min(1.0, score)), reasoning

    except Exception as exc:
        return 0.5, f"GICS unavailable ({exc}), using neutral baseline"


def _assess_context_richness(
    pipeline_ctx: Dict[str, Any],
    child_ctx: Dict[str, Any],
) -> tuple[float, str]:
    """Score how well-specified the task is. More context = higher confidence."""
    signals = 0
    max_signals = 7

    prompt = pipeline_ctx.get("prompt", "")
    if len(prompt) > 100:
        signals += 1  # Decent prompt length
    if len(prompt) > 500:
        signals += 1  # Very detailed prompt

    if child_ctx.get("target_path") or child_ctx.get("target_file"):
        signals += 1  # Explicit output target

    if child_ctx.get("feedback"):
        signals += 1  # Has refinement feedback

    if pipeline_ctx.get("workspace_root") or pipeline_ctx.get("repo_root"):
        signals += 1  # Workspace grounded

    if child_ctx.get("depends_on"):
        signals += 1  # Has dependency chain (structured)

    if child_ctx.get("acceptance_criteria") or pipeline_ctx.get("acceptance_criteria"):
        signals += 1  # Clear success criteria

    score = signals / max_signals
    return score, f"{signals}/{max_signals} context signals present"


def _assess_scope(prompt: str, child_ctx: Dict[str, Any]) -> tuple[float, str]:
    """Estimate task scope from prompt keywords. Smaller scope = higher confidence."""
    scope_indicators = {
        "large": ["refactor", "rewrite", "redesign", "migrate", "overhaul",
                   "entire", "complete", "full", "all files", "whole"],
        "medium": ["implement", "create", "build", "develop", "add feature",
                    "integrate", "architecture"],
        "small": ["fix", "update", "modify", "change", "rename", "add test",
                   "document", "comment", "format", "lint"],
    }

    combined = f"{prompt} {child_ctx.get('role', '')}".lower()

    for indicator in scope_indicators["small"]:
        if indicator in combined:
            return 0.9, f"Small scope detected ('{indicator}')"

    for indicator in scope_indicators["large"]:
        if indicator in combined:
            return 0.3, f"Large scope detected ('{indicator}')"

    for indicator in scope_indicators["medium"]:
        if indicator in combined:
            return 0.6, f"Medium scope detected ('{indicator}')"

    # Count file references as scope proxy
    file_refs = len(re.findall(r'\.\w{1,5}\b', prompt))
    if file_refs > 5:
        return 0.4, f"Multiple file references ({file_refs}) suggest broad scope"
    if file_refs > 2:
        return 0.6, f"Some file references ({file_refs})"

    return 0.7, "Scope unclear, assuming moderate"


def _gather_sibling_context(
    run_id: str,
    parent_run_id: str,
) -> tuple[List[Dict[str, Any]], float, str]:
    """Find completed sibling runs and extract their outputs for cross-pollination."""
    from ...services.ops_service import OpsService

    parent = OpsService.get_run(parent_run_id)
    if not parent:
        return [], 0.5, "No parent found"

    sibling_outputs = []
    for sib_id in parent.child_run_ids:
        if sib_id == run_id:
            continue
        sib = OpsService.get_run(sib_id)
        if not sib or sib.status != "done":
            continue
        sib_ctx = sib.child_context or {}

        # Extract output summary from sibling's logs
        output_summary = _extract_run_output(sib_id)
        if output_summary:
            sibling_outputs.append({
                "task_id": sib_ctx.get("task_id", sib_id),
                "role": sib_ctx.get("role", "unknown"),
                "output": output_summary,
            })

    if not sibling_outputs:
        return [], 0.5, "No completed siblings available"

    # More sibling context = higher confidence boost
    score = min(1.0, 0.5 + len(sibling_outputs) * 0.2)
    return (
        sibling_outputs,
        score,
        f"{len(sibling_outputs)} completed sibling(s) available for cross-pollination",
    )


def _extract_run_output(run_id: str) -> Optional[str]:
    """Extract the substantive output from a completed run's logs."""
    from ...services.ops_service import OpsService

    run = OpsService.get_run(run_id)
    logs = run.log if run else None
    if not logs:
        return None

    # Look for file write confirmations or LLM result content
    output_parts = []
    for entry in reversed(logs):
        msg = entry.get("msg", "")
        if "File written" in msg or "LLM result:" in msg or "written →" in msg:
            output_parts.append(msg[:500])
        if "ExecutorReport:" in msg:
            output_parts.append(msg[:300])
        if len(output_parts) >= 3:
            break

    return "\n".join(reversed(output_parts)) if output_parts else None


def _format_sibling_enrichment(sibling_outputs: List[Dict[str, Any]]) -> str:
    """Format sibling outputs as additional context for the LLM prompt."""
    lines = ["=== CONTEXT FROM COMPLETED SIBLING AGENTS ==="]
    for sib in sibling_outputs:
        lines.append(f"\n--- {sib['role']} (task: {sib['task_id']}) ---")
        lines.append(sib["output"][:1000])
    lines.append("\n=== END SIBLING CONTEXT ===")
    lines.append("Use the above context to ensure consistency with your siblings' work.\n")
    return "\n".join(lines)


def _select_strategy(confidence: float, thresholds: Dict[str, float]) -> str:
    """Select execution strategy based on confidence score."""
    if confidence >= thresholds.get("direct_execute", 0.8):
        return "direct_execute"
    if confidence >= thresholds.get("enrich_context", 0.6):
        return "enrich_context"
    if confidence >= thresholds.get("multi_pass", 0.4):
        return "multi_pass"
    if confidence >= thresholds.get("subdivide", 0.2):
        return "subdivide"
    return "escalate"
