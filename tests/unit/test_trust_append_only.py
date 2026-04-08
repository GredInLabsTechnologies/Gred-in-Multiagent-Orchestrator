"""R18 Change 4 — trust event append-only enforcement tests."""
from __future__ import annotations

import pytest

from tools.gimo_server.services.storage.trust_storage import (
    TrustEventAppendOnlyError,
    TrustStorage,
)


class _FakeGics:
    def __init__(self):
        self.store = {}

    def put(self, key, value):
        self.store[key] = value

    def get(self, key):
        val = self.store.get(key)
        if val is None:
            return None
        return {"fields": val}


def test_delete_trust_event_always_raises():
    ts = TrustStorage(gics_service=_FakeGics())
    with pytest.raises(TrustEventAppendOnlyError):
        ts.delete_trust_event("te:provider:anthropic:2026-04-08T00:00:00Z")


def test_update_trust_event_always_raises():
    ts = TrustStorage(gics_service=_FakeGics())
    with pytest.raises(TrustEventAppendOnlyError):
        ts.update_trust_event("te:provider:anthropic:2026-04-08T00:00:00Z", {"foo": 1})


def test_save_trust_event_refuses_overwrite():
    ts = TrustStorage(gics_service=_FakeGics())
    ev = {
        "dimension_key": "provider:anthropic",
        "timestamp": "2026-04-08T00:00:00+00:00",
        "kind": "approval",
    }
    ts.save_trust_event(ev)
    with pytest.raises(TrustEventAppendOnlyError):
        ts.save_trust_event(ev)
