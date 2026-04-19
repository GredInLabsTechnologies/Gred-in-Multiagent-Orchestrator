"""
Circuit Breaker — Phase 6 of SEA.

Implements circuit breaker pattern to prevent cascading failures.
States: CLOSED → OPEN → HALF_OPEN → CLOSED
"""

import logging
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger("orchestrator.services.timeout.circuit_breaker")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"          # Normal operation, requests pass through
    OPEN = "open"              # Circuit tripped, block all requests (fast-fail)
    HALF_OPEN = "half_open"    # Testing recovery, allow limited requests


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""


class CircuitBreaker:
    """
    Circuit breaker para prevenir fallos en cascada.

    States:
        CLOSED: Normal operation
        OPEN: Block all (fast-fail), wait recovery_timeout
        HALF_OPEN: Allow limited test requests

    Transitions:
        CLOSED --(failures >= threshold)--> OPEN
        OPEN --(recovery_timeout elapsed)--> HALF_OPEN
        HALF_OPEN --(success)--> CLOSED
        HALF_OPEN --(failure)--> OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        name: str = "default"
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            half_open_max_calls: Max requests to allow in HALF_OPEN state
            name: Circuit breaker name (for logging)
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0

        logger.info(
            "CircuitBreaker '%s' initialized: threshold=%d, recovery=%ds",
            name, failure_threshold, recovery_timeout
        )

    def can_proceed(self) -> bool:
        """
        Check if request can proceed.

        Returns:
            True if request should be allowed

        Raises:
            CircuitBreakerOpenError if circuit is open
        """
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout elapsed
            if self.last_failure_time and (time.time() - self.last_failure_time) > self.recovery_timeout:
                logger.info("CircuitBreaker '%s': Transitioning OPEN → HALF_OPEN", self.name)
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                return True

            # Still open, reject
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN. "
                f"Recovery in {self._time_until_recovery():.1f}s"
            )

        if self.state == CircuitState.HALF_OPEN:
            # Allow limited test calls
            if self.half_open_calls < self.half_open_max_calls:
                self.half_open_calls += 1
                return True

            # Max calls reached in HALF_OPEN, reject
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is HALF_OPEN and at capacity"
            )

        return False

    def record_success(self) -> None:
        """Record successful operation."""
        if self.state == CircuitState.HALF_OPEN:
            # Success in HALF_OPEN → transition to CLOSED
            logger.info("CircuitBreaker '%s': Success in HALF_OPEN → CLOSED", self.name)
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.half_open_calls = 0

        elif self.state == CircuitState.CLOSED:
            # Success in CLOSED → increment counter, reset failures
            self.success_count += 1
            self.failure_count = 0

    def record_failure(self) -> None:
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # Failure in HALF_OPEN → back to OPEN
            logger.warning(
                "CircuitBreaker '%s': Failure in HALF_OPEN → OPEN",
                self.name
            )
            self.state = CircuitState.OPEN
            self.half_open_calls = 0

        elif self.state == CircuitState.CLOSED:
            # Check if threshold reached
            if self.failure_count >= self.failure_threshold:
                logger.error(
                    "CircuitBreaker '%s': Threshold reached (%d failures) → OPEN",
                    self.name, self.failure_count
                )
                self.state = CircuitState.OPEN

    def _time_until_recovery(self) -> float:
        """Calculate time until recovery timeout expires."""
        if not self.last_failure_time:
            return 0.0

        elapsed = time.time() - self.last_failure_time
        remaining = self.recovery_timeout - elapsed
        return max(0.0, remaining)

    def get_state(self) -> str:
        """Get current state as string."""
        return self.state.value

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "time_until_recovery": self._time_until_recovery() if self.state == CircuitState.OPEN else None,
            "half_open_calls": self.half_open_calls if self.state == CircuitState.HALF_OPEN else None,
        }

    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state (manual override)."""
        logger.warning("CircuitBreaker '%s': Manual reset to CLOSED", self.name)
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        self.last_failure_time = None
