"""R17 Cluster E.1 — TrustDashboardEntry contract tests."""

from __future__ import annotations

from typing import Any, Dict, List

from tools.gimo_server.services.trust_engine import TrustEngine


class _StubStorage:
    def __init__(self, events: List[Dict[str, Any]]):
        self._events = events
        self._records: Dict[str, Dict[str, Any]] = {}

    def list_trust_events(self, *, limit: int = 5000):
        return list(self._events)

    def list_trust_events_by_dimension(self, dimension_key: str, *, limit: int = 50):
        return [e for e in self._events if e.get("dimension_key") == dimension_key][:limit]

    def upsert_trust_record(self, record):
        self._records[record["dimension_key"]] = record

    def save_dimension(self, key, record):
        self._records[key] = record

    def get_trust_record(self, key):
        return self._records.get(key)

    def get_circuit_breaker_config(self, key):
        return None


def _events():
    return [
        {"dimension_key": "tool:read|*|*|*", "outcome": "approved", "post_check_passed": True, "timestamp": "2026-04-07T00:00:00+00:00"},
        {"dimension_key": "tool:read|*|*|*", "outcome": "approved", "post_check_passed": True, "timestamp": "2026-04-07T00:01:00+00:00"},
    ]


def test_trust_engine_dashboard_returns_canonical_entries():
    storage = _StubStorage(_events())
    engine = TrustEngine(storage)
    rows = engine.dashboard()
    assert rows, "expected at least one row"
    row = rows[0]
    # Canonical fields the renderer reads
    assert "dimension" in row
    assert "score" in row
    assert "state" in row
    assert isinstance(row["dimension"], str) and row["dimension"]
    assert isinstance(row["score"], (int, float))
    assert isinstance(row["state"], str)
    # Legacy aliases preserved for web UI / MCP bridge
    assert row.get("dimension_key") == row["dimension"]
    assert row.get("circuit_state") == row["state"]


def test_trust_dashboard_router_envelope_uses_entries(test_client, valid_token, monkeypatch):
    from tools.gimo_server.routers.ops import trust_router

    class _Engine:
        def __init__(self, *_a, **_kw):
            pass

        def dashboard(self, *, limit=100):
            return [
                {
                    "dimension": "tool:x",
                    "score": 0.91,
                    "state": "closed",
                    "policy": "auto_approve",
                    "approvals": 22,
                    "rejections": 0,
                    "failures": 0,
                    "auto_approvals": 22,
                    "streak": 22,
                    "last_updated": None,
                    "dimension_key": "tool:x",
                    "circuit_state": "closed",
                    "circuit_opened_at": None,
                }
            ]

    monkeypatch.setattr(trust_router, "TrustEngine", _Engine)

    resp = test_client.get(
        "/ops/trust/dashboard",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
    assert isinstance(data["entries"], list) and data["entries"]
    row = data["entries"][0]
    assert row["dimension"] == "tool:x"
    assert row["state"] == "closed"
    assert row["score"] == 0.91
    # legacy alias remains for compat
    assert "items" in data


def test_cli_trust_status_renders_non_empty_columns():
    from gimo_cli.render import TRUST_STATUS

    payload = {
        "entries": [
            {
                "dimension": "tool:x",
                "score": 0.91,
                "state": "closed",
            }
        ],
        "count": 1,
    }
    # Minimal renderer assertion: spec unwrap key + columns must match
    assert TRUST_STATUS.unwrap == "entries"
    for col in TRUST_STATUS.columns:
        assert col in payload["entries"][0], f"missing column {col}"
