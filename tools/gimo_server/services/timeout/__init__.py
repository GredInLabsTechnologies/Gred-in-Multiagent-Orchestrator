"""
SEA (Sistema de Ejecución Adaptativa) — Timeout & Progress Management.

This package implements the adaptive execution system, including:
- Duration telemetry for operations
- Adaptive timeout prediction
- SSE progress streaming
- Deadline propagation
- Checkpointing for resumable operations
- Circuit breaker with intelligent retry
"""

from .duration_telemetry_service import DurationTelemetryService
from .adaptive_timeout_service import AdaptiveTimeoutService
from .progress_emitter import ProgressEmitter
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from .intelligent_retry import (
    IntelligentRetry,
    ProviderDegradedError,
    MaxRetriesExceededError,
    ExponentialBackoff,
)

__all__ = [
    "DurationTelemetryService",
    "AdaptiveTimeoutService",
    "ProgressEmitter",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitState",
    "IntelligentRetry",
    "ProviderDegradedError",
    "MaxRetriesExceededError",
    "ExponentialBackoff",
]
