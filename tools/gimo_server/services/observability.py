# observability.py — DEPRECATED shim.
#
# The legacy simple ObservabilityService was retired in favor of the
# OpenTelemetry-backed implementation in `observability_pkg.observability_service`.
# All methods the simple service exposed (`record_usage`, `record_llm_usage`,
# `record_agent_action`, `get_agent_insights`, `record_span`, `get_metrics`,
# `list_traces`, `record_structured_event`) are preserved on the unified
# service, so `from .observability import ObservabilityService` keeps working
# for any caller that still uses the legacy import path.
#
# DO NOT add new imports against this module — use
# `from .observability_service import ObservabilityService` (the package shim)
# or import directly from `observability_pkg.observability_service`.
from .observability_pkg.observability_service import ObservabilityService  # noqa: F401

__all__ = ["ObservabilityService"]
