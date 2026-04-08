from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ...ops_models import TrustEvent

logger = logging.getLogger("orchestrator.services.storage.trust")


class TrustEventAppendOnlyError(RuntimeError):
    """R18 Change 4 — raised when code attempts to mutate or delete a trust event.

    Trust events are append-only by contract: the audit trail would be
    meaningless if past events could be rewritten. This exception is the
    storage-boundary equivalent of a ``BEFORE UPDATE``/``BEFORE DELETE``
    RAISE(ABORT) SQLite trigger. The plan v2.2 called for SQLite triggers,
    but the actual persistence layer is GICS, so enforcement moves to the
    boundary that every write and delete must traverse.
    """

def _normalize_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if value:
        return str(value)
    return datetime.now(timezone.utc).isoformat()

class TrustStorage:
    """Storage logic for trust events and dimension records (Hot/Cold tiers).
    Persists entirely via GICS.
    """

    def __init__(self, conn: Optional[Any] = None, gics_service: Optional[Any] = None):
        self._conn = conn # Kept for backward compatibility
        self.gics = gics_service

    def ensure_tables(self) -> None:
        """No-op: using GICS."""
        pass

    def save_trust_event(self, event: TrustEvent | Dict[str, Any]) -> None:
        if not self.gics:
            return

        event_data = event.model_dump() if isinstance(event, TrustEvent) else dict(event)
        timestamp = _normalize_timestamp(event_data.get("timestamp"))
        event_data["timestamp"] = timestamp

        try:
            event_key = f"te:{event_data.get('dimension_key')}:{timestamp}"
            # R18 Change 4 — append-only enforcement at the storage boundary.
            # Refuse to overwrite an existing trust event. Collisions within
            # the same microsecond are vanishingly rare but if they occur the
            # caller must surface a retry, not silently rewrite history.
            existing = None
            try:
                existing = self.gics.get(event_key)
            except Exception:
                existing = None
            if existing:
                raise TrustEventAppendOnlyError(
                    f"Refusing to overwrite trust event {event_key} "
                    f"(append-only contract)"
                )
            self.gics.put(event_key, event_data)
        except TrustEventAppendOnlyError:
            raise
        except Exception as e:
            logger.error("Failed to push trust event to GICS: %s", e)

    def delete_trust_event(self, event_key: str) -> None:
        """R18 Change 4 — always raises. Trust events are append-only."""
        raise TrustEventAppendOnlyError(
            f"delete_trust_event({event_key!r}) forbidden — trust events are append-only"
        )

    def update_trust_event(self, event_key: str, patch: Dict[str, Any]) -> None:
        """R18 Change 4 — always raises. Trust events are append-only."""
        raise TrustEventAppendOnlyError(
            f"update_trust_event({event_key!r}) forbidden — trust events are append-only"
        )

    def save_trust_events(self, events: List[TrustEvent | Dict[str, Any]]) -> None:
        if not events or not self.gics:
            return

        # R18 Change 4 — batch path must go through the same append-only
        # guard as the single-event path. Delegate to ``save_trust_event``
        # so the overwrite check fires for every entry.
        for event in events:
            try:
                self.save_trust_event(event)
            except TrustEventAppendOnlyError:
                raise
            except Exception as e:
                logger.error("Failed to push batch trust event to GICS: %s", e)

    def list_trust_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.gics:
            return []
            
        try:
            items = self.gics.scan(prefix="te:", include_fields=True)
            events = [item.get("fields", {}) for item in items]
            events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            return events[:limit]
        except Exception as e:
            logger.error("Failed to list trust events from GICS: %s", e)
            return []

    def list_trust_events_by_dimension(self, dimension_key: str, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.gics:
            return []
            
        try:
            prefix = f"te:{dimension_key}:"
            items = self.gics.scan(prefix=prefix, include_fields=True)
            events = [item.get("fields", {}) for item in items]
            events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            return events[:limit]
        except Exception as e:
            logger.error("Failed to list trust events by dimension from GICS: %s", e)
            return []

    def get_trust_record(self, dimension_key: str) -> Optional[Dict[str, Any]]:
        if not self.gics:
            return None

        try:
            # Try canonical tr: prefix first, fall back to bare key for old data
            result = self.gics.get(f"{self._RECORD_PREFIX}{dimension_key}")
            if result and "fields" in result:
                return result["fields"]
            result = self.gics.get(dimension_key)
            if result and "fields" in result:
                return result["fields"]
        except Exception as e:
            logger.error("Failed to query get_trust_record from GICS for %s: %s", dimension_key, e)

        return None

    # Canonical GICS prefix for trust dimension records.
    _RECORD_PREFIX = "tr:"

    def upsert_trust_record(self, record: Dict[str, Any]) -> None:
        if not self.gics:
            return

        try:
            dimension_key = record.get("dimension_key")
            if dimension_key:
                record["updated_at"] = _normalize_timestamp(datetime.now(timezone.utc))
                # Store under tr: prefix AND under bare key for backward compat
                self.gics.put(f"{self._RECORD_PREFIX}{dimension_key}", record)
                self.gics.put(dimension_key, record)
        except Exception as e:
            logger.error("Failed to push trust record %s to GICS: %s", record.get("dimension_key"), e)

    def list_trust_records(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.gics:
            return []

        try:
            # Primary: scan canonical tr: prefix (populated by upsert_trust_record)
            items = self.gics.scan(prefix=self._RECORD_PREFIX, include_fields=True)
            records = [item.get("fields", {}) for item in items if "dimension_key" in item.get("fields", {})]

            # Fallback: if no tr:-prefixed records yet (pre-migration data),
            # scan broadly but with tighter heuristics.
            if not records:
                items = self.gics.scan(prefix="", include_fields=True)
                for item in items:
                    key = item.get("key", "")
                    fields = item.get("fields", {})
                    if (
                        "dimension_key" in fields
                        and "approvals" in fields
                        and not key.startswith(("te:", "ce:", "er:", "ed:", "wf:", "cp:", "cb:", "tk:", "ckpt:", "revoked:"))
                    ):
                        records.append(fields)

            records.sort(key=lambda x: x.get("updated_at") or x.get("last_updated") or "", reverse=True)
            return records[:limit]
        except Exception as e:
            logger.error("Failed to list trust records: %s", e)
            return []

    def save_dimension(self, dimension_key: str, data: Dict[str, Any]) -> None:
        if "dimension_key" not in data:
            data["dimension_key"] = dimension_key
        self.upsert_trust_record(data)

    def query_dimension(self, dimension_key: str) -> Optional[Dict[str, Any]]:
        return self.get_trust_record(dimension_key)
