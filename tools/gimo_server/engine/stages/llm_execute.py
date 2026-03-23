from __future__ import annotations
from ..contracts import StageInput, StageOutput, ExecutionStage
from ...services.provider_service import ProviderService

# Hard upper bound on multi-pass iterations to prevent context-injection amplification.
_ACE_MAX_PASSES_CEILING = 10

class LlmExecute(ExecutionStage):
    @property
    def name(self) -> str:
        return "llm_execute"

    async def execute(self, input: StageInput) -> StageOutput:
        prompt = input.context.get("prompt")
        if not prompt:
            return StageOutput(status="fail", artifacts={"error": "Missing prompt in context"})

        gen_context = input.context.get("gen_context", {})
        multi_pass = input.context.get("ace_multi_pass", False)
        raw_passes = int(input.context.get("ace_max_passes", 3)) if multi_pass else 1
        max_passes = min(raw_passes, _ACE_MAX_PASSES_CEILING)

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
                        from ...services.ops_service import OpsService
                        OpsService.append_log(
                            input.run_id, level="INFO",
                            msg=f"[LlmExecute] Multi-pass {pass_num}/{max_passes}: critic severity={verdict.severity}, retrying"
                        )
                    except Exception:
                        pass
                except Exception:
                    break  # Critic unavailable — accept current output

            return StageOutput(
                status="continue",
                artifacts={
                    "llm_response": final_resp,
                    "content": final_resp.get("content", ""),
                    "usage": {
                        "prompt_tokens": final_resp.get("prompt_tokens"),
                        "completion_tokens": final_resp.get("completion_tokens"),
                        "cost_usd": final_resp.get("cost_usd"),
                    },
                },
            )
        except Exception as e:
            return StageOutput(status="fail", artifacts={"error": str(e)})

    async def rollback(self, input: StageInput) -> None:
        """LLM execution is stateless, nothing to rollback."""
        pass

