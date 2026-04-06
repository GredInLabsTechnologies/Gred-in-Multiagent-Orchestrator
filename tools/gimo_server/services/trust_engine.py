from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from tools.gimo_server.security import audit_log



@dataclass
class TrustThresholds:
    """Limites estaticos de fallos para control continuo (CircuitBreaker)."""
    auto_approve_score: float = 0.90
    auto_approve_min_approvals: int = 20
    review_score: float = 0.50
    blocked_failures: int = 5


@dataclass
class CircuitBreakerConfig:
    """Tiempos de cooldown y retry para proveedores inestables."""
    window: int = 20
    failure_threshold: int = 5
    recovery_probes: int = 3
    cooldown_seconds: int = 300


class TrustEngine:
    """Computes trust records from persisted trust events."""

    def __init__(
        self,
        trust_store: Any,  # Can be the legacy TrustStore or the new TrustStorage
        thresholds: TrustThresholds | None = None,
        circuit_breaker: CircuitBreakerConfig | None = None,
    ):
        self.trust_store = trust_store
        # Support both legacy trust_store.storage and new TrustStorage (which is its own storage)
        self.storage = getattr(trust_store, "storage", trust_store)
        self.thresholds = thresholds or TrustThresholds()
        self.circuit_breaker = circuit_breaker or CircuitBreakerConfig()

    def query_dimension(self, dimension_key: str, *, events_limit: int = 5000) -> Dict[str, Any]:
        events = self.storage.list_trust_events(limit=events_limit)
        record_map = self._build_records(events)
        record = record_map.get(dimension_key, self._empty_record(dimension_key))
        self.trust_store.save_dimension(dimension_key, record)
        return record

    def dashboard(self, *, limit: int = 100, events_limit: int = 5000) -> List[Dict[str, Any]]:
        events = self.storage.list_trust_events(limit=events_limit)
        records = list(self._build_records(events).values())
        records.sort(key=lambda r: (r["score"], r["approvals"]), reverse=True)
        top = records[:limit]
        for record in top:
            self.storage.upsert_trust_record(record)
        return top

    def _build_records(self, events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        # list_trust_events returns newest-first; streak needs oldest-first.
        ordered = sorted(events, key=lambda e: str(e.get("timestamp") or ""))
        by_dimension: Dict[str, Dict[str, Any]] = {}

        for event in ordered:
            key = event.get("dimension_key")
            if not key:
                continue

            record = by_dimension.setdefault(key, self._empty_record(key))
            outcome = str(event.get("outcome") or "")
            post_check_passed = bool(event.get("post_check_passed", True))

            if outcome in {"approved", "auto_approved"}:
                record["approvals"] += 1
                record["streak"] += 1
                if outcome == "auto_approved":
                    record["auto_approvals"] += 1
            elif outcome == "rejected":
                record["rejections"] += 1
                record["streak"] = 0
            elif outcome in {"error", "timeout"}:
                record["failures"] += 1
                record["streak"] = 0

            if not post_check_passed:
                record["failures"] += 1
                record["streak"] = 0

            record["last_updated"] = event.get("timestamp")

        for record in by_dimension.values():
            self._finalize_record(record)

        return by_dimension

    def _finalize_record(self, record: Dict[str, Any]) -> None:
        approvals = record["approvals"]
        rejections = record["rejections"]
        failures = record["failures"]
        streak = record["streak"]

        base = approvals / (approvals + rejections + failures + 1)
        streak_bonus = min(streak * 0.01, 0.1)
        score = max(0.0, min(1.0, base + streak_bonus))

        record["score"] = round(score, 4)
        record["policy"] = self._decide_policy(record)
        self._apply_circuit_breaker(record)

    def _decide_policy(self, record: Dict[str, Any]) -> str:
        score = record["score"]
        approvals = record["approvals"]
        failures = record["failures"]

        if failures >= self.thresholds.blocked_failures:
            return "blocked"
        if score >= self.thresholds.auto_approve_score and approvals >= self.thresholds.auto_approve_min_approvals:
            return "auto_approve"
        if score >= self.thresholds.review_score:
            return "require_review"
        return "blocked"

    def _apply_circuit_breaker(self, record: Dict[str, Any]) -> None:
        dimension_key = record["dimension_key"]
        current = self.storage.get_trust_record(dimension_key) or {}
        state = str(current.get("circuit_state") or "closed")
        opened_at = self._parse_ts(current.get("circuit_opened_at"))
        cb_cfg = self._resolve_circuit_breaker_config(dimension_key)

        window_events = self._dimension_recent_events(
            dimension_key,
            limit=cb_cfg.window,
        )
        failure_count = sum(1 for evt in window_events if self._is_failure(evt))
        now = datetime.now(timezone.utc)

        next_state = state
        next_opened_at = opened_at

        if state == "closed":
            if failure_count >= cb_cfg.failure_threshold:
                next_state = "open"
                next_opened_at = now
        elif state == "open":
            if opened_at is None:
                next_opened_at = now
            cooldown_ready = bool(next_opened_at) and (now - next_opened_at) >= timedelta(
                seconds=cb_cfg.cooldown_seconds
            )
            if cooldown_ready:
                next_state = "half_open"
        elif state == "half_open":
            probes = window_events[: cb_cfg.recovery_probes]
            if len(probes) < cb_cfg.recovery_probes:
                next_state = "half_open"
            elif any(self._is_failure(evt) or str(evt.get("outcome") or "") == "rejected" for evt in probes):
                next_state = "open"
                next_opened_at = now
            elif all(str(evt.get("outcome") or "") in {"approved", "auto_approved"} for evt in probes):
                next_state = "closed"
                next_opened_at = None

        if next_state == "open":
            record["policy"] = "blocked"
        elif next_state == "half_open":
            # Half-open requires supervised execution (HITL)
            if record["policy"] == "auto_approve":
                record["policy"] = "require_review"

        record["circuit_state"] = next_state
        record["circuit_opened_at"] = next_opened_at.isoformat() if next_opened_at else None

        if next_state != state:
            self._notify_circuit_transition(dimension_key, state, next_state)

    def _resolve_circuit_breaker_config(self, dimension_key: str) -> CircuitBreakerConfig:
        cfg = self.storage.get_circuit_breaker_config(dimension_key)
        if not cfg:
            return self.circuit_breaker
        return CircuitBreakerConfig(
            window=int(cfg.get("window", self.circuit_breaker.window)),
            failure_threshold=int(cfg.get("failure_threshold", self.circuit_breaker.failure_threshold)),
            recovery_probes=int(cfg.get("recovery_probes", self.circuit_breaker.recovery_probes)),
            cooldown_seconds=int(cfg.get("cooldown_seconds", self.circuit_breaker.cooldown_seconds)),
        )

    def _dimension_recent_events(self, dimension_key: str, *, limit: int) -> List[Dict[str, Any]]:
        # Prefer DB-side filtering when available for correctness and scale.
        list_by_dim = getattr(self.storage, "list_trust_events_by_dimension", None)
        if callable(list_by_dim):
            try:
                return list_by_dim(dimension_key, limit=limit)
            except Exception:
                # Fallback to legacy path below
                pass

        events = self.storage.list_trust_events(limit=max(limit * 5, 100))
        filtered = [e for e in events if e.get("dimension_key") == dimension_key]
        # list_trust_events() is newest-first; keep that order.
        return filtered[:limit]

    @staticmethod
    def _is_failure(event: Dict[str, Any]) -> bool:
        outcome = str(event.get("outcome") or "")
        post_check_passed = bool(event.get("post_check_passed", True))
        return outcome in {"error", "timeout"} or not post_check_passed

    @staticmethod
    def _parse_ts(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        try:
            txt = str(value)
            if txt.endswith("Z"):
                txt = txt[:-1] + "+00:00"
            return datetime.fromisoformat(txt).astimezone(timezone.utc)
        except Exception:
            return None

    @staticmethod
    def _notify_circuit_transition(dimension_key: str, from_state: str, to_state: str) -> None:
        actor = "system:trust_engine"
        audit_log(
            "OPS",
            "/ops/trust/circuit-breaker",
            f"{dimension_key}:{from_state}->{to_state}",
            operation="WRITE",
            actor=actor,
        )

    @staticmethod
    def _empty_record(dimension_key: str) -> Dict[str, Any]:
        return {
            "dimension_key": dimension_key,
            "approvals": 0,
            "rejections": 0,
            "failures": 0,
            "auto_approvals": 0,
            "streak": 0,
            "score": 0.85,
            "policy": "require_review",
            "circuit_state": "closed",
            "circuit_opened_at": None,
            "last_updated": None,
        }
