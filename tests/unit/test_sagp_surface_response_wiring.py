"""Regression tests for SurfaceResponseService — canonical SAGP component.

## Why this test exists

`SurfaceResponseService` is canonical per `docs/SYSTEM.md:468` and
`docs/architecture/SAGP.md:227-229`. A static-grep audit would flag it as an
orphan because the governance MCP tools currently return raw
`json.dumps(verdict.to_dict())` instead of dispatching through this formatter.

Per the "Disconnected != dead" rule in the GIMO project memory, we do NOT
delete unconnected canonical code — we annotate it with an enforcement test.
This file:

1. Locks in the public contract (``format_verdict`` / ``format_snapshot``
   classmethods receiving a verdict/snapshot + a ``SurfaceIdentity``).
2. Asserts the surface-capability dispatch still adapts output to
   ``mcp_apps``, ``ansi_colors``, and default JSON surfaces.
3. Prevents a future "looks unused, let's delete" cleanup pass from removing
   the formatter before the MCP governance tools have been rewired to use it.
"""
from __future__ import annotations

import json

from tools.gimo_server.models.governance import (
    GovernanceSnapshot,
    GovernanceVerdict,
)
from tools.gimo_server.models.surface import SurfaceIdentity
from tools.gimo_server.services.surface_response_service import (
    SurfaceResponseService,
)


def _sample_verdict() -> GovernanceVerdict:
    return GovernanceVerdict(
        allowed=True,
        policy_name="workspace_safe",
        risk_band="medium",
        trust_score=0.87,
        estimated_cost_usd=0.0123,
        requires_approval=True,
        circuit_breaker_state="closed",
        proof_id="proof_abc123",
        reasoning="Action permitted under policy 'workspace_safe'",
        constraints=("fs:sandbox", "hitl_required"),
    )


def _sample_snapshot() -> GovernanceSnapshot:
    return GovernanceSnapshot(
        surface_type="mcp",
        surface_name="regression-probe",
        active_policy="workspace_safe",
        trust_profile={"provider": 0.92, "model": 0.84, "tool": 0.77},
        budget_status={"status": "active"},
        gics_health={"daemon_alive": True, "entry_count": 42},
        proof_chain_length=3,
    )


# ── format_verdict dispatch ──────────────────────────────────────────────────


def test_format_verdict_json_is_default():
    """Surfaces without rich / ansi capabilities receive structured JSON."""
    surface = SurfaceIdentity(surface_type="mcp_generic", surface_name="probe")
    out = SurfaceResponseService.format_verdict(_sample_verdict(), surface)

    parsed = json.loads(out)
    assert parsed["allowed"] is True
    assert parsed["policy_name"] == "workspace_safe"
    assert parsed["risk_band"] == "medium"
    assert parsed["proof_id"] == "proof_abc123"
    assert "fs:sandbox" in parsed["constraints"]


def test_format_verdict_mcp_apps_returns_rich_markdown():
    """MCP App surfaces get rich markdown with table + reasoning block."""
    surface = SurfaceIdentity(
        surface_type="claude_app",
        surface_name="Claude Code",
        capabilities=frozenset({"mcp_apps"}),
    )
    out = SurfaceResponseService.format_verdict(_sample_verdict(), surface)

    assert "**Governance Verdict**" in out
    assert "| Policy |" in out  # markdown table header
    assert "`workspace_safe`" in out
    assert "MEDIUM" in out  # risk band upper-cased
    assert "0.87" in out  # trust score
    assert "Action permitted" in out


def test_format_verdict_ansi_uses_terminal_escape_codes():
    """ANSI-capable surfaces get colorized single-line output."""
    surface = SurfaceIdentity(
        surface_type="cli",
        surface_name="gimo-cli",
        capabilities=frozenset({"ansi_colors"}),
    )
    out = SurfaceResponseService.format_verdict(_sample_verdict(), surface)

    assert "\033[" in out, "ANSI surface must receive ANSI escape codes"
    assert "ALLOWED" in out
    assert "workspace_safe" in out
    assert "MEDIUM" in out


def test_format_verdict_denied_shows_denied_marker():
    """Denied verdicts must be visually distinguishable in every format."""
    denied = GovernanceVerdict(
        allowed=False,
        policy_name="read_only",
        risk_band="high",
        trust_score=0.4,
        estimated_cost_usd=0.0,
        requires_approval=True,
        circuit_breaker_state="open",
        proof_id="proof_denied",
        reasoning="Circuit breaker is OPEN",
        constraints=(),
    )

    mcp_surface = SurfaceIdentity(
        surface_type="claude_app",
        surface_name="Claude",
        capabilities=frozenset({"mcp_apps"}),
    )
    ansi_surface = SurfaceIdentity(
        surface_type="cli",
        surface_name="cli",
        capabilities=frozenset({"ansi_colors"}),
    )

    rich_out = SurfaceResponseService.format_verdict(denied, mcp_surface)
    ansi_out = SurfaceResponseService.format_verdict(denied, ansi_surface)

    # Rich uses a red cross icon
    assert "\u274c" in rich_out
    # ANSI must mark it DENIED
    assert "DENIED" in ansi_out


# ── format_snapshot dispatch ─────────────────────────────────────────────────


def test_format_snapshot_json_is_default():
    surface = SurfaceIdentity(surface_type="mcp_generic", surface_name="probe")
    out = SurfaceResponseService.format_snapshot(_sample_snapshot(), surface)

    parsed = json.loads(out)
    assert parsed["surface_type"] == "mcp"
    assert parsed["active_policy"] == "workspace_safe"
    assert parsed["proof_chain_length"] == 3
    assert parsed["trust_profile"]["provider"] == 0.92


def test_format_snapshot_mcp_apps_renders_trust_bars():
    surface = SurfaceIdentity(
        surface_type="claude_app",
        surface_name="Claude Code",
        capabilities=frozenset({"mcp_apps"}),
    )
    out = SurfaceResponseService.format_snapshot(_sample_snapshot(), surface)

    assert "**GIMO Governance Snapshot**" in out
    assert "**Trust Profile:**" in out
    assert "provider:" in out
    # Unicode block-char bars
    assert "\u2588" in out or "\u2591" in out


def test_format_snapshot_ansi_uses_terminal_escape_codes():
    surface = SurfaceIdentity(
        surface_type="cli",
        surface_name="gimo-cli",
        capabilities=frozenset({"ansi_colors"}),
    )
    out = SurfaceResponseService.format_snapshot(_sample_snapshot(), surface)

    assert "\033[" in out
    assert "GIMO Governance" in out
    assert "workspace_safe" in out


# ── Public contract guard ────────────────────────────────────────────────────


def test_surface_response_service_public_classmethods_exist():
    """Lock in the public API documented in SYSTEM.md:468 and SAGP.md:227.

    If future refactors rename or remove these classmethods, this test fails
    loudly — matching what docs promise a consumer can call.
    """
    assert callable(SurfaceResponseService.format_verdict)
    assert callable(SurfaceResponseService.format_snapshot)
