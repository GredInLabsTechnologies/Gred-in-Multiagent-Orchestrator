"""WorkspaceContextService — Captures and queries IDE workspace context.

P9: Captura eventos del IDE (file opens, edits, git events) y los persiste en GICS
para análisis de patterns y context-aware routing.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.workspace_context")


class WorkspaceContextService:
    """Captures workspace events from IDE and provides query API for context analysis."""

    @classmethod
    def capture_event(
        cls,
        session_id: str,
        event_type: str,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Captura evento del IDE y persist en GICS.

        Args:
            session_id: ID de sesión del workspace
            event_type: Tipo de evento (file_open, file_edit, file_close, git_stage, git_commit, terminal_cmd)
            file_path: Path del archivo afectado
            metadata: Metadata adicional del evento
        """
        from .gics_service import GicsService

        event = {
            "event_type": event_type,
            "file_path": file_path,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }

        # Persist en GICS (append to list)
        key = f"ops:workspace:session:{session_id}:events"
        existing_events = cls._retrieve_events_from_gics(session_id) or []
        existing_events.append(event)

        # Comprimir y persistir
        cls._persist_events_to_gics(session_id, existing_events)

        # Update file access frequency
        cls._update_file_access_freq(file_path, session_id)

        logger.debug(
            "Captured event: session=%s, type=%s, file=%s",
            session_id,
            event_type,
            file_path,
        )

    @classmethod
    def get_recent_files(
        cls,
        session_id: str,
        limit: int = 10,
        since_seconds: int = 3600,
    ) -> List[Dict[str, Any]]:
        """Obtiene archivos recientes con temporal weights.

        Args:
            session_id: ID de sesión
            limit: Máximo número de archivos
            since_seconds: Ventana de tiempo (default 1 hora)

        Returns:
            Lista de archivos con temporal_weight decreciente
        """
        from .context_analysis_service import ContextAnalysisService

        events = cls._retrieve_events_from_gics(session_id, since_timestamp=time.time() - since_seconds)

        # Filtrar solo file_open/file_edit
        file_events = [
            e for e in events
            if e["event_type"] in {"file_open", "file_edit"}
        ]

        # Agrupar por file_path y calcular temporal weight
        file_access = {}
        for event in file_events:
            path = event["file_path"]
            if path not in file_access:
                file_access[path] = {
                    "file_path": path,
                    "last_access_at": event["timestamp"],
                    "access_count": 0,
                }
            file_access[path]["access_count"] += 1
            file_access[path]["last_access_at"] = max(
                file_access[path]["last_access_at"],
                event["timestamp"],
            )

        # Calcular temporal weights
        for file_data in file_access.values():
            file_data["temporal_weight"] = ContextAnalysisService.compute_temporal_weight(
                file_data["last_access_at"]
            )

        # Ordenar por temporal_weight y limitar
        sorted_files = sorted(
            file_access.values(),
            key=lambda x: x["temporal_weight"],
            reverse=True,
        )[:limit]

        return sorted_files

    @classmethod
    def get_file_access_frequency(
        cls,
        file_path: str,
    ) -> Optional[Dict[str, Any]]:
        """Obtiene frecuencia de acceso de un archivo.

        Returns:
            {
                "file_path": str,
                "access_count": int,
                "last_access_at": float,
                "first_access_at": float,
                "session_ids": List[str],
                "temporal_weight": float,
            }
        """
        from .context_analysis_service import ContextAnalysisService
        import hashlib

        # Hash file_path para key
        path_hash = hashlib.md5(file_path.encode()).hexdigest()[:12]
        key = f"ops:workspace:file_access_freq:{path_hash}"

        try:
            from ..main import app
            if hasattr(app.state, 'gics'):
                data = app.state.gics.get(key)
                if not data:
                    return None

                # Compute temporal weight
                data["temporal_weight"] = ContextAnalysisService.compute_temporal_weight(
                    data["last_access_at"]
                )

                return data
        except Exception as e:
            logger.warning("Failed to get file access frequency: %s", e)
            return None

    @classmethod
    def get_active_focus_cluster(
        cls,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Obtiene cluster activo del usuario.

        Returns:
            {
                "cluster_id": str,
                "files": List[str],
                "semantic_label": str,
                "active_sessions": List[str],
                "last_activity_at": float,
            }
        """
        from .gics_service import GicsService
        from .context_analysis_service import ContextAnalysisService

        # Get recent files
        recent_files = cls.get_recent_files(session_id, limit=10)
        if not recent_files:
            return None

        # Identify focus clusters
        file_paths = [f["file_path"] for f in recent_files]
        clusters = ContextAnalysisService.identify_focus_clusters(file_paths)

        # Retornar cluster más activo
        if clusters:
            return clusters[0]

        return None

    @classmethod
    def get_git_status(
        cls,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Obtiene git status del workspace.

        Returns:
            {
                "staged_files": List[str],
                "unstaged_files": List[str],
                "branch": str,
                "last_commit_at": float,
            }
        """
        key = f"ops:workspace:session:{session_id}:git_status"

        try:
            from ..main import app
            if hasattr(app.state, 'gics'):
                return app.state.gics.get(key)
            return None
        except Exception as e:
            logger.warning("Failed to get git status: %s", e)
            return None

    @classmethod
    def _persist_events_to_gics(
        cls,
        session_id: str,
        events: List[Dict[str, Any]],
    ) -> None:
        """Persist eventos en GICS (JSON directo, compresión futura)."""
        key = f"ops:workspace:session:{session_id}:events"

        # Por ahora persistir JSON directamente
        # TODO P9.1: Usar GICS compression cuando esté disponible
        data = {
            "events": events,
            "count": len(events),
            "updated_at": time.time(),
        }

        # Obtener instancia GICS desde app state (si está disponible)
        try:
            from ..main import app
            if hasattr(app.state, 'gics'):
                app.state.gics.put(key, data)
            else:
                logger.warning("GICS instance not available, events not persisted")
        except Exception as e:
            logger.warning("Failed to persist events to GICS: %s", e)

        logger.debug(
            "Persisted %d events to GICS (JSON): %d items",
            len(events),
            len(events),
        )

    @classmethod
    def _retrieve_events_from_gics(
        cls,
        session_id: str,
        since_timestamp: float = 0,
    ) -> List[Dict[str, Any]]:
        """Retrieve eventos desde GICS (JSON directo, compresión futura)."""
        key = f"ops:workspace:session:{session_id}:events"

        # Obtener instancia GICS desde app state
        try:
            from ..main import app
            if hasattr(app.state, 'gics'):
                data = app.state.gics.get(key)
                if not data:
                    return []

                # Extraer eventos
                events = data.get("events", [])

                # Filter por timestamp
                if since_timestamp > 0:
                    events = [e for e in events if e["timestamp"] >= since_timestamp]

                return events
            else:
                logger.warning("GICS instance not available")
                return []
        except Exception as e:
            logger.warning("Failed to retrieve events from GICS: %s", e)
            return []

    @classmethod
    def _update_file_access_freq(
        cls,
        file_path: str,
        session_id: str,
    ) -> None:
        """Actualiza frecuencia de acceso de un archivo."""
        import hashlib

        # Hash file_path para key
        path_hash = hashlib.md5(file_path.encode()).hexdigest()[:12]
        key = f"ops:workspace:file_access_freq:{path_hash}"

        now = time.time()

        try:
            from ..main import app
            if hasattr(app.state, 'gics'):
                # Read-modify-write
                data = app.state.gics.get(key)
                if not data:
                    data = {
                        "file_path": file_path,
                        "access_count": 0,
                        "first_access_at": now,
                        "last_access_at": now,
                        "session_ids": [],
                    }

                data["access_count"] += 1
                data["last_access_at"] = now
                if session_id not in data.get("session_ids", []):
                    data["session_ids"].append(session_id)

                app.state.gics.put(key, data)
        except Exception as e:
            logger.warning("Failed to update file access freq: %s", e)
