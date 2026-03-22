import json
from typing import Optional
from ..ops_models import QualityRating

class QualityService:
    """Service for evaluating LLM output quality based on heuristics."""

    ERROR_PHRASES = [
        "i'm sorry",
        "i cannot",
        "as an ai model",
        "as a large language model",
        "i apologize",
        "request failed",
        "invalid request",
        "error:",
    ]

    @staticmethod
    def analyze_output(text: str, task_type: Optional[str] = None, expected_format: Optional[str] = None) -> QualityRating:
        """
        Analyzes the quality of LLM output using several heuristics.
        
        Args:
            text: The raw output text from the LLM.
            task_type: Optional hint about the task (e.g., "code_generation", "classification").
            expected_format: Optional hint about expected format (e.g., "json").
            
        Returns:
            QualityRating with score and alerts.
        """
        if not text or not text.strip():
            return QualityRating(score=0, alerts=["empty_output"], heuristics={"is_empty": True})

        alerts = []
        heuristics = {
            "is_empty": False,
            "has_error_phrase": False,
            "invalid_json": False,
            "too_short": False,
            "high_repetition": False
        }

        # 1. Error Phrase Detection
        lower_text = text.lower()
        for phrase in QualityService.ERROR_PHRASES:
            if phrase in lower_text:
                alerts.append(f"error_phrase_detected: {phrase}")
                heuristics["has_error_phrase"] = True
                break

        # Detect refusal/apology patterns
        # Enhanced list based on common LLM refusal behaviors
        if any(p in lower_text for p in [
            "i cannot fulfill", "i cannot answer", "i cannot provide",
            "i cannot generate", "i'm unable to", "i am unable to",
            "as an ai", "as a language model", "content policy",
            "against my programming"
        ]):
             alerts.append("refusal_detected")
             heuristics["has_error_phrase"] = True

        # 2. JSON Validation
        # Check against explicitly requested json format OR implied by task type
        if expected_format == "json" or task_type in ["classification", "extraction", "structured_data"]:
            try:
                # robust extraction: find first { and last }
                if "{" in text and "}" in text:
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    json_candidate = text[start:end]
                    json.loads(json_candidate)
                else:
                    raise ValueError("No JSON object found")
            except Exception:
                # Fallback: try to find array [ ... ]
                try:
                    if "[" in text and "]" in text:
                        start = text.find("[")
                        end = text.rfind("]") + 1
                        json_candidate = text[start:end]
                        json.loads(json_candidate)
                    else:
                        raise
                except Exception:
                    alerts.append("invalid_json_format")
                    heuristics["invalid_json"] = True

        # 3. Length Check
        # For simple tasks like classification, length doesn't matter much.
        # But for code_generation or creative writing, it might.
        if task_type in ["code_generation", "formatting"] and len(text.strip()) < 20:
            alerts.append("suspiciously_short")
            heuristics["too_short"] = True

        # 4. Repetition Detection
        words = lower_text.split()
        if len(words) > 30:
            # Simple ngram check
            phrases = [" ".join(words[i:i+4]) for i in range(len(words)-4)]
            if len(phrases) > 0:
                unique_pct = len(set(phrases)) / len(phrases)
                if unique_pct < 0.6: # More than 40% repetitive ngrams
                    alerts.append("high_repetition_rate")
                    heuristics["high_repetition"] = True

        # Calculate score (Base 100)
        score = 100
        if heuristics["has_error_phrase"]:
            score -= 60
        if heuristics["invalid_json"]:
            score -= 40
        if heuristics["too_short"]:
            score -= 20
        if heuristics["high_repetition"]:
            score -= 30
        if not text.strip():
            score = 0

        return QualityRating(
            score=max(0, score),
            alerts=alerts,
            heuristics=heuristics
        )
