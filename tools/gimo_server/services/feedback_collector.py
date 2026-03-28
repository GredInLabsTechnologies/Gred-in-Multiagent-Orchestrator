"""FeedbackCollector — Unifies multiple quality signals into canonical score.

F8.3: Combina quality scores automáticos (heurísticos) con feedback manual del usuario
para crear un score unificado que alimenta el sistema de telemetría.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("orchestrator.services.feedback_collector")


class FeedbackCollector:
    """Unifies multiple quality signals into a canonical score.

    Fuentes de quality:
    - Auto-heuristic: QualityService.analyze_output() (BAJA confiabilidad)
    - Execution success: node.error is None (MEDIA confiabilidad, binario)
    - User feedback: Manual post-ejecución (ALTA confiabilidad, ground truth)
    - Confidence score: ConfidenceService (MEDIA confiabilidad, predictivo)

    Ponderación:
    - User feedback tiene peso 1.0 (máximo)
    - Execution success tiene peso 0.4-0.5
    - Auto-heuristic tiene peso 0.3
    - Confidence score tiene peso 0.2
    """

    @classmethod
    def compute_unified_quality(
        cls,
        auto_quality_score: Optional[float],  # 0-100 desde QualityService
        execution_success: bool,  # node.error is None
        user_feedback: Optional[float] = None,  # 0-100 manual
        confidence_score: Optional[float] = None,  # 0-1 predictivo
    ) -> Tuple[float, Dict[str, Any]]:
        """Calcula quality score unificado ponderando señales.

        Args:
            auto_quality_score: Score automático 0-100 desde QualityService
            execution_success: True si la ejecución fue exitosa (sin errores)
            user_feedback: Score manual 0-100 del usuario (opcional)
            confidence_score: Score 0-1 de ConfidenceService (opcional)

        Returns:
            (unified_score, metadata)
            unified_score: 0-100 ponderado
            metadata: Dict con detalles de las fuentes usadas
        """
        scores = []
        weights = []

        # 1. Auto-heuristic (peso bajo)
        if auto_quality_score is not None:
            scores.append(auto_quality_score)
            weights.append(0.3)

        # 2. Execution success (peso medio, binario)
        if execution_success:
            scores.append(80.0)  # Success implica calidad aceptable
            weights.append(0.4)
        else:
            scores.append(20.0)  # Failure implica baja calidad
            weights.append(0.5)  # Más peso a failure

        # 3. User feedback (peso MÁXIMO si disponible)
        if user_feedback is not None:
            scores.append(user_feedback)
            weights.append(1.0)  # Ground truth

        # 4. Confidence score (peso bajo, predictivo)
        if confidence_score is not None:
            # Convertir 0-1 a 0-100
            scores.append(confidence_score * 100.0)
            weights.append(0.2)

        # Calcular weighted average
        total_weight = sum(weights)
        unified_score = sum(s * w for s, w in zip(scores, weights)) / total_weight

        metadata = {
            "sources_used": len(scores),
            "has_user_feedback": user_feedback is not None,
            "execution_success": execution_success,
            "auto_quality": auto_quality_score,
            "confidence": confidence_score,
            "user_feedback": user_feedback,
        }

        logger.debug(
            "Unified quality: %.2f (sources=%d, user_feedback=%s)",
            unified_score,
            len(scores),
            user_feedback is not None,
        )

        return unified_score, metadata

    @classmethod
    def record_user_feedback(
        cls,
        workflow_id: str,
        node_id: str,
        feedback_score: float,  # 0-100 or 1-5 stars convertido
        feedback_text: Optional[str] = None,
    ) -> None:
        """Registra feedback manual del usuario en GICS.

        Args:
            workflow_id: ID del workflow/plan
            node_id: ID del nodo ejecutado
            feedback_score: Score 0-100 (o 1-5 convertido a 0-100)
            feedback_text: Comentario opcional del usuario
        """
        from ..services.gics_service import GicsService

        key = f"ops:user_feedback:{workflow_id}:{node_id}"
        GicsService.put(
            key,
            {
                "workflow_id": workflow_id,
                "node_id": node_id,
                "score": feedback_score,
                "text": feedback_text,
                "timestamp": time.time(),
            },
        )

        logger.info(
            "Recorded user feedback: workflow=%s, node=%s, score=%.2f",
            workflow_id,
            node_id,
            feedback_score,
        )

    @classmethod
    def get_user_feedback(
        cls,
        workflow_id: str,
        node_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Obtiene user feedback registrado para un nodo."""
        from ..services.gics_service import GicsService

        key = f"ops:user_feedback:{workflow_id}:{node_id}"
        return GicsService.get(key)
