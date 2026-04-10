from __future__ import annotations
import time
import uuid
from ..contracts import StageInput, StageOutput, ExecutionStage
from ...models.economy import CostEvent
from ...models.policy import TrustEvent
from ...services.providers.service import ProviderService
from ...services.observability_pkg.observability_service import ObservabilityService
from ...services.ops import OpsService
from ...services.storage_service import StorageService

# Hard upper bound on multi-pass iterations to prevent context-injection amplification.
_ACE_MAX_PASSES_CEILING = 10

class LlmExecute(ExecutionStage):
    @property
    def name(self) -> str:
        return "llm_execute"

    @staticmethod
    def _task_type(context: dict) -> str:
        if context.get("target_path") or context.get("target_file"):
            return "file_task"
        if context.get("custom_plan_id"):
            return "custom_plan"
        return str(context.get("execution_mode") or "run")

    @classmethod
    def _record_run_evidence(
        cls,
        *,
        input: StageInput,
        response: dict,
        duration_ms: int,
        status: str,
    ) -> None:
        provider_id = str(response.get("provider") or "").strip()
        model = str(response.get("model") or "unknown")
        prompt_tokens = int(response.get("prompt_tokens") or 0)
        completion_tokens = int(response.get("completion_tokens") or 0)
        total_tokens = int(response.get("tokens_used") or (prompt_tokens + completion_tokens))
        cost_usd = float(response.get("cost_usd") or 0.0)
        request_id = f"runreq_{uuid.uuid4().hex[:12]}"
        trace_id = str(input.context.get("trace_id") or uuid.uuid4().hex)

        provider_type = provider_id or "unknown"
        auth_mode = ""
        try:
            cfg = ProviderService.get_config()
            if cfg and provider_id and provider_id in cfg.providers:
                entry = cfg.providers[provider_id]
                provider_type = str(getattr(entry, "provider_type", None) or getattr(entry, "type", None) or provider_id)
                auth_mode = str(getattr(entry, "auth_mode", None) or "")
        except Exception:
            pass

        task_type = cls._task_type(input.context)
        step_id = f"{input.run_id}:{cls().name}"
        try:
            ObservabilityService.record_workflow_start(input.run_id, trace_id)
            ObservabilityService.record_node_span(
                workflow_id=input.run_id,
                trace_id=trace_id,
                step_id=step_id,
                node_id=cls().name,
                node_type=cls().name,
                status=status,
                duration_ms=duration_ms,
                tokens_used=total_tokens,
                cost_usd=cost_usd,
            )
            ObservabilityService.record_ai_usage(
                run_id=input.run_id,
                draft_id="",
                provider_type=provider_type,
                auth_mode=auth_mode,
                model=model,
                tokens_in=prompt_tokens,
                tokens_out=completion_tokens,
                cost_usd=cost_usd,
                status=status,
                latency_ms=float(duration_ms),
                request_id=request_id,
                error_code="" if status == "completed" else status,
            )
            ObservabilityService.record_workflow_end(input.run_id, trace_id, status=status)
        except Exception:
            pass

        try:
            storage = StorageService()
            storage.cost.save_cost_event(
                CostEvent(
                    id=uuid.uuid4().hex,
                    workflow_id=input.run_id,
                    node_id=cls().name,
                    model=model,
                    provider=provider_type,
                    task_type=task_type,
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    duration_ms=duration_ms,
                )
            )
            storage.save_trust_event(
                TrustEvent(
                    dimension_key=f"model:{provider_type}:{model}",
                    tool=cls().name,
                    context=task_type,
                    model=model,
                    task_type=task_type,
                    outcome="approved" if status == "completed" else "error",
                    actor=f"run:{input.run_id}",
                    post_check_passed=status == "completed",
                    duration_ms=duration_ms,
                    tokens_used=total_tokens,
                    cost_usd=cost_usd,
                )
            )
            OpsService.record_model_outcome(
                provider_type=provider_type,
                model_id=model,
                success=status == "completed",
                latency_ms=duration_ms,
                cost_usd=cost_usd,
                task_type=task_type,
            )
        except Exception:
            pass

    async def execute(self, input: StageInput) -> StageOutput:
        prompt = input.context.get("prompt")
        if not prompt:
            return StageOutput(status="fail", artifacts={"error": "Missing prompt in context"}, error="Missing prompt in context")

        gen_context = dict(input.context.get("gen_context", {}) or {})
        # Propagate provider/model routing from the run context into gen_context
        # so _resolve_effective_provider_and_model honours target_agent selection.
        for _routing_key in ("provider", "model", "selected_provider", "selected_model"):
            if _routing_key not in gen_context and _routing_key in input.context:
                gen_context[_routing_key] = input.context[_routing_key]
        multi_pass = input.context.get("ace_multi_pass", False)
        raw_passes = int(input.context.get("ace_max_passes", 3)) if multi_pass else 1
        max_passes = min(raw_passes, _ACE_MAX_PASSES_CEILING)
        started_at = time.perf_counter()

        try:
            current_prompt = prompt
            final_resp = None

            for pass_num in range(1, max_passes + 1):
                resp = await ProviderService.static_generate(
                    prompt=current_prompt,
                    context=gen_context,
                )
                content = resp.get("content", "")
                final_resp = resp

                if not multi_pass or pass_num >= max_passes:
                    break

                # Evaluate quality with CriticService
                try:
                    from ...services.critic_service import CriticService
                    verdict = await CriticService.evaluate(content, input.context)
                    if verdict.approved:
                        break
                    # Append critic feedback to prompt for next pass
                    issues_str = "; ".join(verdict.issues) if verdict.issues else "quality insufficient"
                    current_prompt = (
                        f"{prompt}\n\n"
                        f"[CRITIC PASS {pass_num} FEEDBACK — severity: {verdict.severity}]: "
                        f"{issues_str}\n"
                        f"Previous output:\n{content}\n\n"
                        f"Please revise your output addressing the above issues."
                    )
                    try:
                        # Module-level OpsService import is reused; do NOT
                        # re-import here — a local `from ... import` would
                        # rebind OpsService as a local for the entire
                        # function and cause the post-loop routing_snapshot
                        # block to UnboundLocalError when multi_pass=False
                        # short-circuits before this line ever runs.
                        OpsService.append_log(
                            input.run_id, level="INFO",
                            msg=f"[LlmExecute] Multi-pass {pass_num}/{max_passes}: critic severity={verdict.severity}, retrying"
                        )
                    except Exception:
                        pass
                except Exception:
                    break  # Critic unavailable — accept current output

            content = final_resp.get("content", "")
            if not content or not content.strip():
                return StageOutput(
                    status="fail",
                    artifacts={"error": "LLM returned empty content"},
                    error="LLM returned empty content",
                )

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            self._record_run_evidence(
                input=input,
                response=final_resp,
                duration_ms=duration_ms,
                status="completed",
            )

            # R20-006: persist the resolved routing snapshot onto the run
            # record. Previously only spawn_via_draft wrote routing_snapshot;
            # prompt-based runs (top-level chats, CLI drafts, MCP drafts)
            # left it null because RunWorker/EngineService never projected
            # the resolved provider/model back to OpsRun. We do it here
            # because this is the first place the resolved binding is
            # concrete for the prompt-based path. Failure is non-fatal.
            try:
                _run_routing_snapshot = {
                    "provider": str(final_resp.get("provider") or "").strip() or None,
                    "model": str(final_resp.get("model") or "").strip() or None,
                    "cost_usd": float(final_resp.get("cost_usd") or 0.0),
                    "tokens_used": int(final_resp.get("tokens_used") or 0),
                    "resolved_by": "llm_execute",
                    "execution_policy": str(input.context.get("execution_policy_name") or ""),
                }
                if _run_routing_snapshot["provider"] and _run_routing_snapshot["model"]:
                    OpsService.merge_run_meta(
                        input.run_id,
                        routing_snapshot=_run_routing_snapshot,
                        execution_policy_name=(
                            str(input.context.get("execution_policy_name") or "")
                            or None
                        ),
                    )
            except Exception:
                pass

            return StageOutput(
                status="continue",
                artifacts={
                    "llm_response": final_resp,
                    "content": content,
                    "usage": {
                        "prompt_tokens": final_resp.get("prompt_tokens"),
                        "completion_tokens": final_resp.get("completion_tokens"),
                        "cost_usd": final_resp.get("cost_usd"),
                    },
                },
            )
        except Exception as e:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            self._record_run_evidence(
                input=input,
                response={
                    "provider": "",
                    "model": "unknown",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "tokens_used": 0,
                    "cost_usd": 0.0,
                },
                duration_ms=duration_ms,
                status="failed",
            )
            return StageOutput(status="fail", artifacts={"error": str(e)}, error=str(e))

    async def rollback(self, input: StageInput) -> None:
        """LLM execution is stateless, nothing to rollback."""
        pass

