"""Contract checking and rollback logic for GraphEngine."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.gimo_server.ops_models import ContractCheck, WorkflowContract, WorkflowNode

logger = logging.getLogger("orchestrator.services.graph_engine")


class ContractValidatorMixin:
    """Contract checks (pre/post), rollback, and human review."""

    def _run_contract_check(self, node) -> Dict[str, Any]:
        """Execute contract checks in pre/post mode."""
        from tools.gimo_server.ops_models import WorkflowContract
        raw_contract = node.config.get("contract", node.config)
        contract = WorkflowContract.model_validate(raw_contract)
        phase = str(node.config.get("phase", "pre")).lower()
        checks = contract.pre_conditions if phase == "pre" else contract.post_conditions

        failed: List[Dict[str, Any]] = []
        for check in checks:
            passed = self._evaluate_contract_check(check)
            if not passed:
                failed.append({"type": check.type, "params": check.params})

        output = {
            "contract_phase": phase,
            "checks_total": len(checks),
            "checks_failed": failed,
            "contract_passed": len(failed) == 0,
            "blast_radius": contract.blast_radius,
        }

        if failed and phase == "post":
            rollback_result = self._run_rollback(contract.rollback)
            output["rollback_executed"] = rollback_result
            self.state.data["contract_failure"] = output
            raise RuntimeError(f"Post-contract checks failed: {failed}")

        if failed:
            self.state.data["contract_failure"] = output
            raise RuntimeError(f"Pre-contract checks failed: {failed}")

        self.state.data["last_contract_check"] = output
        return output

    async def _run_human_review(self, node) -> Dict[str, Any]:
        """Interactive HITL node."""
        from tools.gimo_server.ops_models import WorkflowNode

        reviews = self.state.data.setdefault("human_reviews", {})
        annotations = self.state.data.setdefault("human_annotations", [])
        decision_payload = reviews.get(node.id)

        timeout_seconds = int(node.config.get("timeout_seconds", 0) or 0)
        default_action = str(node.config.get("default_action", "block"))
        now = datetime.now(timezone.utc)
        pending_key = "human_review_pending"
        pending = dict(self.state.data.get(pending_key) or {})

        if not decision_payload:
            pending_started_at = pending.get("started_at")
            started_dt = self._parse_iso_ts(pending_started_at)
            if pending.get("node_id") != node.id or not started_dt:
                started_dt = now
                pending = {
                    "node_id": node.id,
                    "started_at": started_dt.isoformat(),
                    "timeout_seconds": timeout_seconds,
                    "default_action": default_action,
                }
                self.state.data[pending_key] = pending

            if timeout_seconds > 0 and (now - started_dt).total_seconds() >= timeout_seconds:
                if default_action == "approve":
                    self.state.data.pop(pending_key, None)
                    return {
                        "human_review": "auto_approved_timeout",
                        "human_review_node": node.id,
                    }
                raise RuntimeError(f"Human review timeout at node {node.id}; default_action={default_action}")

            return {
                "pause_execution": True,
                "pause_reason": "human_review_pending",
                "human_review_node": node.id,
                "timeout_seconds": timeout_seconds,
                "default_action": default_action,
            }

        decision = str(decision_payload.get("decision", "")).lower().strip()
        edited_state = decision_payload.get("edited_state") or {}
        annotation = decision_payload.get("annotation")
        if annotation:
            annotations.append(
                {
                    "node_id": node.id,
                    "timestamp": now.isoformat(),
                    "note": str(annotation),
                }
            )

        self.state.data.pop(pending_key, None)

        if decision == "approve":
            return {
                "human_review": "approved",
                "human_review_node": node.id,
            }

        if decision == "reject":
            raise RuntimeError(f"Human review rejected at node {node.id}")

        if decision in {"edit", "edit_state"}:
            if isinstance(edited_state, dict):
                self.state.data.update(edited_state)
            return {
                "human_review": "edited",
                "human_review_node": node.id,
                "edited_keys": sorted(list(edited_state.keys())) if isinstance(edited_state, dict) else [],
            }

        if decision == "takeover":
            if isinstance(edited_state, dict):
                self.state.data.update(edited_state)
            return {
                "human_review": "takeover",
                "human_review_node": node.id,
                "takeover": True,
            }

        if decision == "fork":
            branches = node.config.get("fork_options") or []
            selected_branch = decision_payload.get("selected_branch")
            if not isinstance(branches, list) or not branches:
                raise RuntimeError(f"Fork requested at node {node.id} but no branch selected")

            async def _run_branch(idx: int, branch: Any) -> Dict[str, Any]:
                await asyncio.sleep(0)
                if isinstance(branch, dict):
                    branch_id = str(branch.get("id") or branch.get("name") or f"branch_{idx + 1}")
                    return {
                        "branch_id": branch_id,
                        "state_patch": dict(branch.get("state_patch") or {}),
                        "output": branch.get("output"),
                    }

                branch_id = str(branch)
                return {
                    "branch_id": branch_id,
                    "state_patch": {},
                    "output": None,
                }

            branch_results = await asyncio.gather(*[_run_branch(i, b) for i, b in enumerate(branches)])
            by_id = {item["branch_id"]: item for item in branch_results}

            if selected_branch is None:
                selected_branch = branch_results[0]["branch_id"]

            selected_branch = str(selected_branch)
            selected_payload = by_id.get(selected_branch)
            if selected_payload is None:
                raise RuntimeError(f"Fork requested at node {node.id} but selected branch is invalid: {selected_branch}")

            state_patch = selected_payload.get("state_patch")
            if isinstance(state_patch, dict) and state_patch:
                self.state.data.update(state_patch)

            return {
                "human_review": "fork_selected",
                "human_review_node": node.id,
                "selected_branch": selected_branch,
                "fork_results": branch_results,
            }

        raise RuntimeError(f"Unsupported human review decision at node {node.id}: {decision}")

    def _evaluate_contract_check(self, check) -> bool:
        check_type = check.type
        params = check.params

        if check_type == "file_exists":
            path = params.get("path")
            return bool(path and Path(path).exists())

        if check_type == "function_exists":
            func_name = params.get("function_name")
            content = params.get("content")
            if content is None and params.get("path"):
                try:
                    content = Path(params["path"]).read_text(encoding="utf-8")
                except Exception:
                    return False
            if not func_name or not isinstance(content, str):
                return False
            return f"def {func_name}(" in content

        if check_type == "tests_pass":
            key = params.get("state_key", "tests_passed")
            return bool(self.state.data.get(key, False))

        if check_type == "no_new_vulnerabilities":
            key = params.get("state_key", "new_vulnerabilities")
            return int(self.state.data.get(key, 0) or 0) == 0

        if check_type == "custom":
            key = params.get("state_key")
            expected = params.get("equals", True)
            if key is None:
                return False
            return self.state.data.get(key) == expected

        return False

    def _run_rollback(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        executed: List[Dict[str, Any]] = []
        for action in actions:
            action_type = action.get("type")
            if action_type == "set_state":
                key = action.get("key")
                if key is not None:
                    self.state.data[key] = action.get("value")
                    executed.append({"type": action_type, "key": key})
            elif action_type == "remove_state":
                key = action.get("key")
                if key in self.state.data:
                    self.state.data.pop(key, None)
                    executed.append({"type": action_type, "key": key})

        self.state.data["rollback_actions"] = executed
        return {"count": len(executed), "actions": executed}
