import logging
from mcp.server.fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent

logger = logging.getLogger("mcp_bridge.prompts")

def register_prompts(mcp: FastMCP):
    @mcp.prompt("plan_creation")
    def prompt_plan_creation(goal: str) -> list[PromptMessage]:
        """A guided workflow to create a modular multi-agent plan."""
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"Please create a comprehensive multi-agent plan to achieve the following goal: {goal}.\n"
                         "1. Use 'post_ops_drafts' tool to propose the plan.\n"
                         "2. The plan must include a Mermaid graph.\n"
                         "3. Wait for my approval before executing."
                )
            )
        ]

    @mcp.prompt("debug_run")
    def prompt_debug_run(run_id: str) -> list[PromptMessage]:
        """Analyze a failed or stuck GIMO Run."""
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"The run with ID {run_id} seems to have failed or hanging. Please:\n"
                         f"1. Check the run status using 'get_ops_runs_run_id'.\n"
                         f"2. Look for error messages in the run logs.\n"
                         f"3. Propose a fix or use 'put_ops_runs_run_id_status' to manually override it."
                )
            )
        ]

    @mcp.prompt("optimize_cost")
    def prompt_optimize_cost() -> list[PromptMessage]:
        """Review recent metrics and suggest cost optimizations."""
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text="Review the 'metrics://cascade' and 'metrics://cache' resources.\n"
                         "Based on the data, suggest configuration changes to `provider_service.py` or new cache strategies to reduce LLM API costs."
                )
            )
        ]

    @mcp.prompt("security_audit")
    def prompt_security_audit() -> list[PromptMessage]:
        """Review security trust levels and find anomalous agents."""
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text="Examine the 'security://trust' resource.\n"
                         "Identify any agents that have low trust scores or triggered the circuit breaker. Provide a short incident report."
                )
            )
        ]

    @mcp.prompt("onboard_agent")
    def prompt_onboard_agent(task_description: str) -> list[PromptMessage]:
        """Draft a valid system prompt for a new specialized sub-agent."""
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"I want to create a new specialized GIMO sub-agent to handle this task: '{task_description}'.\n"
                         "Please draft its system prompt following the GIMO persona format (Modular, Disruptive) and suggest the best model preference."
                )
            )
        ]

    # ── SAGP Governance Prompts ────────────────────────────────────────
    @mcp.prompt("governance_check")
    def prompt_governance_check(tool_name: str, policy: str = "workspace_safe") -> list[PromptMessage]:
        """Pre-action governance evaluation workflow."""
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        f"Before executing '{tool_name}', perform a governance check:\n"
                        f"1. Call gimo_evaluate_action(tool_name='{tool_name}', policy='{policy}') to get the verdict.\n"
                        f"2. If 'requires_approval' is true, ask me before proceeding.\n"
                        f"3. If 'allowed' is false, explain why and suggest alternatives.\n"
                        f"4. Show the cost estimate and risk band."
                    ),
                ),
            )
        ]

    @mcp.prompt("multi_agent_plan")
    def prompt_multi_agent_plan(goal: str) -> list[PromptMessage]:
        """Plan creation with provider selection per worker."""
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        f"Create a multi-agent plan for: {goal}\n\n"
                        "For each worker agent:\n"
                        "1. Select the best provider/model using gimo_estimate_cost to compare options.\n"
                        "2. Assign an execution_policy appropriate for the task risk level.\n"
                        "3. Use gimo_spawn_subagent with explicit provider, model, and policy.\n"
                        "4. Check governance with gimo_evaluate_action before each high-risk step.\n"
                        "5. Show the total estimated cost breakdown."
                    ),
                ),
            )
        ]

    logger.info("Registered 7 MCP Prompts")
