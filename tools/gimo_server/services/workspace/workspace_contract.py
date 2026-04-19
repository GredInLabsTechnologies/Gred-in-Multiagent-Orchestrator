"""WorkspaceContract — Invariant gate for GIMO workspace operations.

A WorkspaceContract represents a verified, initialized GIMO workspace.
No mutating tool can operate on a workspace without a valid contract.

Structure created/verified:
    .gimo/
    ├── config.yaml          # user preferences (preserved if exists)
    ├── governance.yaml      # declarative agent governance rules
    ├── plans/
    ├── history/
    ├── runs/
    ├── telemetry/
    │   └── sessions/
    ├── audit.jsonl           # append-only action log
    └── .gitignore
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("orchestrator.workspace_contract")

_GIMO_DIR = ".gimo"
_REQUIRED_SUBDIRS = ("plans", "history", "runs")
_OPTIONAL_SUBDIRS = ("telemetry", "telemetry/sessions")
_GITIGNORE_CONTENT = """\
# GIMO workspace — auto-generated, do not edit
telemetry/
audit.jsonl
runs/
"""

_DEFAULT_GOVERNANCE = """\
# GIMO Governance Rules
# Declarative rules that GIMO enforces server-side for agents working in this workspace.
# See https://gimo.dev/docs/governance for full reference.

rules:
  # Master switch for telemetry (off by default)
  telemetry:
    profile: "off"  # off | minimal | standard | full

  # Protected paths — agents cannot modify these
  # protected_paths: []

  # Style guidance — injected into agent prompts as soft constraints
  # style: "follow existing patterns"

  # Language preference for agent responses
  # language: "en"
"""


@dataclass(frozen=True)
class GovernanceRules:
    """Parsed governance rules from .gimo/governance.yaml."""
    telemetry_profile: str = "off"
    protected_paths: List[str] = field(default_factory=list)
    style: str = ""
    language: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def telemetry_enabled(self) -> bool:
        return self.telemetry_profile != "off"

    @property
    def audit_trail_enabled(self) -> bool:
        return self.telemetry_profile in ("minimal", "standard", "full")

    @property
    def session_logs_enabled(self) -> bool:
        return self.telemetry_profile in ("standard", "full")

    @property
    def insights_enabled(self) -> bool:
        return self.telemetry_profile == "full"

    def prompt_constraints(self) -> str:
        """Build prompt fragment from governance rules for injection into system prompts."""
        lines: List[str] = []
        if self.style:
            lines.append(f"User style directive: {self.style}")
        if self.language:
            lines.append(f"Respond in: {self.language}")
        if self.protected_paths:
            paths_str = ", ".join(self.protected_paths)
            lines.append(
                f"[GIMO-ENFORCED] Protected paths (do NOT modify): {paths_str}"
            )
        if not lines:
            return ""
        header = "=== WORKSPACE GOVERNANCE (from .gimo/governance.yaml) ==="
        footer = "=== END GOVERNANCE ==="
        return f"{header}\n" + "\n".join(lines) + f"\n{footer}"


@dataclass(frozen=True)
class WorkspaceContract:
    """Proof that a workspace has been verified and is ready for GIMO operations."""
    workspace_root: Path
    gimo_dir: Path
    governance: GovernanceRules

    @classmethod
    def verify(cls, workspace_root: str | Path) -> "WorkspaceContract":
        """Verify an existing .gimo/ workspace. Raises if not initialized."""
        root = Path(workspace_root).resolve()
        gimo = root / _GIMO_DIR
        if not gimo.is_dir():
            raise WorkspaceNotInitializedError(root)
        governance = _load_governance(gimo)
        return cls(workspace_root=root, gimo_dir=gimo, governance=governance)

    @classmethod
    def ensure(cls, workspace_root: str | Path) -> "WorkspaceContract":
        """Initialize .gimo/ if missing, then verify. Idempotent."""
        root = Path(workspace_root).resolve()
        gimo = root / _GIMO_DIR
        _ensure_structure(gimo)
        governance = _load_governance(gimo)
        logger.info("Workspace contract ensured: %s", root)
        return cls(workspace_root=root, gimo_dir=gimo, governance=governance)

    @classmethod
    def is_initialized(cls, workspace_root: str | Path) -> bool:
        """Quick check without loading governance."""
        return (Path(workspace_root).resolve() / _GIMO_DIR).is_dir()

    def audit_log_path(self) -> Path:
        return self.gimo_dir / "audit.jsonl"

    def session_log_dir(self) -> Path:
        return self.gimo_dir / "telemetry" / "sessions"

    def append_audit(self, entry: Dict[str, Any]) -> None:
        """Append a single audit entry if audit trail is enabled."""
        if not self.governance.audit_trail_enabled:
            return
        entry.setdefault("ts", _iso_now())
        try:
            with open(self.audit_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Failed to write audit entry: %s", exc)

    def is_path_protected(self, rel_path: str) -> bool:
        """Check if a relative path is protected by governance rules."""
        import fnmatch
        for pattern in self.governance.protected_paths:
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path, f"**/{pattern}"):
                return True
        return False


class WorkspaceNotInitializedError(RuntimeError):
    """Raised when a workspace lacks .gimo/ and auto-init is not requested."""
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        super().__init__(
            f"Workspace not initialized: {workspace_root}. "
            f"Run 'gimo init' or let GIMO bootstrap automatically."
        )


def _ensure_structure(gimo: Path) -> None:
    """Create .gimo/ structure idempotently."""
    for subdir in _REQUIRED_SUBDIRS:
        (gimo / subdir).mkdir(parents=True, exist_ok=True)
    for subdir in _OPTIONAL_SUBDIRS:
        (gimo / subdir).mkdir(parents=True, exist_ok=True)

    gitignore = gimo / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE_CONTENT, encoding="utf-8")

    governance_file = gimo / "governance.yaml"
    if not governance_file.exists():
        governance_file.write_text(_DEFAULT_GOVERNANCE, encoding="utf-8")


def _load_governance(gimo: Path) -> GovernanceRules:
    """Load and parse governance.yaml, returning defaults if missing or invalid."""
    governance_file = gimo / "governance.yaml"
    if not governance_file.exists():
        return GovernanceRules()
    try:
        import yaml
        raw = yaml.safe_load(governance_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return GovernanceRules()
        rules = raw.get("rules") or {}
        if not isinstance(rules, dict):
            return GovernanceRules(raw=raw)

        telemetry = rules.get("telemetry") or {}
        profile = str(telemetry.get("profile", "off")).strip().lower() if isinstance(telemetry, dict) else "off"
        if profile not in ("off", "minimal", "standard", "full"):
            profile = "off"

        protected = rules.get("protected_paths") or []
        if not isinstance(protected, list):
            protected = [str(protected)]

        return GovernanceRules(
            telemetry_profile=profile,
            protected_paths=[str(p) for p in protected],
            style=str(rules.get("style") or "").strip(),
            language=str(rules.get("language") or "").strip(),
            raw=raw,
        )
    except ImportError:
        logger.warning("PyYAML not installed, governance.yaml ignored")
        return GovernanceRules()
    except Exception as exc:
        logger.warning("Failed to parse governance.yaml: %s", exc)
        return GovernanceRules()


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
