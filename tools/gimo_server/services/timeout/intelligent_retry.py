"""
Intelligent Retry — Phase 6 of SEA.

Retry logic with circuit breaker and collective intelligence from GICS.
Learns from collective failures to avoid retrying when provider is degraded.
"""

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

logger = logging.getLogger("orchestrator.services.timeout.intelligent_retry")


class ProviderDegradedError(Exception):
    """Raised when provider is collectively degraded (no retry)."""
    pass


class MaxRetriesExceededError(Exception):
    """Raised when max retries exceeded."""
    pass


class ExponentialBackoff:
    """Exponential backoff calculator."""

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 32.0,
        multiplier: float = 2.0
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.multiplier = multiplier

    def next_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number."""
        delay = self.base_delay * (self.multiplier ** attempt)
        return min(delay, self.max_delay)


class IntelligentRetry:
    """
    Servicio de retry inteligente con circuit breaker y collective intelligence.

    Features:
    - Circuit breaker to prevent cascading failures
    - Exponential backoff
    - Collective intelligence from GICS (detect provider degradation)
    - Configurable retry logic
    """

    # Singleton GICS instance (injected)
    _gics = None

    # Threshold for collective degradation detection
    DEGRADATION_THRESHOLD = 10  # >10 timeouts in window → degraded

    # Time window for collective intelligence (5 minutes)
    DEGRADATION_WINDOW_SECONDS = 300

    def __init__(
        self,
        circuit_breaker: Optional[CircuitBreaker] = None,
        backoff: Optional[ExponentialBackoff] = None,
        name: str = "default"
    ):
        """
        Initialize intelligent retry service.

        Args:
            circuit_breaker: Circuit breaker instance (creates default if None)
            backoff: Backoff strategy (creates default if None)
            name: Retry service name
        """
        self.name = name
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            name=f"retry_{name}"
        )
        self.backoff = backoff or ExponentialBackoff(
            base_delay=1.0,
            max_delay=32.0,
            multiplier=2.0
        )

        logger.info("IntelligentRetry '%s' initialized", name)

    @classmethod
    def set_gics(cls, gics) -> None:
        """Inject GICS service instance."""
        cls._gics = gics

    @classmethod
    def _get_gics(cls):
        """Get GICS instance (None if not available)."""
        return cls._gics

    async def execute_with_retry(
        self,
        operation: Callable,
        operation_name: str,
        max_retries: int = 3,
        timeout: Optional[float] = None
    ) -> Any:
        """
        Execute operation with intelligent retry.

        Args:
            operation: Async callable to execute
            operation_name: Operation name (for logging/telemetry)
            max_retries: Maximum retry attempts
            timeout: Optional timeout per attempt

        Returns:
            Operation result

        Raises:
            CircuitBreakerOpenError: Circuit breaker is open
            ProviderDegradedError: Provider is collectively degraded
            MaxRetriesExceededError: Max retries exceeded
            TimeoutError: Operation timed out
        """
        attempt = 0

        while attempt <= max_retries:
            try:
                # 1. Check circuit breaker
                self.circuit_breaker.can_proceed()

                # 2. Execute operation (with optional timeout)
                if timeout:
                    result = await asyncio.wait_for(operation(), timeout=timeout)
                else:
                    result = await operation()

                # 3. Success → record and return
                self.circuit_breaker.record_success()

                if attempt > 0:
                    logger.info(
                        "IntelligentRetry '%s': Success on attempt %d/%d",
                        self.name, attempt + 1, max_retries + 1
                    )

                return result

            except CircuitBreakerOpenError:
                # Circuit breaker is open → fail fast
                logger.warning(
                    "IntelligentRetry '%s': Circuit breaker open, aborting",
                    self.name
                )
                raise

            except TimeoutError as exc:
                # Timeout → record failure and check collective intelligence
                self.circuit_breaker.record_failure()
                attempt += 1

                logger.warning(
                    "IntelligentRetry '%s': Timeout on attempt %d/%d",
                    self.name, attempt, max_retries + 1
                )

                # Record timeout in GICS for collective intelligence
                self._record_timeout(operation_name)

                # Check collective degradation
                if self._is_provider_degraded(operation_name):
                    logger.error(
                        "IntelligentRetry '%s': Provider collectively degraded, aborting",
                        self.name
                    )
                    raise ProviderDegradedError(
                        f"Provider degraded for {operation_name} "
                        f"(>{self.DEGRADATION_THRESHOLD} timeouts in {self.DEGRADATION_WINDOW_SECONDS}s)"
                    )

                # Retry with backoff
                if attempt <= max_retries:
                    delay = self.backoff.next_delay(attempt - 1)
                    logger.info(
                        "IntelligentRetry '%s': Retrying in %.1fs (attempt %d/%d)",
                        self.name, delay, attempt + 1, max_retries + 1
                    )
                    await asyncio.sleep(delay)
                else:
                    raise MaxRetriesExceededError(
                        f"Max retries ({max_retries}) exceeded for {operation_name}"
                    )

            except Exception as exc:
                # Other exceptions → record failure and re-raise
                self.circuit_breaker.record_failure()
                logger.error(
                    "IntelligentRetry '%s': Unhandled exception: %s",
                    self.name, exc, exc_info=True
                )
                raise

        # Should not reach here
        raise MaxRetriesExceededError(
            f"Max retries ({max_retries}) exceeded for {operation_name}"
        )

    def _record_timeout(self, operation_name: str) -> None:
        """Record timeout in GICS for collective intelligence."""
        try:
            gics = self._get_gics()
            if not gics:
                return

            timestamp_ms = int(time.time() * 1000)
            key = f"ops:timeout:{operation_name}:{timestamp_ms}"

            fields = {
                "operation": operation_name,
                "timestamp": int(time.time()),
                "retry_service": self.name,
            }

            gics.put(key, fields)

        except Exception as exc:
            logger.warning("Failed to record timeout in GICS: %s", exc)

    def _is_provider_degraded(self, operation_name: str) -> bool:
        """
        Check if provider is collectively degraded.

        Uses GICS to count recent timeouts. If >DEGRADATION_THRESHOLD timeouts
        in the last DEGRADATION_WINDOW_SECONDS, provider is considered degraded.

        Args:
            operation_name: Operation name to check

        Returns:
            True if provider is degraded
        """
        try:
            gics = self._get_gics()
            if not gics:
                return False

            # Scan recent timeouts
            prefix = f"ops:timeout:{operation_name}:"
            records = gics.scan(prefix=prefix)

            # Count timeouts in window
            current_time = time.time()
            recent_count = 0

            for record in records:
                fields = record.get("fields") or {}
                timestamp = fields.get("timestamp", 0)

                if current_time - timestamp < self.DEGRADATION_WINDOW_SECONDS:
                    recent_count += 1

            is_degraded = recent_count > self.DEGRADATION_THRESHOLD

            if is_degraded:
                logger.warning(
                    "Provider degradation detected: %d timeouts for %s in last %ds",
                    recent_count, operation_name, self.DEGRADATION_WINDOW_SECONDS
                )

            return is_degraded

        except Exception as exc:
            logger.warning("Failed to check provider degradation: %s", exc)
            return False

    def get_stats(self) -> dict:
        """Get retry service statistics."""
        return {
            "name": self.name,
            "circuit_breaker": self.circuit_breaker.get_stats(),
            "backoff": {
                "base_delay": self.backoff.base_delay,
                "max_delay": self.backoff.max_delay,
                "multiplier": self.backoff.multiplier,
            },
        }

    def reset(self) -> None:
        """Reset retry service (manual override)."""
        logger.warning("IntelligentRetry '%s': Manual reset", self.name)
        self.circuit_breaker.reset()
