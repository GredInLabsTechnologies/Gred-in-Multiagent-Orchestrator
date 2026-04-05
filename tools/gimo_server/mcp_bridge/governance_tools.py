"""SAGP Governance MCP tools.

Eight governance-specific tools that expose GIMO's governance authority
to any MCP client (Claude App, VS Code, Cursor, etc.).
"""
import json
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("mcp_bridge.governance_tools")


def register_governance_tools(mcp: FastMCP):

    @mcp.tool()
    async def gimo_evaluate_action(
        tool_name: str,
        tool_args_json: str = "{}",
        thread_id: str = "",
        policy: str = "workspace_safe",
    ) -> str:
        """Evaluate whether an action is allowed under GIMO governance.

        Call this BEFORE executing any tool to get a governance verdict
        with policy, risk band, trust score, cost estimate, and HITL requirements.

        Args:
            tool_name: Name of the tool to evaluate (e.g. "write_file", "shell_exec")
            tool_args_json: JSON string of tool arguments
            thread_id: Optional thread ID for proof chain tracking
            policy: Execution policy name (read_only, docs_research, propose_only, workspace_safe, workspace_experiment, security_audit)
        """
        try:
            from tools.gimo_server.models.surface import SurfaceIdentity
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            tool_args = json.loads(tool_args_json) if tool_args_json else {}
            surface = SurfaceIdentity(
                surface_type="mcp_generic",
                surface_name="mcp-governance-tool",
            )
            verdict = SagpGateway.evaluate_action(
                surface=surface,
                tool_name=tool_name,
                tool_args=tool_args,
                thread_id=thread_id,
                policy_name=policy,
            )
            return json.dumps(verdict.to_dict(), indent=2)
        except json.JSONDecodeError as e:
            return json.dumps({"error": "INVALID_TOOL_ARGS", "detail": str(e)})
        except Exception as e:
            logger.error("gimo_evaluate_action failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def gimo_estimate_cost(
        model: str,
        input_tokens: int = 1000,
        output_tokens: int = 500,
    ) -> str:
        """Estimate the cost of an LLM call.

        Args:
            model: Model name (e.g. "claude-sonnet-4-6", "gpt-4o", "deepseek-v3")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
        """
        try:
            from tools.gimo_server.services.economy.cost_service import CostService

            pricing = CostService.get_pricing(model)
            total = CostService.calculate_cost(model, input_tokens, output_tokens)
            provider = CostService.get_provider(model)
            return json.dumps({
                "model": model,
                "provider": provider,
                "input_price_per_1m": pricing["input"],
                "output_price_per_1m": pricing["output"],
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_cost_usd": total,
            }, indent=2)
        except Exception as e:
            logger.error("gimo_estimate_cost failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def gimo_get_trust_profile(dimension_key: str = "") -> str:
        """Get trust scores and circuit breaker state.

        Args:
            dimension_key: Optional dimension to query (e.g. "provider:anthropic", "model:gpt-4o"). Empty returns all dimensions.
        """
        try:
            from tools.gimo_server.services.trust_engine import TrustEngine
            from tools.gimo_server.services.storage.trust_storage import TrustStorage
            from tools.gimo_server.services.storage_service import StorageService

            storage = TrustStorage(gics_service=StorageService._shared_gics)
            engine = TrustEngine(trust_store=storage)

            if dimension_key:
                record = engine.query_dimension(dimension_key)
                return json.dumps(record, indent=2, default=str)
            else:
                dashboard = engine.dashboard(limit=20)
                return json.dumps(dashboard, indent=2, default=str)
        except Exception as e:
            logger.error("gimo_get_trust_profile failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def gimo_get_governance_snapshot(thread_id: str = "") -> str:
        """Get a complete governance snapshot: policy, trust, budget, GICS health, proof chain.

        Args:
            thread_id: Optional thread ID for thread-specific state
        """
        try:
            from tools.gimo_server.models.surface import SurfaceIdentity
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            surface = SurfaceIdentity(
                surface_type="mcp_generic",
                surface_name="mcp-governance-tool",
            )
            snapshot = SagpGateway.get_snapshot(
                surface=surface,
                thread_id=thread_id,
            )
            return json.dumps(snapshot.to_dict(), indent=2)
        except Exception as e:
            logger.error("gimo_get_governance_snapshot failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def gimo_get_gics_insight(prefix: str = "", limit: int = 20) -> str:
        """Get GICS (Governance Intelligence & Control System) telemetry entries.

        Args:
            prefix: Key prefix filter (e.g. "model:", "provider:", "anomaly:")
            limit: Maximum entries to return
        """
        try:
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            result = SagpGateway.get_gics_insight(prefix=prefix, limit=limit)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            logger.error("gimo_get_gics_insight failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def gimo_verify_proof_chain(thread_id: str) -> str:
        """Verify the integrity of the execution proof chain for a thread.

        Args:
            thread_id: Thread ID whose proof chain to verify
        """
        try:
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            result = SagpGateway.verify_proof_chain(thread_id=thread_id)
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("gimo_verify_proof_chain failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def gimo_get_execution_policy(policy_name: str = "workspace_safe") -> str:
        """Get details of an execution policy profile.

        Args:
            policy_name: Policy name (read_only, docs_research, propose_only, workspace_safe, workspace_experiment, security_audit)
        """
        try:
            from tools.gimo_server.services.execution.execution_policy_service import EXECUTION_POLICIES

            policy = EXECUTION_POLICIES.get(policy_name)
            if not policy:
                available = list(EXECUTION_POLICIES.keys())
                return json.dumps({"error": f"Unknown policy: {policy_name}", "available": available})

            return json.dumps({
                "name": policy.name,
                "fs_mode": policy.fs_mode,
                "network_mode": policy.network_mode,
                "allowed_domains": sorted(policy.allowed_domains),
                "allowed_tools": sorted(policy.allowed_tools),
                "requires_confirmation": sorted(policy.requires_confirmation),
                "max_cost_per_turn_usd": policy.max_cost_per_turn_usd,
                "auto_test_on_write": policy.auto_test_on_write,
                "auto_lint_on_write": policy.auto_lint_on_write,
                "hitl_required": policy.hitl_required,
            }, indent=2)
        except Exception as e:
            logger.error("gimo_get_execution_policy failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def gimo_get_budget_status(scope: str = "global") -> str:
        """Get current budget status and forecast.

        Args:
            scope: Budget scope (global, session, or thread ID)
        """
        try:
            from tools.gimo_server.services.economy.cost_service import CostService

            CostService.load_pricing()
            return json.dumps({
                "status": "active",
                "pricing_loaded": CostService._PRICING_LOADED,
                "scope": scope,
            }, indent=2, default=str)
        except Exception as e:
            logger.error("gimo_get_budget_status failed: %s", e)
            return json.dumps({"error": str(e)})
