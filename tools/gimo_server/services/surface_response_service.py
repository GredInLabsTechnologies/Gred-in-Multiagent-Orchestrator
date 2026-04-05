"""Surface Response Service: Formats governance responses per surface capabilities.

Adapts the same GovernanceVerdict/Snapshot into the best format for
each surface: JSON for APIs, ANSI for terminals, ui:// for MCP Apps.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ..models.governance import GovernanceSnapshot, GovernanceVerdict
from ..models.surface import SurfaceIdentity

logger = logging.getLogger("orchestrator.surface_response")


class SurfaceResponseService:
    """Format governance data according to surface capabilities."""

    @classmethod
    def format_verdict(cls, verdict: GovernanceVerdict, surface: SurfaceIdentity) -> str:
        """Format a GovernanceVerdict for the given surface."""
        if surface.supports_mcp_apps:
            return cls._format_verdict_rich(verdict)
        if surface.supports("ansi_colors"):
            return cls._format_verdict_ansi(verdict)
        return cls._format_verdict_json(verdict)

    @classmethod
    def format_snapshot(cls, snapshot: GovernanceSnapshot, surface: SurfaceIdentity) -> str:
        """Format a GovernanceSnapshot for the given surface."""
        if surface.supports_mcp_apps:
            return cls._format_snapshot_rich(snapshot)
        if surface.supports("ansi_colors"):
            return cls._format_snapshot_ansi(snapshot)
        return json.dumps(snapshot.to_dict(), indent=2)

    # ── JSON (default) ────────────────────────────────────────────────────

    @classmethod
    def _format_verdict_json(cls, verdict: GovernanceVerdict) -> str:
        return json.dumps(verdict.to_dict(), indent=2)

    # ── Rich text (MCP Apps capable) ──────────────────────────────────────

    @classmethod
    def _format_verdict_rich(cls, verdict: GovernanceVerdict) -> str:
        icon = "\u2705" if verdict.allowed else "\u274c"
        lines = [
            f"{icon} **Governance Verdict**",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Policy | `{verdict.policy_name}` |",
            f"| Risk | **{verdict.risk_band.upper()}** |",
            f"| Trust | {verdict.trust_score:.2f} |",
            f"| Cost | ${verdict.estimated_cost_usd:.4f} |",
            f"| HITL | {'Required' if verdict.requires_approval else 'Not needed'} |",
            f"| Circuit | {verdict.circuit_breaker_state} |",
            f"",
            f"> {verdict.reasoning}",
        ]
        if verdict.constraints:
            lines.append(f"\nConstraints: {', '.join(verdict.constraints)}")
        return "\n".join(lines)

    @classmethod
    def _format_snapshot_rich(cls, snapshot: GovernanceSnapshot) -> str:
        lines = [
            f"**GIMO Governance Snapshot**",
            f"",
            f"Surface: `{snapshot.surface_type}` ({snapshot.surface_name})",
            f"Policy: `{snapshot.active_policy}`",
            f"Proofs: {snapshot.proof_chain_length}",
        ]
        if snapshot.trust_profile:
            lines.append("\n**Trust Profile:**")
            for dim, score in snapshot.trust_profile.items():
                bar = cls._score_bar(score)
                lines.append(f"  {dim}: {bar} {score:.2f}")
        return "\n".join(lines)

    # ── ANSI (terminal) ───────────────────────────────────────────────────

    @classmethod
    def _format_verdict_ansi(cls, verdict: GovernanceVerdict) -> str:
        green = "\033[32m"
        red = "\033[31m"
        yellow = "\033[33m"
        reset = "\033[0m"
        bold = "\033[1m"

        icon_color = green if verdict.allowed else red
        risk_color = {"low": green, "medium": yellow, "high": red}.get(verdict.risk_band, reset)

        lines = [
            f"{icon_color}{bold}{'ALLOWED' if verdict.allowed else 'DENIED'}{reset} | "
            f"Policy: {verdict.policy_name} | "
            f"Risk: {risk_color}{verdict.risk_band.upper()}{reset} | "
            f"Trust: {verdict.trust_score:.2f} | "
            f"Cost: ${verdict.estimated_cost_usd:.4f}",
        ]
        if verdict.requires_approval:
            lines.append(f"  {yellow}HITL required{reset}")
        lines.append(f"  {verdict.reasoning}")
        return "\n".join(lines)

    @classmethod
    def _format_snapshot_ansi(cls, snapshot: GovernanceSnapshot) -> str:
        bold = "\033[1m"
        reset = "\033[0m"
        lines = [
            f"{bold}GIMO Governance{reset} | {snapshot.surface_type} | Policy: {snapshot.active_policy}",
        ]
        if snapshot.trust_profile:
            for dim, score in snapshot.trust_profile.items():
                lines.append(f"  {dim}: {cls._score_bar_ansi(score)} {score:.2f}")
        return "\n".join(lines)

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _score_bar(score: float, width: int = 10) -> str:
        filled = round(score * width)
        return "\u2588" * filled + "\u2591" * (width - filled)

    @staticmethod
    def _score_bar_ansi(score: float, width: int = 10) -> str:
        green = "\033[32m"
        yellow = "\033[33m"
        red = "\033[31m"
        reset = "\033[0m"
        color = green if score >= 0.7 else yellow if score >= 0.4 else red
        filled = round(score * width)
        return f"{color}{'#' * filled}{'.' * (width - filled)}{reset}"
