"""Adaptive multi-tier threat level engine.

Replaces the binary panic_mode with a 4-level defense system that:
- Tracks threats per-source (IP/fingerprint)
- Classifies events (operational vs security)
- Auto-decays if no new threats arrive
- Whitelists localhost / trusted sources
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.security.threat")

# ---------------------------------------------------------------------------
# Threat Levels
# ---------------------------------------------------------------------------

class ThreatLevel(IntEnum):
    """Progressive defense levels."""
    NOMINAL = 0   # Green  — no restrictions
    ALERT = 1     # Yellow — increased logging, tighter per-source rate limits
    GUARDED = 2   # Orange — unauthenticated requests throttled
    LOCKDOWN = 3  # Red    — only authenticated requests pass


THREAT_LABELS: Dict[ThreatLevel, str] = {
    ThreatLevel.NOMINAL: "NOMINAL",
    ThreatLevel.ALERT: "ALERT",
    ThreatLevel.GUARDED: "GUARDED",
    ThreatLevel.LOCKDOWN: "LOCKDOWN",
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Auto-decay timers (seconds of inactivity before dropping one level)
DECAY_TIMERS: Dict[ThreatLevel, int] = {
    ThreatLevel.ALERT: 120,      # 2 min → NOMINAL
    ThreatLevel.GUARDED: 180,    # 3 min → ALERT
    ThreatLevel.LOCKDOWN: 300,   # 5 min → GUARDED
}

# Escalation thresholds (within their respective time windows)
AUTH_FAILURE_ALERT_THRESHOLD = 3          # per-source failures for ALERT
AUTH_FAILURE_GUARDED_THRESHOLD = 5        # global failures for GUARDED
AUTH_FAILURE_LOCKDOWN_THRESHOLD = 10      # global failures for LOCKDOWN
AUTH_FAILURE_WINDOW_SECONDS = 60

EXCEPTION_GUARDED_THRESHOLD = 5           # security exceptions for GUARDED
EXCEPTION_LOCKDOWN_THRESHOLD = 8          # security exceptions for LOCKDOWN
EXCEPTION_WINDOW_SECONDS = 60

# IPs that never cause threat escalation
WHITELISTED_SOURCES = frozenset({
    "127.0.0.1",
    "localhost",
    "::1",
    "0.0.0.0",  # noqa: S104
    "testclient",  # FastAPI TestClient
})

# Exceptions considered operational (do NOT escalate threat)
OPERATIONAL_EXCEPTIONS = (
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
    FileNotFoundError,
    PermissionError,
    OSError,
    BrokenPipeError,
)

# Source tracking cleanup (remove sources inactive for >24h)
SOURCE_RETENTION_SECONDS = 86400

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventSeverity:
    OPERATIONAL = "operational"
    SECURITY = "security"
    CRITICAL = "critical"


@dataclass
class ThreatEvent:
    """A recorded threat event."""
    timestamp: float
    event_type: str        # "auth_failure", "exception", "rate_limit"
    severity: str          # EventSeverity values
    source: str            # IP or fingerprint
    detail: str = ""
    resolved: bool = False


# ---------------------------------------------------------------------------
# Source Tracker
# ---------------------------------------------------------------------------

@dataclass
class SourceRecord:
    """Per-source threat tracking."""
    source: str
    auth_failures: int = 0
    exceptions: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0

    def is_expired(self, now: float) -> bool:
        return (now - self.last_seen) > SOURCE_RETENTION_SECONDS


# ---------------------------------------------------------------------------
# Threat Engine
# ---------------------------------------------------------------------------

class ThreatEngine:
    """Adaptive threat evaluation engine.

    Singleton-like: meant to be instantiated once at app startup and shared
    across the middlewares via ``app.state.threat_engine``.
    """

    def __init__(self) -> None:
        self._level: ThreatLevel = ThreatLevel.NOMINAL
        self._level_since: float = time.time()
        self._events: List[ThreatEvent] = []
        self._sources: Dict[str, SourceRecord] = {}
        self._max_events = 500  # ring-buffer cap

    # -- Public API ---------------------------------------------------------

    @property
    def level(self) -> ThreatLevel:
        return self._level

    @level.setter
    def level(self, value: ThreatLevel) -> None:
        if isinstance(value, int):
            self._set_level(ThreatLevel(value))
        else:
            self._set_level(value)

    @property
    def level_label(self) -> str:
        return THREAT_LABELS.get(self._level, "UNKNOWN")

    @property
    def level_since(self) -> float:
        return self._level_since

    def decay_remaining_seconds(self) -> Optional[float]:
        """Seconds until auto-decay to next lower level, or None if NOMINAL."""
        timer = DECAY_TIMERS.get(self._level)
        if timer is None:
            return None
        elapsed = time.time() - self._level_since
        remaining = timer - elapsed
        return max(0.0, remaining)

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot for the status endpoint."""
        now = time.time()
        active_sources = [
            {
                "source": s.source,
                "auth_failures": s.auth_failures,
                "exceptions": s.exceptions,
                "last_seen_ago": round(now - s.last_seen, 1),
            }
            for s in self._sources.values()
            if not s.is_expired(now)
        ]
        return {
            "threat_level": int(self._level),
            "threat_level_label": self.level_label,
            "threat_level_since": self._level_since,
            "auto_decay_remaining": self.decay_remaining_seconds(),
            "active_sources": len(active_sources),
            "sources": active_sources[:20],  # cap for response size
            "recent_events_count": len(self._events),
            # Backward compat
            "panic_mode": self._level >= ThreatLevel.LOCKDOWN,
        }

    # -- Event recording ----------------------------------------------------

    def record_auth_failure(self, source: str, *, detail: str = "") -> ThreatLevel:
        """Record a failed authentication attempt."""
        if self._is_whitelisted(source):
            logger.debug("Auth failure from whitelisted source %s — ignored", source)
            return self._level

        now = time.time()
        self._touch_source(source, now, auth_failure=True)
        self._add_event(ThreatEvent(
            timestamp=now,
            event_type="auth_failure",
            severity=EventSeverity.SECURITY,
            source=source,
            detail=detail,
        ))
        self._evaluate(now)
        return self._level

    def record_exception(self, source: str, exc: Exception, *, detail: str = "") -> ThreatLevel:
        """Record an unhandled exception, classifying operational vs security."""
        if isinstance(exc, OPERATIONAL_EXCEPTIONS):
            logger.debug("Operational exception from %s (%s) — not escalating", source, type(exc).__name__)
            return self._level

        now = time.time()
        is_whitelisted = self._is_whitelisted(source)
        if not is_whitelisted:
            self._touch_source(source, now, exception=True)

        self._add_event(ThreatEvent(
            timestamp=now,
            event_type="exception",
            severity=EventSeverity.SECURITY,
            source=source,
            detail=detail or str(exc)[:200],
        ))
        self._evaluate(now)
        return self._level

    # -- Admin actions ------------------------------------------------------

    def clear_all(self) -> None:
        """Reset to NOMINAL — operator emergency action."""
        self._set_level(ThreatLevel.NOMINAL)
        for evt in self._events:
            evt.resolved = True
        self._sources.clear()
        logger.info("Threat level manually reset to NOMINAL")

    def downgrade(self) -> ThreatLevel:
        """Drop one level — operator de-escalation."""
        if self._level > ThreatLevel.NOMINAL:
            new_level = ThreatLevel(self._level - 1)
            self._set_level(new_level)
            logger.info("Threat level manually downgraded to %s", self.level_label)
        return self._level

    # -- Periodic maintenance -----------------------------------------------

    def tick_decay(self) -> bool:
        """Called periodically (every ~30s). Returns True if level changed."""
        timer = DECAY_TIMERS.get(self._level)
        if timer is None:
            return False

        elapsed = time.time() - self._level_since
        if elapsed >= timer:
            old = self._level
            new_level = ThreatLevel(self._level - 1)
            self._set_level(new_level)
            logger.info(
                "Threat auto-decayed %s → %s after %ds inactivity",
                THREAT_LABELS[old], self.level_label, int(elapsed),
            )
            return True
        return False

    def cleanup_stale_sources(self) -> int:
        """Remove expired source records. Returns count removed."""
        now = time.time()
        stale = [k for k, v in self._sources.items() if v.is_expired(now)]
        for k in stale:
            del self._sources[k]
        return len(stale)

    def cleanup_old_events(self, max_age: float = SOURCE_RETENTION_SECONDS) -> int:
        """Trim old events from the ring buffer."""
        now = time.time()
        before = len(self._events)
        self._events = [e for e in self._events if (now - e.timestamp) < max_age]
        return before - len(self._events)

    # -- Persistence helpers ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise state for saving to security_db.json."""
        return {
            "threat_level": int(self._level),
            "threat_level_since": self._level_since,
            "panic_mode": self._level >= ThreatLevel.LOCKDOWN,
            "recent_events": [
                {
                    "timestamp": e.timestamp,
                    "type": e.event_type,
                    "severity": e.severity,
                    "source": e.source,
                    "detail": e.detail,
                    "resolved": e.resolved,
                }
                for e in self._events[-100:]  # persist last 100
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThreatEngine":
        """Restore from saved state (used only for diagnostics, NOT for startup)."""
        engine = cls()
        # On startup we always start NOMINAL — this is intentional.
        # from_dict is for reading history, not restoring locks.
        return engine

    # -- Internal -----------------------------------------------------------

    def _set_level(self, level: ThreatLevel, reason: str = "") -> None:
        self._level = level
        self._level_since = time.time()
        if reason:
            logger.info("Threat level changed to %s: %s", self.level_label, reason)
        
        # Persist level change immediately
        try:
            from tools.gimo_server.security import save_security_db
            save_security_db()
        except Exception as e:
            logger.error("Failed to persist threat level change: %s", e)

    def _is_whitelisted(self, source: str) -> bool:
        return source in WHITELISTED_SOURCES

    def _touch_source(self, source: str, now: float, *, auth_failure: bool = False, exception: bool = False) -> None:
        rec = self._sources.get(source)
        if rec is None:
            rec = SourceRecord(source=source, first_seen=now)
            self._sources[source] = rec
        rec.last_seen = now
        if auth_failure:
            rec.auth_failures += 1
        if exception:
            rec.exceptions += 1

    def _add_event(self, event: ThreatEvent) -> None:
        self._events.append(event)
        # Cap ring buffer
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    def _evaluate(self, now: float) -> None:
        """Re-evaluate threat level based on current events."""
        window_start = now - AUTH_FAILURE_WINDOW_SECONDS
        exc_window_start = now - EXCEPTION_WINDOW_SECONDS

        # Count recent security events
        recent_auth = [
            e for e in self._events
            if e.event_type == "auth_failure"
            and e.timestamp >= window_start
            and not e.resolved
        ]
        recent_exceptions = [
            e for e in self._events
            if e.event_type == "exception"
            and e.severity == EventSeverity.SECURITY
            and e.timestamp >= exc_window_start
            and not e.resolved
        ]

        # Per-source auth failures (for ALERT)
        source_counts: Dict[str, int] = {}
        for e in recent_auth:
            source_counts[e.source] = source_counts.get(e.source, 0) + 1

        max_per_source = max(source_counts.values()) if source_counts else 0
        total_auth = len(recent_auth)
        total_exc = len(recent_exceptions)

        # Determine appropriate level (only escalate, never auto-downgrade here)
        target = ThreatLevel.NOMINAL

        if max_per_source >= AUTH_FAILURE_ALERT_THRESHOLD:
            target = max(target, ThreatLevel.ALERT)

        if total_auth >= AUTH_FAILURE_GUARDED_THRESHOLD or total_exc >= EXCEPTION_GUARDED_THRESHOLD:
            target = max(target, ThreatLevel.GUARDED)

        if total_auth >= AUTH_FAILURE_LOCKDOWN_THRESHOLD or total_exc >= EXCEPTION_LOCKDOWN_THRESHOLD:
            target = max(target, ThreatLevel.LOCKDOWN)

        # Only escalate — decay is handled by tick_decay()
        if target > self._level:
            old = self._level
            self._set_level(target)
            logger.warning(
                "THREAT ESCALATED %s → %s (auth_failures=%d, exceptions=%d, per_source_max=%d)",
                THREAT_LABELS[old], self.level_label, total_auth, total_exc, max_per_source,
            )
