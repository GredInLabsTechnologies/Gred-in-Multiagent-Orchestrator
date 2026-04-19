"""Mesh → ObservabilityService bridge.

Emits mesh events as UI spans so the observability dashboard sees mesh
traffic (enrollment, dispatch decisions, thermal events, state changes).

This is a *sink*, never a gate: failures to record are swallowed with a
debug log. Mesh logic must never break because observability is down.
Events are also already persisted to the dedicated mesh audit trail
(`audit.jsonl`, `thermal_events.jsonl`); this bridge adds dashboard
visibility on top.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("orchestrator.mesh.observability")

_KIND = "mesh"


def _emit(name: str, attributes: Dict[str, Any]) -> None:
    """Best-effort emit. Swallows all exceptions."""
    try:
        from ..observability_pkg.observability_service import ObservabilityService
        ObservabilityService.record_span(_KIND, name, attributes)
    except Exception:  # pragma: no cover — defensive
        logger.debug("mesh observability emit failed (name=%s)", name, exc_info=True)


def emit_enrollment(device_id: str, device_mode: str, device_class: str) -> None:
    _emit("enroll", {
        "device_id": device_id,
        "device_mode": device_mode,
        "device_class": device_class,
        "status": "ok",
    })


def emit_state_change(device_id: str, old_state: str, new_state: str) -> None:
    _emit("state_change", {
        "device_id": device_id,
        "old_state": old_state,
        "new_state": new_state,
        "status": "ok",
    })


def emit_thermal(
    device_id: str,
    event_type: str,
    trigger_sensor: str,
    trigger_value: float,
    trigger_threshold: float,
) -> None:
    # event_type is one of: warning, throttle, lockout
    status = "failed" if event_type == "lockout" else "ok"
    _emit("thermal", {
        "device_id": device_id,
        "event_type": event_type,
        "trigger_sensor": trigger_sensor,
        "trigger_value": trigger_value,
        "trigger_threshold": trigger_threshold,
        "status": status,
    })


def emit_dispatch(
    device_id: str,
    reason: str,
    fallback_to_local: bool,
    health_score: float,
    action_class: Optional[str] = None,
) -> None:
    _emit("dispatch", {
        "device_id": device_id,
        "reason": reason,
        "fallback_to_local": fallback_to_local,
        "health_score": health_score,
        "action_class": action_class or "",
        "status": "ok",
    })
