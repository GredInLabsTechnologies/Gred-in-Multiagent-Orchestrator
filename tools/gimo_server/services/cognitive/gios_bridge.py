from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

from .models import DetectedIntent, ExecutionPlanDraft, SecurityDecision


class GiosTfIdfIntentEngine:
    """
    Pure Python TF-IDF Semantic Intent Detector.
    Ports the core concept of GIOS (cosine similarity against a knowledge base)
    without heavyweight ML dependencies like Transformers/Torch.
    """

    def __init__(self) -> None:
        self.knowledge_base = {
            "HELP": [
                "help",
                "ayuda",
                "que puedes hacer",
                "qué puedes hacer",
                "dime tus comandos",
                "instrucciones",
                "como funcionas",
            ],
            "ASK_STATUS": [
                "status",
                "estado",
                "como va",
                "cómo va",
                "resumen",
                "dame un resumen",
                "hay algo pendiente",
                "dime el estado de los runs",
            ],
            "CREATE_PLAN": [
                "crea un plan",
                "crear plan",
                "plan tecnico",
                "plan técnico",
                "roadmap",
                "diseña un plan",
                "dame los pasos",
                "plan de accion",
                "plan de acción",
            ],
        }
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.intent_vectors: List[Dict[str, Any]] = []
        self._build_index()

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        # Remove punctuation, keep words
        words = re.findall(r"\b\w+\b", text)
        return [w for w in words if len(w) > 2 or w in {"va", "un"}]

    def _build_index(self) -> None:
        # Build vocabulary
        doc_count = 0
        word_doc_freq: Dict[str, set] = {}

        for intent, examples in self.knowledge_base.items():
            for idx, text in enumerate(examples):
                doc_id = f"{intent}_{idx}"
                doc_count += 1
                words = self._tokenize(text)
                for w in words:
                    if w not in self.vocabulary:
                        self.vocabulary[w] = len(self.vocabulary)
                    if w not in word_doc_freq:
                        word_doc_freq[w] = set()
                    word_doc_freq[w].add(doc_id)

        # Calculate IDF
        for word, doc_set in word_doc_freq.items():
            self.idf[word] = math.log((1 + doc_count) / (1 + len(doc_set))) + 1

        # Precompute vectors
        for intent, examples in self.knowledge_base.items():
            for text in examples:
                vector = self._vectorize(text)
                self.intent_vectors.append(
                    {"intent": intent, "text": text, "vector": vector}
                )

    def _vectorize(self, text: str) -> List[float]:
        words = self._tokenize(text)
        tf: Dict[str, float] = {}
        for w in words:
            tf[w] = tf.get(w, 0) + 1

        # TF-IDF
        vector = [0.0] * len(self.vocabulary)
        norm_sq = 0.0
        for w, count in tf.items():
            if w in self.vocabulary:
                idx = self.vocabulary[w]
                val = count * self.idf[w]
                vector[idx] = val
                norm_sq += val * val

        # Normalize (L2)
        norm = math.sqrt(norm_sq)
        if norm > 0:
            for i in range(len(vector)):
                vector[i] /= norm

        return vector

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        return sum(x * y for x, y in zip(v1, v2))

    def detect_intent(self, input_text: str, context: dict) -> DetectedIntent:
        if not input_text or not input_text.strip():
            return DetectedIntent(name="UNKNOWN", confidence=0.0, reason="empty_input")

        input_vector = self._vectorize(input_text)
        
        # If input has no recognizable words
        if sum(input_vector) == 0:
             return DetectedIntent(name="UNKNOWN", confidence=0.0, reason="no_known_words")

        best_intent = "UNKNOWN"
        best_score = 0.0
        best_example = ""

        # Find closest match
        for item in self.intent_vectors:
            score = self._cosine_similarity(input_vector, item["vector"])
            if score > best_score:
                best_score = score
                best_intent = item["intent"]
                best_example = item["text"]

        # Matches legacy GIOS THRESHOLD = 0.45
        if best_score >= 0.45:
            return DetectedIntent(
                name=best_intent,
                confidence=round(best_score, 3),
                reason=f"tfidf_matched: '{best_example}'",
            )

        return DetectedIntent(
            name="UNKNOWN",
            confidence=round(best_score, 3),
            reason="below_threshold",
        )


class GiosSecurityGuard:
    """
    Military-Grade Security Detector ported directly from legacy GIOS.
    Scans for adversarial inputs, prompt injection attempts, and jailbreaks.
    """

    _GIOS_LEGACY_THREATS = (
        "ignore all previous instructions",
        "ignore previous instructions",
        "forget your instructions",
        "you are now",
        "tu ahora eres",
        "actúa como un",
        "act as a",
        "system override",
        "developer mode",
        "modo desarrollador",
        "dan mode",
        "unfiltered",
    )

    def evaluate(self, input_text: str, context: dict) -> SecurityDecision:
        text = (input_text or "").lower()
        matched = [threat for threat in self._GIOS_LEGACY_THREATS if threat in text]
        if matched:
            return SecurityDecision(
                allowed=False,
                risk_level="high",
                reason="Detected prompt-injection/jailbreak pattern (GIOS)",
                flags=matched,
            )
        return SecurityDecision(allowed=True, risk_level="low", reason="clean_input", flags=[])


class GiosDirectResponseEngine:
    def can_bypass_llm(self, intent: DetectedIntent, context: dict) -> bool:
        return intent.name in {"ASK_STATUS", "HELP"}

    def build_execution_plan(self, intent: DetectedIntent, context: dict) -> ExecutionPlanDraft:
        prompt = (context.get("prompt") or "").strip()

        if intent.name == "HELP":
            return ExecutionPlanDraft(
                content=(
                    "🤖 **GIOS Bridge Activo**\n\n"
                    "Puedo ayudarte con:\n"
                    "- Crear planes técnicos detallados\n"
                    "- Consultar el estado del orquestador\n"
                    "- Guiarte para aprobar y ejecutar workflows\n\n"
                    "*(Respuesta directa sin consumo de LLM)*"
                ),
                metadata={"direct_response": True, "intent": intent.name, "engine": "gios_bridge"},
            )

        if intent.name == "ASK_STATUS":
            return ExecutionPlanDraft(
                content=(
                    "📊 **Estado del Sistema (GIOS Bridge)**\n\n"
                    "Verificando flujos... Revisa /ops/drafts y /ops/runs para ver los pendientes, "
                    "en ejecución y completados de manera detallada.\n\n"
                    "*(Respuesta directa sin consumo de LLM)*"
                ),
                metadata={"direct_response": True, "intent": intent.name, "engine": "gios_bridge"},
            )

        if intent.name == "CREATE_PLAN":
            trimmed = prompt[:500] if prompt else "(sin prompt)"
            return ExecutionPlanDraft(
                content=(
                    "📋 **PLAN PROPUESTO**\n"
                    "1) Analizar objetivo y restricciones\n"
                    "2) Diseñar arquitectura y contratos\n"
                    "3) Implementar por hitos\n"
                    "4) Validar con tests\n"
                    "5) Entregar evidencia\n\n"
                    f"*Contexto detectado:* {trimmed}"
                ),
                metadata={"direct_response": False, "intent": intent.name, "engine": "gios_bridge"},
            )

        return ExecutionPlanDraft(
            content="No tengo una respuesta directa para este caso. Se redirigirá al LLM.",
            metadata={"direct_response": False, "intent": intent.name, "engine": "gios_bridge"},
        )
