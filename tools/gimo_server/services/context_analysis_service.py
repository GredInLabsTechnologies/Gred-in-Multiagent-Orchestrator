"""ContextAnalysisService — Analiza patterns temporales en workspace events.

P9: Detecta file sequences, focus clusters y computa temporal decay weights.
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.context_analysis")


class ContextAnalysisService:
    """Analiza patterns en workspace events para context-aware routing."""

    @classmethod
    def compute_temporal_weight(cls, last_access_at: float) -> float:
        """Exponential decay: recent files tienen más peso.

        Weight formula:
          w(t) = e^(-λt) donde t = (now - last_access) / 3600 (horas)
          λ = 0.1 (decay rate)

        Ejemplos:
          - Archivo accedido hace 5 min: w = e^(-0.1 * 5/60) ≈ 0.99
          - Archivo accedido hace 1 hora: w = e^(-0.1 * 1) ≈ 0.90
          - Archivo accedido hace 10 horas: w = e^(-0.1 * 10) ≈ 0.37
        """
        now = time.time()
        hours_since = (now - last_access_at) / 3600.0
        decay_rate = 0.1
        weight = math.exp(-decay_rate * hours_since)
        return max(0.01, min(1.0, weight))  # Clamp [0.01, 1.0]

    @classmethod
    def detect_file_sequences(
        cls,
        events: List[Dict[str, Any]],
        min_support: int = 3,
        max_gap_seconds: int = 300,
    ) -> List[Dict[str, Any]]:
        """Detecta secuencias frecuentes de file opens.

        Algoritmo: Apriori-like frequent itemset mining
        - Extrae secuencias de file_open events con gap < 5 min
        - Cuenta occurrences de cada secuencia
        - Retorna secuencias con support ≥ min_support

        Args:
            events: Lista de eventos (debe tener event_type, file_path, timestamp)
            min_support: Mínimo número de occurrences
            max_gap_seconds: Máximo gap entre eventos consecutivos

        Returns:
            Lista de secuencias detectadas:
            [
                {
                    "sequence": ["model.py", "test_model.py", "conftest.py"],
                    "occurrences": 5,
                    "confidence": 0.8,
                    "last_seen_at": timestamp,
                },
                ...
            ]
        """
        # Filtrar solo file_open events
        file_opens = [
            e for e in events
            if e.get("event_type") == "file_open"
        ]

        if len(file_opens) < min_support:
            return []

        # Construir secuencias candidatas
        sequences = []
        current_seq = []
        last_timestamp = None

        for event in sorted(file_opens, key=lambda x: x["timestamp"]):
            if last_timestamp is None or (event["timestamp"] - last_timestamp) <= max_gap_seconds:
                current_seq.append(event["file_path"])
                last_timestamp = event["timestamp"]
            else:
                # Gap demasiado grande, empezar nueva secuencia
                if len(current_seq) >= 2:
                    sequences.append((tuple(current_seq), last_timestamp))
                current_seq = [event["file_path"]]
                last_timestamp = event["timestamp"]

        # Agregar última secuencia
        if len(current_seq) >= 2:
            sequences.append((tuple(current_seq), last_timestamp))

        # Contar occurrences
        sequence_counts = defaultdict(list)
        for seq, timestamp in sequences:
            sequence_counts[seq].append(timestamp)

        # Filtrar por min_support
        detected_sequences = []
        for seq, timestamps in sequence_counts.items():
            if len(timestamps) >= min_support:
                detected_sequences.append({
                    "sequence": list(seq),
                    "occurrences": len(timestamps),
                    "confidence": len(timestamps) / len(sequences) if sequences else 0.0,
                    "last_seen_at": max(timestamps),
                })

        # Ordenar por occurrences
        detected_sequences.sort(key=lambda x: x["occurrences"], reverse=True)

        logger.debug(
            "Detected %d file sequences (min_support=%d)",
            len(detected_sequences),
            min_support,
        )

        return detected_sequences

    @classmethod
    def identify_focus_clusters(
        cls,
        recent_files: List[str],
        min_cluster_size: int = 3,
    ) -> List[Dict[str, Any]]:
        """Identifica clusters de archivos correlacionados.

        Algoritmo: DBSCAN-like clustering basado en:
          - Path similarity (misma carpeta, similar nombres)
          - Co-occurrence frequency

        Args:
            recent_files: Lista de file paths recientes
            min_cluster_size: Mínimo tamaño de cluster

        Returns:
            Lista de clusters detectados:
            [
                {
                    "cluster_id": "auth_layer",
                    "files": ["auth.py", "auth_middleware.py", "test_auth.py"],
                    "semantic_label": "authentication",
                    "last_activity_at": timestamp,
                },
                ...
            ]
        """
        if len(recent_files) < min_cluster_size:
            return []

        # Agrupar por directorio
        dir_groups = defaultdict(list)
        for path in recent_files:
            # Extraer directorio base
            parts = path.split("/")
            if len(parts) > 1:
                base_dir = "/".join(parts[:-1])
            else:
                base_dir = "root"
            dir_groups[base_dir].append(path)

        # Identificar clusters
        clusters = []
        for dir_path, files in dir_groups.items():
            if len(files) >= min_cluster_size:
                # Detectar semantic label desde nombres de archivos
                semantic_label = cls._infer_semantic_label(files)

                clusters.append({
                    "cluster_id": semantic_label or dir_path.split("/")[-1],
                    "files": files,
                    "semantic_label": semantic_label or "general",
                    "active_sessions": [],
                    "last_activity_at": time.time(),
                })

        logger.debug(
            "Identified %d focus clusters from %d files",
            len(clusters),
            len(recent_files),
        )

        return clusters

    @classmethod
    def get_detected_sequences(
        cls,
        session_id: str,
        min_support: int = 3,
    ) -> List[Dict[str, Any]]:
        """Obtiene file sequences detectadas para una sesión.

        Args:
            session_id: ID de sesión
            min_support: Mínimo número de occurrences

        Returns:
            Lista de secuencias detectadas
        """
        from .workspace.workspace_context_service import WorkspaceContextService

        # Get events desde workspace context
        events = WorkspaceContextService._retrieve_events_from_gics(
            session_id,
            since_timestamp=time.time() - 86400,  # Last 24 hours
        )

        return cls.detect_file_sequences(events, min_support=min_support)

    @classmethod
    def _infer_semantic_label(cls, file_paths: List[str]) -> Optional[str]:
        """Infiere semantic label desde nombres de archivos.

        Heurísticas:
        - "auth", "login" → "authentication"
        - "test_" → "testing"
        - "model" → "data_model"
        - etc.
        """
        # Concatenar todos los nombres
        all_text = " ".join(file_paths).lower()

        # Patterns comunes
        if "auth" in all_text or "login" in all_text:
            return "authentication"
        elif "test_" in all_text or "_test" in all_text:
            return "testing"
        elif "model" in all_text:
            return "data_model"
        elif "api" in all_text or "endpoint" in all_text:
            return "api"
        elif "ui" in all_text or "component" in all_text:
            return "frontend"
        elif "db" in all_text or "database" in all_text:
            return "database"
        elif "security" in all_text or "crypto" in all_text:
            return "security"

        return None
