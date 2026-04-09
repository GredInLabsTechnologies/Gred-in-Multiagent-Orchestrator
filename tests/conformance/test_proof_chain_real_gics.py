"""Real GICS proof-chain round-trip (R20-005, hardened).

The companion ``test_proof_persistence_parity.py`` only validates the
``proof_``-prefix contract under the session-scoped mocked GICS daemon
(see ``tests/conftest.py::_mock_gics_daemon``), where ``GICSClient._call``
is a noop and ``scan()`` returns nothing — meaning ``verify_proof_chain``
always reports ``length=0`` regardless of how many proofs were appended.
That left the *round-trip* (persist → scan → verify) untested.

This test installs an in-memory GICS substitute on
``StorageService._shared_gics`` for the duration of one call, runs
``SagpGateway.evaluate_action`` end-to-end, and asserts that
``verify_proof_chain`` reads the same proof back via the ``put → scan``
contract used in production code.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from tools.gimo_server.models.surface import SurfaceIdentity
from tools.gimo_server.services.sagp_gateway import SagpGateway
from tools.gimo_server.services.storage_service import StorageService


class _InMemoryGics:
    """Minimal in-memory GICS substitute for the proof persist/scan loop."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    def put(self, key: str, value: Dict[str, Any]) -> None:
        self._store[key] = dict(value)

    def scan(self, *, prefix: str = "", include_fields: bool = False) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for key, fields in self._store.items():
            if not key.startswith(prefix):
                continue
            row: Dict[str, Any] = {"key": key}
            if include_fields:
                row["fields"] = dict(fields)
            rows.append(row)
        return rows


def test_evaluate_action_persists_and_verifies_via_real_gics(monkeypatch):
    fake = _InMemoryGics()
    prev = StorageService._shared_gics
    StorageService.set_shared_gics(fake)  # type: ignore[arg-type]
    try:
        tid = "conformance-r20-005-real-gics"
        surface = SurfaceIdentity(surface_type="mcp", surface_name="conformance")

        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="read_file",
            tool_args={"path": "README.md"},
            thread_id=tid,
            policy_name="read_only",
        )
        proof_id = verdict.to_dict().get("proof_id") or ""
        assert proof_id.startswith("proof_"), proof_id

        # Direct GICS state — the put() reached the store.
        keys = [k for k in fake._store if k.startswith(f"ops:proof:{tid}:")]
        assert keys, f"no proof persisted into GICS for thread {tid}"
        assert any(proof_id in k for k in keys), keys

        # Round-trip via verify_proof_chain (which uses scan + chain rebuild).
        chain = SagpGateway.verify_proof_chain(thread_id=tid)
        assert chain.get("thread_id") == tid
        assert chain.get("length", 0) >= 1, chain
        assert chain.get("state") == "present", chain
        assert chain.get("valid") is True, chain
        # Subject/executor attribution flows through end-to-end.
        assert chain.get("subject", {}).get("id") == tid
        assert chain.get("executor", {}).get("type") == "sagp"
    finally:
        StorageService.set_shared_gics(prev)  # type: ignore[arg-type]
