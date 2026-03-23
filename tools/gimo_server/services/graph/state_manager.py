"""StateManager — Fase 1 de GraphEngine v2.

Gestión de actualizaciones de estado con reducers declarativos.
Soporta: overwrite (default), append, add, max, min, merge_dict, dedupe_append.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("orchestrator.services.state_manager")


class StateManager:
    """Aplica actualizaciones de estado mediante reducers declarativos."""

    SUPPORTED_REDUCERS = frozenset(
        ["overwrite", "append", "add", "max", "min", "merge_dict", "dedupe_append"]
    )

    def __init__(
        self,
        reducers: Optional[Dict[str, str]] = None,
        gics_client=None,
        workflow_id: str = "",
    ):
        self._reducers = reducers or {}
        self._gics = gics_client
        self._workflow_id = workflow_id

    # ── Public API ──────────────────────────────────────────

    def apply_update(
        self,
        current_state: Dict[str, Any],
        update: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Aplica `update` sobre `current_state` usando los reducers configurados.

        Retorna el estado modificado (in-place).
        """
        for key, new_value in update.items():
            reducer = self._reducers.get(key, "overwrite")
            conflict = self._detect_conflict(current_state, key, new_value, reducer)
            if conflict:
                self._record_conflict(key, conflict)
            current_state[key] = self._apply_reducer(reducer, current_state, key, new_value)
        return current_state

    # ── Reducer dispatch ────────────────────────────────────

    def _apply_reducer(
        self,
        reducer: str,
        state: Dict[str, Any],
        key: str,
        new_value: Any,
    ) -> Any:
        current = state.get(key)

        if reducer == "overwrite":
            return new_value

        if reducer == "append":
            if current is None:
                return [new_value] if not isinstance(new_value, list) else new_value
            base = list(current) if isinstance(current, list) else [current]
            addition = list(new_value) if isinstance(new_value, list) else [new_value]
            return base + addition

        if reducer == "add":
            if current is None:
                return new_value
            try:
                return current + new_value
            except TypeError:
                logger.warning("reducer 'add' type mismatch for key=%s, fallback overwrite", key)
                return new_value

        if reducer == "max":
            if current is None:
                return new_value
            try:
                return max(current, new_value)
            except TypeError:
                return new_value

        if reducer == "min":
            if current is None:
                return new_value
            try:
                return min(current, new_value)
            except TypeError:
                return new_value

        if reducer == "merge_dict":
            if current is None:
                return dict(new_value) if isinstance(new_value, dict) else new_value
            if isinstance(current, dict) and isinstance(new_value, dict):
                merged = dict(current)
                merged.update(new_value)
                return merged
            logger.warning("reducer 'merge_dict' on non-dict for key=%s, fallback overwrite", key)
            return new_value

        if reducer == "dedupe_append":
            if current is None:
                return list(new_value) if isinstance(new_value, list) else [new_value]
            base = list(current) if isinstance(current, list) else [current]
            addition = list(new_value) if isinstance(new_value, list) else [new_value]
            seen = set()
            result = []
            for item in base + addition:
                key_item = item if not isinstance(item, dict) else str(sorted(item.items()))
                if key_item not in seen:
                    seen.add(key_item)
                    result.append(item)
            return result

        # Fallback desconocido → overwrite con warning
        logger.warning("Unknown reducer '%s' for key=%s, using overwrite", reducer, key)
        return new_value

    # ── Conflict detection ──────────────────────────────────

    def _detect_conflict(
        self,
        state: Dict[str, Any],
        key: str,
        new_value: Any,
        reducer: str,
    ) -> Optional[Dict[str, Any]]:
        """Detecta conflicto cuando un overwrite sobreescribe un valor existente diferente."""
        if reducer != "overwrite":
            return None
        if key not in state:
            return None
        current = state[key]
        if current == new_value:
            return None
        return {
            "key": key,
            "current_value": current,
            "new_value": new_value,
            "reducer": reducer,
        }

    def _record_conflict(self, key: str, conflict: Dict[str, Any]) -> None:
        if not self._gics or not self._workflow_id:
            return
        gics_key = f"ops:reducer_conflict:{self._workflow_id}:{key}"
        try:
            self._gics.put(gics_key, conflict)
        except Exception as e:
            logger.debug("GICS reducer_conflict record failed: %s", e)
