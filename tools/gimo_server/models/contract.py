"""GimoContract: Single source of truth that reconciles all runtime configuration.

This contract is created at the start of each operation and ensures that:
- Identity (caller_role) is validated
- Provider (model_id) is resolved once and immutable
- Workspace is explicit and confirmed
- Schema constraints (valid_roles) are derived from Pydantic, not hardcoded
- License plan is propagated from startup

This prevents the 5 disconnected sources of truth problem revealed in E2E audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args

from tools.gimo_server.models.agent import AgentRole


@dataclass(frozen=True)
class GimoContract:
    """Immutable contract that binds identity, provider, workspace, and schema for an operation.

    All fields are frozen to prevent accidental mutation during execution.
    """

    # ── IDENTITY (WHO) ────────────────────────────────────────────────────
    caller_role: str  # "actions" | "operator" | "admin" — from validated token
    agent_trust_ceiling: str  # "t0" | "t1" | "t2" | "t3" — agents NEVER get admin (t2)

    # ── PROVIDER (WHAT LLM) ───────────────────────────────────────────────
    provider_id: str  # e.g., "claude-account", "ollama"
    model_id: str  # e.g., "claude-haiku-4-5-20251001", "qwen2.5-coder:3b"

    # ── WORKSPACE (WHERE) ─────────────────────────────────────────────────
    workspace_root: Path  # Absolute path, verified to exist

    # ── SCHEMA CONSTRAINTS (HOW) ──────────────────────────────────────────
    valid_roles: tuple[str, ...]  # Extracted from AgentRole Literal — single source of truth
    valid_scopes: tuple[str, ...]  # Valid scope values for tasks

    # ── CONTEXT (WHEN/WHY) ────────────────────────────────────────────────
    created_at: datetime
    license_plan: str  # "free" | "pro" | "enterprise" | "unknown"

    def is_admin(self) -> bool:
        """Check if caller has admin privileges."""
        return self.caller_role == "admin"

    def is_operator_or_above(self) -> bool:
        """Check if caller has operator or admin privileges."""
        return self.caller_role in {"operator", "admin"}

    def is_actions_only(self) -> bool:
        """Check if caller is restricted to read-only actions."""
        return self.caller_role == "actions"

    def format_roles_for_prompt(self) -> str:
        """Format valid roles for inclusion in system prompts.

        Returns: ' | '.join(['"orchestrator"', '"worker"', '"external_action"'])
        """
        return " | ".join(f'"{role}"' for role in self.valid_roles)

    def validate_role(self, role: str) -> bool:
        """Check if a role value is valid according to schema."""
        return role in self.valid_roles

    def validate_scope(self, scope: str) -> bool:
        """Check if a scope value is valid."""
        return scope in self.valid_scopes


def extract_valid_roles() -> tuple[str, ...]:
    """Extract valid role values from AgentRole Literal type.

    This is the SINGLE SOURCE OF TRUTH for valid roles.
    Never hardcode roles in prompts or validation logic.
    """
    return get_args(AgentRole)


# Default valid scopes (can be extended in future)
DEFAULT_VALID_SCOPES = ("bridge", "file_write", "file_read", "shell")
