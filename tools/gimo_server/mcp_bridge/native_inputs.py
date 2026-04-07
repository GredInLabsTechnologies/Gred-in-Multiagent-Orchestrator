"""R17 Cluster D — Pydantic input models for native MCP tools.

These models are the SINGLE SOURCE OF TRUTH for the parameter shape of the
affected native MCP tools. They serve two purposes:

1. They are exported via ``model_json_schema()`` so that the schema seen by
   MCP clients matches the actual function signature with no hand-crafted
   drift (resolves issue #9 — int→string parameter type drift).

2. They centralize parameter aliasing (deprecated old names) and cross-field
   validation (e.g. the XOR between ``plan_id`` and ``objective`` for
   ``gimo_generate_team_config``, restoring the objective mode lost in R16).

Aliases emit a ``DeprecationWarning`` for ONE round so external callers have
a clean migration path with no immediate external breakage.
"""
from __future__ import annotations

import warnings
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _warn_alias(old: str, new: str) -> None:
    warnings.warn(
        f"Parameter '{old}' is deprecated; use '{new}' instead.",
        DeprecationWarning,
        stacklevel=3,
    )


class EstimateCostInput(BaseModel):
    """Inputs for ``gimo_estimate_cost`` (#9 — int→string drift fix).

    Canonical names: ``model``, ``tokens_in``, ``tokens_out``.
    Deprecated aliases: ``input_tokens`` → ``tokens_in``,
    ``output_tokens`` → ``tokens_out``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    model: str = Field(..., description="Model identifier (e.g. 'claude-sonnet-4-6').")
    tokens_in: int = Field(1000, description="Input tokens (canonical name).")
    tokens_out: int = Field(500, description="Output tokens (canonical name).")

    @classmethod
    def from_call(
        cls,
        model: str,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> "EstimateCostInput":
        if input_tokens is not None and tokens_in is None:
            _warn_alias("input_tokens", "tokens_in")
            tokens_in = input_tokens
        if output_tokens is not None and tokens_out is None:
            _warn_alias("output_tokens", "tokens_out")
            tokens_out = output_tokens
        return cls(
            model=model,
            tokens_in=tokens_in if tokens_in is not None else 1000,
            tokens_out=tokens_out if tokens_out is not None else 500,
        )


class GenerateTeamConfigInput(BaseModel):
    """Inputs for ``gimo_generate_team_config`` (#10 — restore objective mode).

    Exactly one of ``plan_id`` or ``objective`` must be provided.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    plan_id: Optional[str] = Field(
        None, description="Existing plan/draft ID to generate team config from."
    )
    objective: Optional[str] = Field(
        None,
        description="Free-text objective; a draft will be created and materialized.",
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> "GenerateTeamConfigInput":
        if (self.plan_id is None) == (self.objective is None):
            raise ValueError(
                "Exactly one of 'plan_id' or 'objective' is required for "
                "gimo_generate_team_config."
            )
        return self


class VerifyProofChainInput(BaseModel):
    """Inputs for ``gimo_verify_proof_chain`` (#11 — optional thread_id).

    When ``thread_id`` is omitted, the tool falls back to the most recent
    verified chain (most recently updated thread).
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    thread_id: Optional[str] = Field(
        None,
        description=(
            "Thread ID whose proof chain to verify. If omitted, falls back to "
            "the most recently updated thread."
        ),
    )
