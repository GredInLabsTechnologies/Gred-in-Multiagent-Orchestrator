"""Agent Teams Service: Generates Claude Code Agent Teams configurations.

Converts GIMO plans into Agent Teams teammate configs, each with
GIMO MCP server loaded, specific execution_policy, and task description.

Requires: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.agent_teams")


class AgentTeamsService:
    """Generate Claude Code Agent Teams configs from GIMO plans."""

    @classmethod
    def generate_team_config(
        cls,
        plan_content: Dict[str, Any],
        mcp_server_command: str = "python -m tools.gimo_server.mcp_bridge.server",
    ) -> Dict[str, Any]:
        """Convert a GIMO plan into Agent Teams teammate definitions.

        Args:
            plan_content: Parsed plan content with tasks/nodes
            mcp_server_command: Command to start GIMO MCP server

        Returns:
            Config dict for Agent Teams with teammates array
        """
        tasks = cls._extract_tasks(plan_content)
        teammates = []

        for i, task in enumerate(tasks):
            policy = cls._infer_policy(task)
            teammate = {
                "name": task.get("name", f"worker-{i}"),
                "description": task.get("description", task.get("task", "Worker agent")),
                "mcpServers": {
                    "gimo": {
                        "command": mcp_server_command,
                    }
                },
                "systemPrompt": cls.generate_teammate_prompt(task, policy),
            }
            teammates.append(teammate)

        return {
            "env": {
                "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
            },
            "teammates": teammates,
            "governance": {
                "mcp_server": mcp_server_command,
                "note": "Each teammate has GIMO governance via MCP. "
                        "Use gimo_evaluate_action before high-risk operations.",
            },
        }

    @classmethod
    def generate_teammate_prompt(
        cls,
        task: Dict[str, Any],
        policy: str = "workspace_safe",
    ) -> str:
        """Generate a system prompt for a teammate with governance constraints."""
        task_desc = task.get("task", task.get("description", "Complete the assigned task"))
        role = task.get("role", "worker")

        return (
            f"You are a GIMO-governed {role} agent.\n\n"
            f"## Task\n{task_desc}\n\n"
            f"## Governance Rules\n"
            f"- Execution policy: `{policy}`\n"
            f"- Before ANY file write or shell command, call `gimo_evaluate_action` "
            f"with tool_name and policy='{policy}'.\n"
            f"- If the verdict says `requires_approval: true`, ask the orchestrator "
            f"before proceeding.\n"
            f"- If `allowed: false`, do NOT proceed — report the denial reason.\n"
            f"- Track costs via `gimo_estimate_cost` for expensive operations.\n"
            f"- Use `gimo_get_governance_snapshot` to check overall state.\n\n"
            f"## Communication\n"
            f"- Report progress via task updates.\n"
            f"- Escalate blockers to the orchestrator immediately.\n"
        )

    @classmethod
    def _extract_tasks(cls, plan_content: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract task list from various plan formats."""
        # Support multiple plan formats
        if "tasks" in plan_content:
            return plan_content["tasks"]
        if "nodes" in plan_content:
            return plan_content["nodes"]
        if "steps" in plan_content:
            return plan_content["steps"]
        # Single task fallback
        if "task" in plan_content:
            return [plan_content]
        return []

    @classmethod
    def _infer_policy(cls, task: Dict[str, Any]) -> str:
        """Infer execution policy from task metadata."""
        # Explicit policy
        if "execution_policy" in task:
            return task["execution_policy"]
        if "policy" in task:
            return task["policy"]

        # Infer from role/type
        role = str(task.get("role", "")).lower()
        task_type = str(task.get("type", "")).lower()

        if role in ("reviewer", "auditor") or task_type in ("review", "audit"):
            return "read_only"
        if role == "researcher" or task_type == "research":
            return "docs_research"
        if role == "planner" or task_type in ("plan", "propose"):
            return "propose_only"
        if task_type in ("security", "security_audit"):
            return "security_audit"
        if task_type in ("experiment", "prototype"):
            return "workspace_experiment"

        return "workspace_safe"
