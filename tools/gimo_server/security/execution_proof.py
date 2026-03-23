from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, List, Sequence


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _proof_chain_payload(
    *,
    proof_id: str,
    prev_proof_id: str,
    thread_id: str,
    tool_name: str,
    input_hash: str,
    output_hash: str,
    mood: str,
    cost_usd: float,
    timestamp: float,
    prev_chain_hash: str,
) -> str:
    return _canonical_json(
        {
            "proof_id": proof_id,
            "prev_proof_id": prev_proof_id,
            "thread_id": thread_id,
            "tool_name": tool_name,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "mood": mood,
            "cost_usd": float(cost_usd),
            "timestamp": float(timestamp),
            "prev_chain_hash": prev_chain_hash,
        }
    )


@dataclass
class ExecutionProof:
    proof_id: str
    prev_proof_id: str
    thread_id: str
    tool_name: str
    input_hash: str
    output_hash: str
    mood: str
    cost_usd: float
    timestamp: float
    chain_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionProofChain:
    def __init__(self, thread_id: str, proofs: Sequence[ExecutionProof] | None = None):
        self.thread_id = thread_id
        self._proofs: list[ExecutionProof] = list(proofs or [])

    @classmethod
    def from_records(cls, thread_id: str, records: Sequence[dict[str, Any]]) -> "ExecutionProofChain":
        proofs = [ExecutionProof(**record) for record in records]
        if not proofs:
            return cls(thread_id=thread_id, proofs=[])

        by_id = {proof.proof_id: proof for proof in proofs}
        if len(by_id) != len(proofs):
            raise ValueError("Duplicate proof_id detected in proof chain")

        heads = [proof for proof in proofs if not proof.prev_proof_id]
        if len(heads) != 1:
            raise ValueError("Proof chain must have exactly one root proof")

        children: dict[str, list[ExecutionProof]] = {}
        for proof in proofs:
            if proof.prev_proof_id and proof.prev_proof_id not in by_id:
                raise ValueError(f"Proof {proof.proof_id} references unknown predecessor {proof.prev_proof_id}")
            if proof.prev_proof_id:
                children.setdefault(proof.prev_proof_id, []).append(proof)

        ordered: list[ExecutionProof] = []
        seen: set[str] = set()
        current = heads[0]
        while current:
            if current.proof_id in seen:
                raise ValueError("Cycle detected in proof chain")
            ordered.append(current)
            seen.add(current.proof_id)
            next_items = children.get(current.proof_id, [])
            if len(next_items) > 1:
                raise ValueError(f"Proof chain is branching at {current.proof_id}")
            current = next_items[0] if next_items else None

        if len(seen) != len(proofs):
            raise ValueError("Proof chain is disconnected")

        return cls(thread_id=thread_id, proofs=ordered)

    def append(self, tool_name: str, args: Any, result: Any, mood: str, cost: float = 0.0) -> ExecutionProof:
        prev = self._proofs[-1] if self._proofs else None
        input_hash = _sha256_text(_canonical_json(args))
        output_hash = _sha256_text(_canonical_json(result))
        prev_chain_hash = prev.chain_hash if prev else ""
        proof_id = f"proof_{uuid.uuid4().hex[:16]}"
        prev_proof_id = prev.proof_id if prev else ""
        timestamp = time.time()
        normalized_cost = float(cost or 0.0)
        chain_hash = _sha256_text(
            _proof_chain_payload(
                proof_id=proof_id,
                prev_proof_id=prev_proof_id,
                thread_id=self.thread_id,
                tool_name=tool_name,
                input_hash=input_hash,
                output_hash=output_hash,
                mood=mood,
                cost_usd=normalized_cost,
                timestamp=timestamp,
                prev_chain_hash=prev_chain_hash,
            )
        )
        proof = ExecutionProof(
            proof_id=proof_id,
            prev_proof_id=prev_proof_id,
            thread_id=self.thread_id,
            tool_name=tool_name,
            input_hash=input_hash,
            output_hash=output_hash,
            mood=mood,
            cost_usd=normalized_cost,
            timestamp=timestamp,
            chain_hash=chain_hash,
        )
        self._proofs.append(proof)
        return proof

    def verify(self) -> bool:
        prev: ExecutionProof | None = None
        for proof in self._proofs:
            if proof.thread_id != self.thread_id:
                return False
            expected_prev_id = prev.proof_id if prev else ""
            if proof.prev_proof_id != expected_prev_id:
                return False
            prev_chain_hash = prev.chain_hash if prev else ""
            expected_chain = _sha256_text(
                _proof_chain_payload(
                    proof_id=proof.proof_id,
                    prev_proof_id=proof.prev_proof_id,
                    thread_id=proof.thread_id,
                    tool_name=proof.tool_name,
                    input_hash=proof.input_hash,
                    output_hash=proof.output_hash,
                    mood=proof.mood,
                    cost_usd=proof.cost_usd,
                    timestamp=proof.timestamp,
                    prev_chain_hash=prev_chain_hash,
                )
            )
            if proof.chain_hash != expected_chain:
                return False
            prev = proof
        return True

    def to_list(self) -> List[ExecutionProof]:
        return list(self._proofs)
