"""
Deadline Propagation Middleware — Phase 4 of SEA.

Extracts deadline headers and injects remaining time into request state.
Backend can use this to cancel proactively when approaching timeout.
"""

import logging
import time
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("orchestrator.middlewares.deadline")


class DeadlineMiddleware(BaseHTTPMiddleware):
    """
    Middleware para propagación de deadlines desde CLI/UI al backend.

    Headers esperados:
        X-GIMO-Deadline: Unix timestamp absoluto (float)
        X-GIMO-Max-Duration: Duración máxima en segundos (float)

    Inyecta en request.state:
        request.state.deadline: Unix timestamp del deadline
        request.state.remaining_time: Segundos restantes
        request.state.max_duration: Duración máxima original
    """

    # Minimum time required to proceed (5 seconds)
    MIN_REMAINING_TIME = 5.0

    async def dispatch(self, request: Request, call_next):
        """Process request and inject deadline information."""

        # Extract headers
        deadline_str = request.headers.get("X-GIMO-Deadline")
        max_duration_str = request.headers.get("X-GIMO-Max-Duration")

        if deadline_str:
            try:
                deadline = float(deadline_str)
                remaining = deadline - time.time()

                # Validate that there's enough time to proceed
                if remaining < self.MIN_REMAINING_TIME:
                    logger.warning(
                        "Deadline already exceeded or too close: %.1fs remaining",
                        remaining
                    )
                    return JSONResponse(
                        status_code=408,
                        content={
                            "error": "Request deadline exceeded",
                            "detail": f"Only {remaining:.1f}s remaining (minimum {self.MIN_REMAINING_TIME}s required)",
                            "error_code": "DEADLINE_EXCEEDED"
                        }
                    )

                # Inject into request state
                request.state.deadline = deadline
                request.state.remaining_time = remaining

                if max_duration_str:
                    try:
                        request.state.max_duration = float(max_duration_str)
                    except ValueError:
                        logger.warning("Invalid X-GIMO-Max-Duration header: %s", max_duration_str)

                logger.debug(
                    "Deadline propagated: %.1fs remaining (deadline=%.2f)",
                    remaining, deadline
                )

            except ValueError:
                logger.warning("Invalid X-GIMO-Deadline header: %s", deadline_str)

        # Process request
        response = await call_next(request)

        return response

    @staticmethod
    def get_remaining_time(request: Request) -> float:
        """
        Helper para obtener tiempo restante desde request.

        Returns:
            Remaining time in seconds, or None if no deadline set
        """
        deadline = getattr(request.state, "deadline", None)
        if deadline is None:
            return None

        remaining = deadline - time.time()
        return max(0.0, remaining)

    @staticmethod
    def check_deadline_approaching(request: Request, threshold: float = 10.0) -> bool:
        """
        Check if deadline is approaching.

        Args:
            request: FastAPI request object
            threshold: Seconds threshold (default 10s)

        Returns:
            True if deadline is within threshold seconds
        """
        remaining = DeadlineMiddleware.get_remaining_time(request)
        if remaining is None:
            return False

        return remaining < threshold

    @staticmethod
    def allocate_time_budget(
        request: Request,
        overhead_percent: float = 0.1
    ) -> float:
        """
        Calcula presupuesto de tiempo para operación interna.

        Reserva overhead_percent del tiempo para overhead del servidor.

        Args:
            request: FastAPI request object
            overhead_percent: Percentage to reserve (default 10%)

        Returns:
            Time budget in seconds for internal operation
        """
        remaining = DeadlineMiddleware.get_remaining_time(request)
        if remaining is None:
            return None

        # Reserve overhead for server processing
        budget = remaining * (1.0 - overhead_percent)
        return max(0.0, budget)
