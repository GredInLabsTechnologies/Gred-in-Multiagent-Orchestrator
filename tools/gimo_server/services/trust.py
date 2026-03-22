from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal



logger = logging.getLogger("orchestrator.trust")


from ..ops_models import TrustRecord, TrustEvent


class TrustService:
    """Consolidated service for trust metrics, circuit breakers, and event buffering."""

    def __init__(self, storage: Any):
        self.storage = storage
        self._buffer: List[Dict[str, Any]] = []
        self._last_flush = time.monotonic()
        
        # Thresholds
        self.auto_approve_score = 0.90
        self.min_approvals = 20
        self.blocked_failures = 5

    # --- Event Buffering ---

    def add_event(self, event: Dict[str, Any]) -> None:
        self._buffer.append(dict(event))
        if len(self._buffer) >= 50 or (time.monotonic() - self._last_flush) >= 10:
            self.flush_events()

    def flush_events(self) -> None:
        if not self._buffer: return
        try:
            # Assumes storage has save_trust_events()
            self.storage.save_trust_events(self._buffer)
            self._buffer.clear()
            self._last_flush = time.monotonic()
        except Exception as e:
            logger.error(f"Failed to flush trust events: {e}")

    # --- Trust Computation ---

    def get_trust_record(self, dimension_key: str) -> TrustRecord:
        """Calculates trust score and determines execution policy for a specific dimension."""
        events_raw: List[Dict[str, Any]] = self.storage.list_trust_events_by_dimension(dimension_key, limit=100)
        if not events_raw:
            return self._empty_record(dimension_key)
        
        # Validate into domain types (P0 Boundary rule)
        events = [TrustEvent.model_validate(e) for e in events_raw]
        
        approvals = sum(1 for e in events if e.outcome in ("approved", "auto_approved"))
        failures = sum(1 for e in events if e.outcome in ("error", "timeout") or not e.post_check_passed)
        rejections = sum(1 for e in events if e.outcome == "rejected")
        
        score = approvals / (approvals + rejections + failures + 1)
        # Add basic streak bonus (last N consecutive successes)
        streak = 0
        for e in sorted(events, key=lambda x: x.timestamp, reverse=True):
            if e.outcome in ("approved", "auto_approved") and e.post_check_passed:
                streak += 1
            else:
                break
        
        final_score = round(max(0.0, min(1.0, score + (streak * 0.01))), 4)
        
        # Policy decision
        if failures >= self.blocked_failures:
            policy: Literal["allow", "require_review", "blocked", "auto_approve"] = "blocked"
        elif final_score >= self.auto_approve_score and approvals >= self.min_approvals:
            policy = "auto_approve"
        elif final_score >= 0.5:
            policy = "require_review"
        else:
            policy = "blocked"
            
        record = TrustRecord(
            dimension_key=dimension_key,
            score=final_score,
            policy=policy,
            approvals=approvals,
            failures=failures,
            streak=streak,
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        
        # Circuit breaker logic
        self._apply_circuit_breaker(record, events)
        return record

    def _apply_circuit_breaker(self, record: TrustRecord, recent_events: List[TrustEvent]) -> None:
        # Simplified circuit breaker
        failures_in_window = sum(1 for e in recent_events[:20] if e.outcome in ("error", "timeout"))
        if failures_in_window >= 5:
            record.policy = "blocked"
            record.circuit_state = "open"
        else:
            record.circuit_state = "closed"

    def _empty_record(self, key: str) -> TrustRecord:
        return TrustRecord(
            dimension_key=key,
            score=0.0,
            policy="require_review",
            approvals=0,
            failures=0,
            streak=0,
            circuit_state="closed"
        )
