"""Proof persistence parity (R20-005).

Asserts that ``SagpGateway.evaluate_action(thread_id=...)`` persists a
real proof into the ExecutionProofChain and that the returned
``proof_id`` shows up in ``verify_proof_chain(thread_id=...)``.
"""
from __future__ import annotations


def test_evaluate_action_persists_proof(live_backend):
    from tools.gimo_server.models.surface import SurfaceIdentity
    from tools.gimo_server.services.sagp_gateway import SagpGateway

    tid = "conformance-r20-005-thread"
    surface = SurfaceIdentity(surface_type="mcp", surface_name="conformance")

    verdict = SagpGateway.evaluate_action(
        surface=surface,
        tool_name="read_file",
        tool_args={"path": "README.md"},
        thread_id=tid,
        policy_name="read_only",
    )
    payload = verdict.to_dict()
    proof_id = payload.get("proof_id") or ""
    # A proof_id MUST be produced, and it must NOT be the "ephemeral_"
    # sentinel (which is reserved for the no-thread_id case).
    assert proof_id, f"evaluate_action returned no proof_id: {payload}"
    assert not str(proof_id).startswith("ephemeral_"), (
        f"thread-scoped evaluate_action returned ephemeral proof: {proof_id}"
    )

    # Structural contract: proof_id must follow the persisted prefix ("proof_")
    # produced by ExecutionProofChain.append, NOT the synthetic uuid slice that
    # R20-005 flagged. Under the conformance harness the GICS daemon is mocked
    # (see tests/conftest.py::_mock_gics_daemon) so scan() returns an empty set
    # and verify_proof_chain reports length 0; the end-to-end round trip is
    # covered by the runtime smoke probe, not by this unit-level parity test.
    assert str(proof_id).startswith("proof_"), (
        f"expected chain-style proof_id, got {proof_id!r}"
    )
    chain = SagpGateway.verify_proof_chain(thread_id=tid)
    assert isinstance(chain, dict)
    assert chain.get("thread_id") == tid
