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
        proofs.sort(key=lambda proof: (proof.timestamp, proof.proof_id))
        return cls(thread_id=thread_id, proofs=proofs)

    def append(self, tool_name: str, args: Any, result: Any, mood: str, cost: float = 0.0) -> ExecutionProof:
        prev = self._proofs[-1] if self._proofs else None
        input_hash = _sha256_text(_canonical_json(args))
        output_hash = _sha256_text(_canonical_json(result))
        prev_chain_hash = prev.chain_hash if prev else ""
        chain_hash = _sha256_text(f"{prev_chain_hash}:{input_hash}:{output_hash}")
        proof = ExecutionProof(
            proof_id=f"proof_{uuid.uuid4().hex[:16]}",
            prev_proof_id=prev.proof_id if prev else "",
            thread_id=self.thread_id,
            tool_name=tool_name,
            input_hash=input_hash,
            output_hash=output_hash,
            mood=mood,
            cost_usd=float(cost or 0.0),
            timestamp=time.time(),
            chain_hash=chain_hash,
        )
        self._proofs.append(proof)
        return proof

    def verify(self) -> bool:
        prev: ExecutionProof | None = None
        for proof in self._proofs:
            expected_prev_id = prev.proof_id if prev else ""
            if proof.prev_proof_id != expected_prev_id:
                return False
            prev_chain_hash = prev.chain_hash if prev else ""
            expected_chain = _sha256_text(f"{prev_chain_hash}:{proof.input_hash}:{proof.output_hash}")
            if proof.chain_hash != expected_chain:
                return False
            prev = proof
        return True

    def to_list(self) -> List[ExecutionProof]:
        return list(self._proofs)
