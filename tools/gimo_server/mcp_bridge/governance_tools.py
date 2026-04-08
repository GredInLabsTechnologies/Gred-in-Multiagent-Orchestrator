"""SAGP Governance MCP tools.

Eight governance-specific tools that expose GIMO's governance authority
to any MCP client (Claude App, VS Code, Cursor, etc.).
"""
import json
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("mcp_bridge.governance_tools")


def _mcp_surface(name: str = "mcp-governance-tool"):
    """Shared MCP surface identity for consistent governance tracking."""
    from tools.gimo_server.models.surface import SurfaceIdentity
    return SurfaceIdentity(surface_type="mcp", surface_name=name)


def register_governance_tools(mcp: FastMCP):
    # R18 Change 1 — declare Pydantic-bound tools for the boot-time drift guard.
    # These tools already expose canonical signatures matching their *Input models
    # (R17 Cluster D); bind() records the expected model so assert_no_drift()
    # can verify the live FastMCP schema at the end of the registration path.
    from .native_inputs import EstimateCostInput, VerifyProofChainInput
    from . import _register as _drift

    _drift.bind("gimo_estimate_cost", EstimateCostInput)
    _drift.bind("gimo_verify_proof_chain", VerifyProofChainInput)

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
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            tool_args = json.loads(tool_args_json) if tool_args_json else {}
            surface = _mcp_surface()
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
        tokens_in: int = 1000,
        tokens_out: int = 500,
    ) -> str:
        """Estimate the cost of an LLM call.

        Canonical params (the published MCP schema is the single source of
        truth — derived from EstimateCostInput): ``model``, ``tokens_in``,
        ``tokens_out``. The legacy ``input_tokens`` / ``output_tokens``
        aliases were removed in R17.1 after the one-round deprecation.

        Args:
            model: Model name (e.g. "claude-sonnet-4-6", "gpt-4o", "deepseek-v3")
            tokens_in: Number of input tokens
            tokens_out: Number of output tokens
        """
        try:
            from tools.gimo_server.services.economy.cost_service import CostService
            from .native_inputs import EstimateCostInput

            params = EstimateCostInput(
                model=model, tokens_in=tokens_in, tokens_out=tokens_out
            )

            pricing = CostService.get_pricing(params.model)
            total = CostService.calculate_cost(
                params.model, params.tokens_in, params.tokens_out
            )
            provider = CostService.get_provider(params.model)
            return json.dumps({
                "model": params.model,
                "provider": provider,
                "input_price_per_1m": pricing["input"],
                "output_price_per_1m": pricing["output"],
                "tokens_in": params.tokens_in,
                "tokens_out": params.tokens_out,
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
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            if dimension_key:
                score = SagpGateway._get_trust_score(dimension_key)
                return json.dumps({"dimension_key": dimension_key, "effective_score": score}, indent=2)
            else:
                dimensions = ["provider", "model", "tool"]
                result = {d: SagpGateway._get_trust_score(d) for d in dimensions}
                return json.dumps(result, indent=2)
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
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            surface = _mcp_surface()
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
    async def gimo_verify_proof_chain(thread_id: str | None = None) -> str:
        """Verify the integrity of the execution proof chain for a thread.

        If ``thread_id`` is omitted, falls back to the most recently updated
        thread (the "most recent verified chain").

        Args:
            thread_id: Optional thread ID whose proof chain to verify.
        """
        try:
            from tools.gimo_server.services.sagp_gateway import SagpGateway
            from .native_inputs import VerifyProofChainInput

            params = VerifyProofChainInput(thread_id=thread_id)
            resolved_id = params.thread_id

            if not resolved_id:
                # Fallback: most recently updated thread.
                from tools.gimo_server.services.conversation_service import (
                    ConversationService,
                )
                threads = ConversationService.list_threads()
                if not threads:
                    return json.dumps({
                        "error": "No threads found; cannot verify any proof chain.",
                    })
                resolved_id = threads[0].id

            result = SagpGateway.verify_proof_chain(thread_id=resolved_id)
            if isinstance(result, dict):
                result.setdefault("resolved_thread_id", resolved_id)
                result.setdefault("thread_id_was_inferred", thread_id is None)
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
            from tools.gimo_server.services.storage_service import StorageService

            CostService.load_pricing()
            storage = StorageService()
            total_spend = storage.cost.get_total_spend(days=30)
            spend_rate = storage.cost.get_spend_rate(hours=24)
            by_model = storage.cost.aggregate_by_model(days=30) or []

            return json.dumps({
                "status": "active",
                "pricing_loaded": CostService._PRICING_LOADED,
                "scope": scope,
                "spend_30d_usd": round(total_spend, 4),
                "burn_rate_hourly_usd": round(spend_rate, 6),
                "top_models": by_model[:5],
            }, indent=2, default=str)
        except Exception as e:
            logger.error("gimo_get_budget_status failed: %s", e)
            return json.dumps({"error": str(e)})
