from __future__ import annotations
from ..contracts import StageInput, StageOutput
from ...services.critic_service import CriticService

class Critic:
    name = "critic"

    async def execute(self, input: StageInput) -> StageOutput:
        # Reuses CriticService to review output
        content = input.artifacts.get("content")
        if not content:
            return StageOutput(status="continue")
            
        try:
            review = await CriticService.review_output(content)
            
            if review.get("passed"):
                return StageOutput(status="continue", artifacts={"critic_review": review})
            else:
                return StageOutput(status="retry", artifacts={"critic_review": review})
        except Exception as e:
            return StageOutput(status="continue", artifacts={"critic_error": str(e)}) # Fallback to continue on critic error

    async def rollback(self, input: StageInput) -> None:
        pass
