import pytest
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from tools.gimo_server.services.trust_engine import CircuitBreakerConfig, TrustEngine, TrustThresholds
from tools.gimo_server.services.trust_event_buffer import TrustEventBuffer
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server import config

# Add test token to config.TOKENS to bypass real verify_token 401s
config.TOKENS.add("a"*32)

# ── Stubs & Helper ────────────────────────────────────────

class StubTrustStore:
    def __init__(self, storage):
        self.storage = storage
    def save_dimension(self, dimension_key, data):
        self.storage.upsert_trust_record(data)

class StubStorage:
    def __init__(self, events=None):
        self._events = list(events or [])
        self._records = {}
        self._cb_cfg = {}
        self.saved_batches = []
    def list_trust_events(self, limit: int = 100): return self._events[:limit]
    def get_trust_record(self, dimension_key: str): return self._records.get(dimension_key)
    def upsert_trust_record(self, record): self._records[record["dimension_key"]] = dict(record)
    def get_circuit_breaker_config(self, dimension_key: str): return self._cb_cfg.get(dimension_key)
    def save_trust_events(self, events): self.saved_batches.append(list(events))

def _make_events(n: int, dimension: str = "tool|git_diff|m|t") -> list:
    now = datetime.now(timezone.utc)
    return [{"timestamp": now.isoformat(), "dimension_key": dimension, "outcome": "approved" if i % 5 != 0 else "error"} for i in range(n)]

def _auth(role: str):
    return lambda: AuthContext(token="t", role=role)

# ── Core Engine Tests ─────────────────────────────────────

class TestTrustEngineCore:
    def test_query_dimension_auto_approve(self):
        events = [{"dimension_key": "d", "outcome": "approved", "timestamp": "2026-01-01Z"} for _ in range(25)]
        engine = TrustEngine(StubTrustStore(StubStorage(events)))
        record = engine.query_dimension("d")
        assert record["approvals"] == 25
        assert record["policy"] == "auto_approve"

    def test_circuit_breaker_opens(self):
        dimension = "d"
        events = [{"dimension_key": dimension, "outcome": "error", "timestamp": "2026-01-01Z"} for _ in range(5)]
        engine = TrustEngine(StubTrustStore(StubStorage(events)), circuit_breaker=CircuitBreakerConfig(window=5, failure_threshold=5))
        record = engine.query_dimension(dimension)
        assert record["circuit_state"] == "open"
        assert record["policy"] == "blocked"

# ── Event Buffer & Performance ──────────────────────────────

class TestTrustInfrastructure:
    def test_buffer_flushes(self):
        storage = StubStorage()
        buffer = TrustEventBuffer(storage=storage, max_events=2, flush_interval_seconds=999)
        buffer.add_event({"tool": "a"})
        assert buffer.size == 1
        buffer.add_event({"tool": "b"})
        assert len(storage.saved_batches) == 1

    @pytest.mark.parametrize("n_events", [200, 500])
    def test_performance_overhead(self, n_events):
        """Verify TrustEngine overhead stays under 15ms budget (consolidated from latency tests)."""
        events = _make_events(n_events)
        engine = TrustEngine(StubTrustStore(StubStorage(events)))
        start = time.perf_counter()
        for _ in range(50):
            engine.query_dimension("tool|git_diff|m|t")
        elapsed = (time.perf_counter() - start) / 50 * 1000
        assert elapsed < 15

# ── Route & Policy Tests ───────────────────────────────────

class TestTrustRoutes:
    def test_query_returns_data(self, test_client):
        from tools.gimo_server.main import app
        app.dependency_overrides[verify_token] = _auth("operator")
        with patch("tools.gimo_server.routers.ops.trust_router.TrustEngine.query_dimension") as m:
            m.return_value = {"score": 0.9}
            res = test_client.post("/ops/trust/query", json={"dimension_key": "k"})
            assert res.status_code == 200
            assert abs(res.json()["score"] - 0.9) < 1e-9
        app.dependency_overrides.clear()

    @pytest.mark.parametrize("role,expected_status", [
        ("actions", 403),
        ("operator", 403),
        ("admin", 200),
    ])
    def test_cb_config_rbac(self, test_client, role, expected_status):
        from tools.gimo_server.main import app
        app.dependency_overrides[verify_token] = _auth(role)
        res = test_client.put("/ops/trust/circuit-breaker/k", json={"window": 1})
        assert res.status_code == expected_status
        app.dependency_overrides.clear()

# ── Rate Limiting (Migrated from security_core) ──────────────

class TestRateLimiting:
    def test_rate_limit_functional(self, test_client):
        """Verify rate limiting triggers 429 after threshold (Consolidated)."""
        # Test client is whitelisted usually, so we ensure it hits if we spam
        # or we test the internal check_rate_limit if needed.
        # Here we test via the client to ensure the middleware works.
        from tools.gimo_server.security.rate_limit import rate_limit_store
        rate_limit_store.clear()
        
        # We simulate the token to bypass 401
        headers = {"Authorization": "Bearer " + "a"*32}
        
        from tools.gimo_server.security import rate_limit
        from datetime import datetime
        
        # Populate real store for multiple common test keys to trigger 429
        # TestClient can identify as 'testclient', '127.0.0.1', or 'unknown'
        data = {
            "count": rate_limit.RATE_LIMIT_PER_MIN + 1,
            "start_time": datetime.now()
        }
        for ip in ["127.0.0.1", "testclient", "unknown"]:
            rate_limit.rate_limit_store[ip] = data.copy()
        
        try:
            res = test_client.get("/status", headers=headers)
            assert res.status_code == 429
        finally:
            rate_limit.rate_limit_store.clear()
