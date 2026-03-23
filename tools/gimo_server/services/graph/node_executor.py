"""Node execution dispatch for GraphEngine."""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from tools.gimo_server.services.tool_registry_service import ToolRegistryService
from tools.gimo_server.services.role_profiles import assert_tool_allowed, get_role_profile
from tools.gimo_server.services.hitl_gate_service import HitlGateService

if TYPE_CHECKING:
    from tools.gimo_server.ops_models import WorkflowGraph, WorkflowNode

logger = logging.getLogger("orchestrator.services.graph_engine")


class NodeExecutorMixin:
    """Node type dispatch and execution: llm_call, tool_call, transform, sub_graph, eval."""

    async def _execute_node(self, node, state: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a single node based on its type."""
        if node.type == "llm_call":
            return await self._execute_llm_call(node)

        if node.type == "tool_call":
            return await self._execute_tool_call(node)

        if node.type == "transform":
            return self._execute_transform(node)

        if node.type == "sub_graph":
            return await self._execute_sub_graph(node)

        if node.type == "eval":
            return self._execute_eval(node)

        return {"status": "ok", "msg": "noop"}

    async def _execute_llm_call(self, node) -> Dict[str, Any]:
        prompt, context = self._prepare_llm_payload(node)

        resp = await self._provider_service.generate(prompt, context)

        # Quality Analysis (Phase 5 requirement: ROI needs quality)
        from tools.gimo_server.services.quality_service import QualityService
        text_output = str(resp.get("content") or resp.get("result") or "")
        quality = QualityService.analyze_output(
            text_output,
            task_type=context.get("task_type"),
            expected_format=context.get("expected_format")
        )

        return {
            "role": "assistant",
            "content": resp.get("content") or resp.get("result") or "",
            "provider": resp.get("provider", "unknown"),
            "model_used": resp.get("model") or resp.get("model_used", "unknown"),
            "tokens_used": resp.get("tokens_used", 0),
            "cost_usd": resp.get("cost_usd", 0.0),
            "quality_rating": quality.model_dump()
        }

    def _prepare_llm_payload(self, node) -> tuple[str, Dict[str, Any]]:
        """Renders prompt and prepares context for LLM call."""
        prompt_template = str(node.config.get("prompt", ""))

        try:
            if "{" in prompt_template and "}" in prompt_template:
               prompt = prompt_template.format(**self.state.data)
            else:
               prompt = prompt_template
        except Exception as e:
            logger.warning(f"Prompt formatting failed for node {node.id}: {e}")
            prompt = prompt_template

        context = {
            "system": node.config.get("system_prompt"),
            "system_prompt": node.config.get("system_prompt"),
            "model": node.config.get("selected_model") or node.config.get("model"),
            "temperature": node.config.get("temperature", 0.7),
            "task_type": node.config.get("task_type"),
            "node_id": node.id,
            "expected_format": "json" if node.type == "classification" else None
        }
        return prompt, context

    async def _execute_tool_call(self, node) -> Dict[str, Any]:
        tool_name = str(node.config.get("tool_name", "")).strip()
        args = node.config.get("arguments") or {}

        if not tool_name:
             raise ValueError(f"Node {node.id} missing tool_name")

        await self._enforce_tool_governance(node=node, tool_name=tool_name, args=args)

        # Lookup tool in registry
        tool_entry = ToolRegistryService.get_tool(tool_name)
        if not tool_entry:
            raise ValueError(f"Tool {tool_name} not found in registry")

        # Check if MCP tool
        mcp_server = tool_entry.metadata.get("mcp_server")
        if mcp_server:
            from tools.gimo_server.services.provider_service import ProviderService
            from tools.gimo_server.adapters.mcp_client import McpClient
            ops_config = ProviderService.get_config()
            if not ops_config or mcp_server not in ops_config.mcp_servers:
                raise RuntimeError(f"MCP server {mcp_server} not found or disabled")

            server_config = ops_config.mcp_servers[mcp_server]
            real_tool_name = tool_entry.metadata.get("mcp_tool", tool_name)

            async with McpClient(mcp_server, server_config) as client:
                result = await client.call_tool(real_tool_name, args)

            return {
                "tool": tool_name,
                "input": args,
                "output": result,
                "mcp_server": mcp_server
            }

        # Local tool execution
        if tool_entry.metadata.get("type") == "native":
            return self._execute_native_tool(tool_name, args)

        raise NotImplementedError(f"Local tool execution for {tool_name} not implemented yet")

    async def _enforce_tool_governance(self, *, node, tool_name: str, args: Dict[str, Any]) -> None:
        role_profile = str(node.config.get("role_profile") or node.config.get("role") or "").strip()
        if not role_profile:
            return

        assert_tool_allowed(role_profile, tool_name)

        profile = get_role_profile(role_profile)
        if profile.hitl_required:
            decision = await HitlGateService.gate_tool_call(
                agent_id=str(node.agent or node.id),
                tool=tool_name,
                params=dict(args or {}),
            )
            if decision != "allow":
                raise PermissionError(f"HITL denied tool call: {tool_name}")

    def _execute_native_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "core_write_file":
            path = args.get("path")
            content = args.get("content")
            if path and content:
                try:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text(content, encoding="utf-8")
                    return {"status": "success", "written": len(content)}
                except Exception as e:
                    return {"status": "error", "error": str(e)}

        if tool_name == "core_read_file":
            path = args.get("path")
            if path:
                try:
                    if Path(path).exists():
                        return {"content": Path(path).read_text(encoding="utf-8")}
                    return {"error": "file_not_found"}
                except Exception as e:
                    return {"error": str(e)}

        return {"error": f"Native tool {tool_name} not found"}

    def _execute_transform(self, node) -> Dict[str, Any]:
        operation = node.config.get("operation")
        if operation == "json_extract":
            source_key = node.config.get("source_key")
            target_key = node.config.get("target_key")
            if source_key and target_key:
                source_val = self.state.data.get(source_key)
                if isinstance(source_val, str):
                    try:
                        if "```json" in source_val:
                            start = source_val.find("```json") + 7
                            end = source_val.find("```", start)
                            if end > start:
                                source_val = source_val[start:end].strip()
                        parsed = json.loads(source_val)
                        return {target_key: parsed}
                    except Exception as e:
                        return {"error": f"json_extract_failed: {e}"}

        elif operation == "format_string":
            template = node.config.get("template", "")
            target_key = node.config.get("target_key")
            if template and target_key:
                try:
                    formatted = template.format(**self.state.data)
                    return {target_key: formatted}
                except Exception as e:
                    return {"error": f"format_string_failed: {e}"}

        return {"status": "ok", "msg": "transform_noop"}

    async def _execute_sub_graph(self, node) -> Dict[str, Any]:
        from tools.gimo_server.ops_models import WorkflowGraph

        sub_graph_def = node.config.get("graph")
        if not sub_graph_def:
            raise ValueError("sub_graph node missing 'graph' definition")

        if isinstance(sub_graph_def, dict):
            if "id" not in sub_graph_def:
                sub_graph_def["id"] = f"{self.graph.id}_sub_{node.id}"
            sub_graph = WorkflowGraph.model_validate(sub_graph_def)
        else:
            sub_graph = sub_graph_def

        input_mapping = node.config.get("input_mapping")
        initial_state = {}
        if input_mapping:
             for pk, ck in input_mapping.items():
                 if pk in self.state.data:
                     initial_state[ck] = self.state.data[pk]
        else:
            initial_state = copy.deepcopy(self.state.data)

        initial_state.pop("budget_counters", None)
        initial_state.pop("step_logs", None)
        initial_state.pop("trace_id", None)

        # Import at call time to avoid circular import
        from .engine import GraphEngine as _GraphEngine
        sub_engine = _GraphEngine(
            graph=sub_graph,
            max_iterations=self.max_iterations,
            storage=self.storage,
            persist_checkpoints=self.persist_checkpoints,
            confidence_service=getattr(self, "_confidence_service", None),
            provider_service=getattr(self, "_provider_service", None),
        )

        sub_result = await sub_engine.execute(initial_state=initial_state)

        output_mapping = node.config.get("output_mapping")
        result_data = {}
        if output_mapping:
            for ck, pk in output_mapping.items():
                if ck in sub_result.data:
                    result_data[pk] = sub_result.data[ck]

        sub_counters = sub_result.data.get("budget_counters", {})
        tokens_used = int(sub_counters.get("tokens", 0))
        cost_usd = float(sub_counters.get("cost_usd", 0.0))

        return {
            "sub_graph_id": sub_graph.id,
            "status": "completed",
            "output": result_data,
            "tokens_used": tokens_used,
            "cost_usd": cost_usd
        }

    def _execute_eval(self, node) -> Dict[str, Any]:
        from tools.gimo_server.services.evals_service import EvalsService
        from tools.gimo_server.ops_models import EvalJudgeConfig, EvalGoldenCase

        expected = node.config.get("expected_state")
        case_id = node.config.get("case_id", f"eval_{node.id}")

        adhoc_case = EvalGoldenCase(
             case_id=case_id,
             input_state={},
             expected_state=expected or {},
             threshold=node.config.get("threshold", 1.0)
        )
        judge_config = EvalJudgeConfig(enabled=False)

        score, reason = EvalsService._score_case(
            expected_state=adhoc_case.expected_state,
            actual_state=self.state.data,
            judge=judge_config
        )

        passed = score >= adhoc_case.threshold
        return {
            "eval_passed": passed,
            "score": score,
            "reason": reason
        }
