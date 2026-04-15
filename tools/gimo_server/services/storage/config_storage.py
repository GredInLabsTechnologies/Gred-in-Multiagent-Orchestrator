from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("orchestrator.services.storage.config")

class ConfigStorage:
    """Storage logic for circuit breakers and tool call idempotency.
    Persists entirely via GICS.
    """

    def __init__(self, conn: Optional[Any] = None, gics: Optional[Any] = None):
        self._conn = conn # Kept for backward compatibility
        self.gics = gics

    def ensure_tables(self) -> None:
        """No-op: using GICS."""

    def get_circuit_breaker_config(self, dimension_key: str) -> Optional[Dict[str, Any]]:
        if not self.gics:
            return None
            
        try:
            result = self.gics.get(f"cb:{dimension_key}")
            if result and "fields" in result:
                return {
                    "dimension_key": dimension_key,
                    "window": int(result["fields"].get("window", 0)),
                    "failure_threshold": int(result["fields"].get("failure_threshold", 0)),
                    "recovery_probes": int(result["fields"].get("recovery_probes", 0)),
                    "cooldown_seconds": int(result["fields"].get("cooldown_seconds", 0)),
                }
        except Exception as e:
            logger.error("Failed to get circuit breaker config from GICS: %s", e)
            
        return None

    def upsert_circuit_breaker_config(self, dimension_key: str, config: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "dimension_key": dimension_key,
            "window": int(config.get("window", 0)),
            "failure_threshold": int(config.get("failure_threshold", 0)),
            "recovery_probes": int(config.get("recovery_probes", 0)),
            "cooldown_seconds": int(config.get("cooldown_seconds", 0)),
        }
        
        if self.gics:
            try:
                self.gics.put(f"cb:{dimension_key}", payload)
            except Exception as e:
                logger.error("Failed to push circuit breaker config %s to GICS: %s", dimension_key, e)

        return payload

    def register_tool_call_idempotency_key(
        self,
        *,
        idempotency_key: str,
        tool: str,
        context: Optional[str] = None,
    ) -> bool:
        if not idempotency_key or not self.gics:
            return True

        key = f"tk:{idempotency_key}"
        try:
            existing = self.gics.get(key)
            if existing and "fields" in existing:
                return False # Already registered
                
            self.gics.put(key, {"tool": tool, "context": context})
            return True
        except Exception as e:
            logger.error("Failed to register tool call idempotency key %s to GICS: %s", idempotency_key, e)
            return True # Fail open to avoid blocking
