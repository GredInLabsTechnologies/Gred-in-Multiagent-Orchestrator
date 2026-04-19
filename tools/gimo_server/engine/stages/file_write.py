from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict
from ..contracts import FileTaskSpec, StageInput, StageOutput, ExecutionStage
from ..tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

class FileWrite(ExecutionStage):
    @property
    def name(self) -> str:
        return "file_write"

    @staticmethod
    def _resolve_execution_policy(context: Dict[str, Any]) -> str:
        explicit_policy = context.get("execution_policy")
        if isinstance(explicit_policy, str) and explicit_policy.strip():
            return explicit_policy.strip()

        gen_context = context.get("gen_context")
        if isinstance(gen_context, dict):
            nested_policy = gen_context.get("execution_policy")
            if isinstance(nested_policy, str) and nested_policy.strip():
                return nested_policy.strip()

        return "workspace_safe"

    @staticmethod
    def _assert_within_workspace(path: str, workspace_root: str) -> None:
        """Raise ValueError if path resolves outside workspace_root."""
        ws = Path(workspace_root).resolve()
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = ws / candidate
        candidate = candidate.resolve()
        candidate.relative_to(ws)  # raises ValueError if outside workspace

    @staticmethod
    def _extract_fallback_path(content: str, context: Dict[str, Any]) -> str | None:
        for k in ("target_path", "target_file", "file_path"):
            val = context.get(k)
            if isinstance(val, str) and val.strip():
                return val.strip()

        regexes = [
            r"TARGET_FILE:\s*(.+?)(?:\s*\n|$)",
            r"([A-Za-z]:[/\\][^\s\"']+\.\w{1,8})",
            r"(\S+/[^\s\"']+\.\w{1,8})",
            r"['\"]([^\s\"']+\.\w{1,8})['\"]",
        ]
        for pattern in regexes:
            m = re.search(pattern, content)
            if m:
                return m.group(1).strip("'\", ")
        return None

    async def execute(self, input: StageInput) -> StageOutput:
        # 1. Get tool calls from LLM response (previous stage artifact)
        llm_resp = input.artifacts.get("llm_response", {})
        llm_content = str(input.artifacts.get("content") or "")
        if isinstance(llm_resp, dict):
            llm_content = str(input.artifacts.get("content") or llm_resp.get("content") or "")
        
        # Search for tool calls in various formats (direct or artifacts)
        tool_calls = []
        if isinstance(llm_resp, dict):
            tool_calls = llm_resp.get("tool_calls", [])
        
        # 2. Setup executor with policy (Per-run allowed_paths takes precedence)
        policy = input.context.get("gen_context", {}).get("policy") or {}
        if not policy:
            # Fallback to field registry merge or direct context
            allowed = input.context.get("allowed_paths")
            if allowed:
                policy = {"allowed_paths": allowed}
            else:
                from ...services.runtime_policy_service import RuntimePolicyService
                policy = RuntimePolicyService.load_policy_config()

        workspace_root = input.context.get("workspace_root", ".")
        execution_policy = self._resolve_execution_policy(input.context)
        executor = ToolExecutor(
            workspace_root=workspace_root,
            policy=policy,
            execution_policy=execution_policy,
        )
        
        results = []
        artifacts_out = {}
        status = "continue"
        
        # Priority 1: Tool calls
        if tool_calls:
            for tc in tool_calls:
                # Handle both OpenAI/Anthropic and internal shapes
                func = tc.get("function") or tc
                name = func.get("name")
                args_raw = func.get("arguments", "{}")
                
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    res = await executor.execute_tool_call(name, args)
                    results.append(res)
                    if res.get("status") == "error":

                        status = "fail"
                        artifacts_out["error"] = res.get("message")
                        break
                except Exception as e:
                    status = "fail"
                    artifacts_out["error"] = f"Failed to parse arguments for {name}: {str(e)}"
                    break
        else:
            # Fallback path if no tool calls found.
            # Priority 1: explicit FileTaskSpec contract in context (preferred).
            spec_raw = input.context.get("file_task_spec")
            if spec_raw:
                try:
                    spec = FileTaskSpec.model_validate(spec_raw)
                    target_path = spec.target_path
                except Exception:
                    target_path = None
            else:
                target_path = None
            # Priority 2: heuristic extraction from LLM content (backwards-compat fallback).
            if not target_path:
                target_path = self._extract_fallback_path(llm_content, input.context)
            logger.info("[FileWrite] target_path extracted: %r (content[:80]=%r)", target_path, llm_content[:80])
            if not target_path:
                # No file operations needed — pass through (e.g., legacy_run text-only response)
                logger.info("[FileWrite] No target path found — pass-through (no-op)")
                status = "continue"
            else:
                # Workspace bounds check: reject paths that escape the workspace
                try:
                    self._assert_within_workspace(target_path, workspace_root)
                except ValueError:
                    logger.warning("[FileWrite] Path traversal rejected: %r escapes workspace %r", target_path, workspace_root)
                    status = "fail"
                    artifacts_out["error"] = f"Path traversal rejected: {target_path!r} escapes workspace"
                    artifacts_out["file_op_results"] = results
                    return StageOutput(status=status, artifacts=artifacts_out)
                fallback_content = llm_content.strip()
                # Strip any TARGET_FILE directive line that the agent may have emitted
                fallback_content = re.sub(r"(?m)^TARGET_FILE:[^\n]*\n?", "", fallback_content).strip()
                if fallback_content.startswith("```"):
                    fallback_content = re.sub(r"```\w*\n?", "", fallback_content).strip()
                logger.info("[FileWrite] writing %d chars to %r", len(fallback_content), target_path)
                res = await executor.execute_tool_call(
                    "write_file",
                    {"path": target_path, "content": fallback_content},
                )
                logger.info("[FileWrite] result: %s", res)
                results.append(res)
                if res.get("status") == "error":
                    status = "fail"
                    artifacts_out["error"] = res.get("message")
            
        artifacts_out["file_op_results"] = results
        return StageOutput(status=status, artifacts=artifacts_out)

    async def rollback(self, input: StageInput) -> None:
        """File write rollback requires git checkpointing (Phase 3)."""

