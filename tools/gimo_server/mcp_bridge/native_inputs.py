"""R17.1 Cluster D — Pydantic input models for native MCP tools.

These models are the SINGLE SOURCE OF TRUTH for the parameter shape of the
affected native MCP tools. The published MCP schema (introspected via
``mcp._tool_manager._tools[name].parameters``) MUST match the canonical
fields here. Tests in ``test_native_tools_r17_1_schema.py`` enforce that
parity by introspecting the live FastMCP registry, not just the helper.

R17.1 change: the deprecated ``input_tokens`` / ``output_tokens`` aliases for
``gimo_estimate_cost`` were removed after their one-round deprecation. The
function signature now matches ``EstimateCostInput`` exactly, eliminating the
last source of schema drift.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EstimateCostInput(BaseModel):
    """Inputs for ``gimo_estimate_cost``.

    Canonical names: ``model``, ``tokens_in``, ``tokens_out``. No aliases.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., description="Model identifier (e.g. 'claude-sonnet-4-6').")
    tokens_in: int = Field(1000, description="Input tokens.")
    tokens_out: int = Field(500, description="Output tokens.")


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


class GicsModelReliabilityInput(BaseModel):
    """R18 Change 5 — canonical input for ``gimo_gics_model_reliability``."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., description="Model identifier, e.g. 'gpt-4o'.")


class GicsAnomalyReportInput(BaseModel):
    """R18 Change 5 — canonical (empty) input for ``gimo_gics_anomaly_report``."""

    model_config = ConfigDict(extra="forbid")


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
