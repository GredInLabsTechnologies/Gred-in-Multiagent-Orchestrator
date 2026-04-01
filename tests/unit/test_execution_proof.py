from __future__ import annotations

from unittest.mock import patch

from tools.gimo_server.security.execution_proof import ExecutionProofChain


def test_execution_proof_chain_round_trip_and_verify():
    chain = ExecutionProofChain("thread_1")
    first = chain.append("read_file", {"path": "a.py"}, {"status": "success"}, mood="forensic", cost=0.0)
    second = chain.append("write_file", {"path": "a.py"}, {"status": "success"}, mood="executor", cost=0.0)

    restored = ExecutionProofChain.from_records("thread_1", [proof.to_dict() for proof in chain.to_list()])

    assert restored.verify() is True
    assert restored.to_list()[0].proof_id == first.proof_id
    assert restored.to_list()[1].prev_proof_id == second.prev_proof_id


def test_execution_proof_chain_detects_tampering():
    chain = ExecutionProofChain("thread_2")
    chain.append("search_text", {"pattern": "todo"}, {"status": "success"}, mood="forensic", cost=0.0)
    chain.append("patch_file", {"path": "b.py"}, {"status": "success"}, mood="executor", cost=0.0)

    tampered = [proof.to_dict() for proof in chain.to_list()]
    tampered[1]["output_hash"] = "bad"

    restored = ExecutionProofChain.from_records("thread_2", tampered)
    assert restored.verify() is False


def test_execution_proof_chain_detects_metadata_tampering():
    chain = ExecutionProofChain("thread_3")
    chain.append("read_file", {"path": "a.py"}, {"status": "success"}, mood="forensic", cost=0.0)

    tampered = [proof.to_dict() for proof in chain.to_list()]
    tampered[0]["mood"] = "executor"

    restored = ExecutionProofChain.from_records("thread_3", tampered)
    assert restored.verify() is False


def test_execution_proof_chain_rebuilds_linked_order_even_with_same_timestamps():
    with patch("tools.gimo_server.security.execution_proof.time.time", return_value=123.0):
        chain = ExecutionProofChain("thread_4")
        first = chain.append("read_file", {"path": "a.py"}, {"status": "success"}, mood="forensic", cost=0.0)
        second = chain.append("read_file", {"path": "b.py"}, {"status": "success"}, mood="forensic", cost=0.0)

    restored = ExecutionProofChain.from_records("thread_4", [proof.to_dict() for proof in chain.to_list()])

    assert restored.verify() is True
    assert [proof.proof_id for proof in restored.to_list()] == [first.proof_id, second.proof_id]
