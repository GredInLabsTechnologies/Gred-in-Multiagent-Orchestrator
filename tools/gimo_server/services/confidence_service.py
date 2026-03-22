from __future__ import annotations

import json
import logging
from typing import Any, Dict

from .trust_engine import TrustEngine

logger = logging.getLogger("orchestrator.services.confidence")

class ConfidenceService:
    """Evaluates AI confidence for tasks using TrustEngine metrics."""

    def __init__(self, trust_engine: TrustEngine):
        self.trust_engine = trust_engine

    def get_confidence_score(self, dimension_key: str) -> Dict[str, Any]:
        """
        Calculates a confidence score (0.0 to 1.0) for a given dimension.
        Returns score, reasoning and historical markers.
        """
        record = self.trust_engine.query_dimension(dimension_key)
        
        trust_score = record.get("score", 0.0)
        streak = record.get("streak", 0)
        approvals = record.get("approvals", 0)
        failures = record.get("failures", 0)
        
        # Confidence logic:
        # Base: TrustEngine score (which already considers approvals/rejections)
        # Bonus: Small bonus for long streaks
        # Penalty: Heavy penalty if there are recent failures (streak reset)
        
        confidence = trust_score
        
        # Streak bonus (max 0.1)
        streak_bonus = min(streak * 0.02, 0.1)
        confidence += streak_bonus
        
        # Failure penalty if high failure rate
        total_attempts = approvals + record.get("rejections", 0) + failures
        if total_attempts > 0:
            failure_rate = failures / total_attempts
            if failure_rate > 0.2:
                confidence *= (1.0 - failure_rate)

        final_score = max(0.0, min(1.0, confidence))
        
        return {
            "score": round(final_score, 4),
            "percentage": f"{round(final_score * 100, 1)}%",
            "level": self._get_confidence_level(final_score),
            "reason": f"Basado en {approvals} aprobaciones y racha de {streak}.",
            "dimension": dimension_key
        }

    def _get_confidence_level(self, score: float) -> str:
        if score >= 0.9: return "High"
        if score >= 0.7: return "Strong"
        if score >= 0.5: return "Moderate"
        if score >= 0.3: return "Low"
        return "Critical"

    async def project_confidence(self, description: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        [NEW] Proactive self-evaluation using LLM to detect ambiguity and risk.
        Evaluates the task before execution.
        """
        from .provider_service import ProviderService

        prompt = f"""
        Analyze the following task and context to determine if you have enough information to execute it successfully.
        
        TASK DESCRIPTION:
        {description}
        
        CONTEXT DATA:
        {json.dumps(context, indent=2)}
        
        EVALUATION CRITERIA:
        1. Ambiguity: Are the instructions clear and specific?
        2. Missing Information: Are there required files, parameters or context data missing?
        3. Risk: Is this a high-risk operation (e.g. data deletion, system change) that requires extra caution?
        
        RESPONSE FORMAT (JSON ONLY):
        {{
            "confidence": float (0.0 to 1.0),
            "analysis": "Brief explanation of the score",
            "questions": ["Specific questions for the user if confidence < 0.8", ...],
            "risk_level": "low" | "medium" | "high"
        }}
        """
        
        try:
            # Use default provider
            resp = await ProviderService.static_generate(prompt, {"system_prompt": "You are an AI quality assurance agent."})
            response_text = resp["content"]
            
            # Clean response text if model returns markdown
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(response_text)
            
            # Ensure fields exist
            data.setdefault("confidence", 0.5)
            data.setdefault("analysis", "No analysis provided")
            data.setdefault("questions", [])
            data.setdefault("risk_level", "medium")
            
            return {
                "score": float(data["confidence"]),
                "analysis": str(data["analysis"]),
                "questions": list(data["questions"]),
                "risk_level": str(data["risk_level"]),
                "type": "proactive"
            }
        except Exception as e:
            logger.error(f"Error in project_confidence: {e}")
            return {
                "score": 0.5,
                "analysis": f"Evaluación fallida: {str(e)}",
                "questions": ["¿Puedes confirmar los detalles de la tarea?"],
                "risk_level": "unknown",
                "type": "proactive_fallback"
            }
