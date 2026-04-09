import json
import time
import sys
import logging
from typing import Any
from mcp.server.fastmcp import FastMCP

# Keep original references for module loading and stat checking
_server_start_time = time.time()
logger = logging.getLogger("mcp_bridge.native_tools")

# Strong references to fire-and-forget background tasks (prevents GC mid-flight)
_BACKGROUND_CHAT_TASKS: set = set()

def register_native_tools(mcp: FastMCP):
    # R18 Change 1 — declare Pydantic-bound tools for the boot-time drift guard.
    from .native_inputs import (
        GenerateTeamConfigInput,
        GicsAnomalyReportInput,
        GicsModelReliabilityInput,
    )
    from . import _register as _drift

    _drift.bind("gimo_generate_team_config", GenerateTeamConfigInput)
    # R18 Change 5 — bind GICS MCP tools for drift protection.
    _drift.bind("gimo_gics_model_reliability", GicsModelReliabilityInput)
    _drift.bind("gimo_gics_anomaly_report", GicsAnomalyReportInput)

    @mcp.tool()
    async def gimo_get_status() -> str:
        """Returns the canonical GIMO operator status snapshot.

        Thin wrapper over OperatorStatusService.get_status_snapshot() — the
        single source of truth for backend/provider/thread/budget/permissions
        state. Does NOT invent state, does NOT probe sockets, does NOT synthesize
        "RUNNING"/"STOPPED" strings. Returns the same dict that /ops/operator/status
        serves, as JSON.
        """
        try:
            import json
            from tools.gimo_server.services.operator_status_service import OperatorStatusService
            snapshot = OperatorStatusService.get_status_snapshot()
            return json.dumps(snapshot, indent=2, default=str)
        except Exception as e:
            logger.error("gimo_get_status failed: %s", e, exc_info=True)
            return json.dumps({"error": "status_snapshot_failed", "detail": str(e)})

    @mcp.tool()
    async def gimo_wake_ollama() -> str:
        """Attempts to start the local Ollama service if it is offline."""
        from tools.gimo_server.services.providers.catalog_service import ProviderCatalogService
        success = await ProviderCatalogService.ensure_ollama_ready()
        if success:
            return "Ollama service is now ONLINE and ready."
        return "Failed to wake up Ollama. Check if it is installed and available in PATH."

    @mcp.tool()
    def gimo_start_engine() -> str:
        """Start the GIMO backend if not already running. Idempotent.

        **Bootstrap tool for MCP-only operators.** Clients that have no
        access to a terminal/CLI on the host (e.g., Claude Desktop, Claude
        App, ChatGPT App Actions using the stdio MCP bridge as subprocess)
        reach GIMO through this bridge process, which runs locally on the
        host and has filesystem access. When the user's only surface is
        MCP, this is the single legitimate bootstrap path to the backend.

        Thin trampoline over the canonical launcher at
        ``gimo_cli.commands.server.start_server``. Does NOT fork its own
        uvicorn, does NOT mint ORCH_TOKEN, does NOT touch .env, does NOT
        spawn vite. All lifecycle authority lives in the canonical
        launcher (honest lifecycle, R21 cleanup/launcher-honest).

        If you have a terminal on the host, prefer ``gimo up`` from the
        shell — it is the same code path.

        Returns:
            JSON status with url, pid, version, and a flag indicating
            whether the server was already running or newly started.
        """
        import json
        try:
            from gimo_cli.commands.server import (
                DEFAULT_SERVER_HOST,
                DEFAULT_SERVER_PORT,
                _health_details,
                _server_url,
                server_healthy,
                start_server,
            )

            host, port = DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT
            url = _server_url(host, port)

            if server_healthy(url):
                pid, version = _health_details(url)
                return json.dumps(
                    {
                        "status": "already_running",
                        "url": url,
                        "pid": pid,
                        "version": version,
                    },
                    default=str,
                )

            # Delegate to canonical launcher (single source of truth).
            ok = start_server(host, port)
            if not ok:
                return json.dumps(
                    {
                        "status": "failed",
                        "url": url,
                        "detail": "start_server() returned False; check server logs.",
                    }
                )

            pid, version = _health_details(url)
            return json.dumps(
                {
                    "status": "started",
                    "url": url,
                    "pid": pid,
                    "version": version,
                },
                default=str,
            )
        except Exception as exc:
            logger.error("gimo_start_engine failed: %s", exc, exc_info=True)
            return json.dumps({"error": "start_engine_failed", "detail": str(exc)})

    @mcp.tool()
    def gimo_stop_engine() -> str:
        """Stop the GIMO backend gracefully. Idempotent.

        **Symmetric counterpart to gimo_start_engine.** For MCP-only
        operators (Claude Desktop, Claude App, ChatGPT App Actions via
        stdio bridge), this is the legitimate shutdown path when no
        terminal/CLI is available on the host.

        Thin trampoline over the canonical shutdown logic at
        ``gimo_cli.commands.server`` (which calls POST /ops/shutdown with
        PID-kill fallback and verifies the server is actually down). Does
        NOT fork its own kill path, does NOT touch PID files, does NOT
        mutate ``server._active_run_worker``. All lifecycle authority
        lives in the canonical launcher.

        If you have a terminal on the host, prefer ``gimo down`` from the
        shell — it is the same code path.

        Returns:
            JSON status with url and a flag indicating whether the
            server was already stopped or newly terminated.
        """
        import json
        try:
            from gimo_cli.commands.server import (
                DEFAULT_SERVER_HOST,
                DEFAULT_SERVER_PORT,
                _find_pids_on_port,
                _kill_all_on_port,
                _server_url,
                _wait_for_server_down,
                server_healthy,
            )

            host, port = DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT
            url = _server_url(host, port)

            health_before = server_healthy(url, timeout=1.5)
            pids_before = _find_pids_on_port(port)
            if not health_before and not pids_before:
                return json.dumps(
                    {
                        "status": "already_stopped",
                        "url": url,
                    }
                )

            found, killed = _kill_all_on_port(port, url)
            down_state = _wait_for_server_down(url, port, timeout_seconds=15.0)
            if down_state is None:
                remaining = _find_pids_on_port(port)
                return json.dumps(
                    {
                        "status": "failed",
                        "url": url,
                        "detail": "server did not fall to unreachable within 15s",
                        "remaining_pids": remaining,
                    }
                )

            return json.dumps(
                {
                    "status": "stopped",
                    "url": url,
                    "down_state": down_state,
                    "listeners_found": found,
                    "listeners_killed": killed,
                }
            )
        except Exception as exc:
            logger.error("gimo_stop_engine failed: %s", exc, exc_info=True)
            return json.dumps({"error": "stop_engine_failed", "detail": str(exc)})

    @mcp.tool()
    def gimo_get_server_info() -> str:
        """Return diagnostics for the MCP bridge process itself and module staleness.

        Read-only introspection of the bridge process: uptime, sys.executable,
        whether a RunWorker instance is attached, and mtime/hash of key modules
        on disk versus their import cache. Useful for developers who need to
        diagnose "why doesn't my change appear?" over MCP when no terminal is
        available on the host.

        This tool does NOT replace gimo_get_status (canonical operator/backend
        snapshot). It is complementary: gimo_get_status answers "what does GIMO
        know?", gimo_get_server_info answers "what code is the bridge process
        actually running?".

        Has no canonical backend replacement — the backend cannot inspect its
        own Python import cache from outside its process boundary.
        """
        import hashlib
        import importlib
        from datetime import datetime, timezone
        from pathlib import Path

        uptime_s = int(time.time() - _server_start_time)
        started_at = datetime.fromtimestamp(_server_start_time, tz=timezone.utc).isoformat()

        from tools.gimo_server.mcp_bridge import server
        worker_running = getattr(server, "_active_run_worker", None) is not None

        module_keys = [
            "tools.gimo_server.services.run_worker",
            "tools.gimo_server.mcp_bridge.server",
            "tools.gimo_server.services.providers.service",
        ]

        lines = [
            "GIMO MCP Bridge Server Diagnostics",
            f"Started : {started_at}",
            f"Uptime  : {uptime_s}s",
            f"Worker  : {'running' if worker_running else 'not started'}",
            f"sys.exe : {sys.executable}",
            "",
            "Module File States (mtime vs import cache):",
        ]

        for mod_name in module_keys:
            try:
                mod = importlib.import_module(mod_name)
                src_file = getattr(mod, "__file__", None)
                if src_file:
                    p = Path(src_file).resolve()
                    disk_mtime = p.stat().st_mtime
                    disk_hash = hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest()[:8]  # nosec B324
                    mod_mtime = getattr(mod, "_cached_mtime", None)
                    stale = "⚠ STALE" if (mod_mtime and mod_mtime != disk_mtime) else "✅ current"
                    lines.append(f"  {mod_name.split('.')[-1]}: {p}\n    mtime={int(disk_mtime)} hash={disk_hash} [{stale}]")
            except Exception as e:
                lines.append(f"  {mod_name.split('.')[-1]}: error → {e}")

        return "\n".join(lines)

    # ── gimo_reload_worker — dev-mode only ───────────────────────────────────
    # Hot-reload of the RunWorker module without bouncing the bridge/backend
    # process. Kept behind GIMO_DEV_MODE env gate because:
    #   1) importlib.reload has known state-corruption risks in the presence
    #      of module-level globals and concurrent in-flight work.
    #   2) Forcing a reload from a remote MCP client is effectively a
    #      privileged dev affordance, not an operator concern.
    # When the gate is off, the canonical safe path for operators is the
    # sequence gimo_stop_engine → gimo_start_engine (full bounce).
    import os as _os_dev_gate
    if _os_dev_gate.environ.get("GIMO_DEV_MODE", "").strip().lower() in ("1", "true", "yes", "on"):
        @mcp.tool()
        async def gimo_reload_worker() -> str:
            """Hot-reload the RunWorker module without restarting the MCP bridge process.

            **Dev-only.** Registered only when GIMO_DEV_MODE is truthy. Has no
            canonical bounce-equivalent replacement — gimo_stop_engine + gimo_start_engine
            is a full process bounce with different semantics (clears ALL module
            state, not just the worker). Hot-reload preserves the bridge process
            and the rest of the in-memory state, which is why devs want it.

            Risks (why it's gated):
            - importlib.reload does NOT re-execute dependency modules; a change
              in a module that run_worker imports will NOT appear.
            - If another request holds the old RunWorker instance, race conditions
              are possible.
            - Module-level globals in run_worker may become inconsistent.

            When in doubt, use gimo_stop_engine → gimo_start_engine for a clean
            bounce.
            """
            import importlib
            from tools.gimo_server.mcp_bridge import server

            steps = []
            current_worker = getattr(server, "_active_run_worker", None)
            if current_worker is not None:
                try:
                    await current_worker.stop()
                    steps.append("✅ Old RunWorker stopped")
                except Exception as e:
                    steps.append(f"⚠ Could not stop old worker cleanly: {e}")
                server._active_run_worker = None

            try:
                mod_name = "tools.gimo_server.services.run_worker"
                if mod_name in sys.modules:
                    importlib.reload(sys.modules[mod_name])
                    steps.append(f"✅ Module '{mod_name}' reloaded from disk")
                else:
                    importlib.import_module(mod_name)
            except Exception as e:
                return f"❌ Module reload failed: {e}"

            try:
                from tools.gimo_server.services.run_worker import RunWorker
                server._active_run_worker = RunWorker()
                await server._active_run_worker.start()
                steps.append("✅ New RunWorker instantiated and started")
            except Exception as e:
                return f"❌ Failed to start new worker: {e}"

            return "\n".join(steps) + "\n🚀 GIMO RunWorker hot-reloaded successfully."

    def _generate_mermaid_graph(plan_data: Any) -> str:
        try:
            from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService

            payload = TaskDescriptorService.coerce_plan_data(plan_data)
            raw_tasks = payload.get("tasks") or []
            normalized_plan = TaskDescriptorService.normalize_plan_data(payload)
            lines = ["graph TD"]
            for index, task in enumerate(normalized_plan.get("tasks", [])):
                raw_task = raw_tasks[index] if index < len(raw_tasks) and isinstance(raw_tasks[index], dict) else {}
                node_id = str(task.get("id") or f"task_{index}").replace("-", "_")
                label = f'"{task.get("title") or node_id}<br/>[{raw_task.get("status") or "pending"}]"'
                lines.append(f"    {node_id}[{label}]")
                for dep in task.get("depends_on") or []:
                    lines.append(f"    {dep.replace('-', '_')} --> {node_id}")
            return "\\n".join(lines)
        except Exception as e:
            return f"Error graph: {e}"

    @mcp.tool()
    async def gimo_propose_structured_plan(task_instructions: str) -> str:
        """Generates a structured multi-step plan with task dependencies and Mermaid graph.

        **Call this when the user asks for a non-trivial task that requires
        planning.** Materializes a plan via the backend and returns a rich
        structured presentation: tasks with dependencies, Mermaid graph,
        cost estimate, risk band, and governance verdict.

        **After calling this tool, you MUST present the plan for human approval
        before executing it.** This is not a suggestion — it is a mandatory
        protocol. The human must see and confirm the plan before any work begins.

        Protocol:
        1. Call this tool with the task instructions.
        2. Use ``EnterPlanMode`` to write the plan to the plan file. Include:
           - The Mermaid graph from the ``graph`` field
           - A task table with id, title, role, dependencies, scope
           - Cost estimate and risk band
           - The ``draft_id`` (needed for step 4)
        3. Call ``ExitPlanMode`` — the user sees the plan and approves or rejects.
        4. If approved: call ``gimo_approve_draft(draft_id, auto_run=True)``.
        5. If rejected: relay the user's feedback. Do not approve.

        If the user wants to skip review entirely (e.g. "just do it", "skip
        planning"), use ``gimo_run_task`` instead — the explicit bypass path.
        """
        import json as _json
        try:
            from .bridge import proxy_to_api

            # 1. Materialize plan via canonical backend endpoint
            plan_result = await proxy_to_api(
                "POST", "/ops/generate-plan",
                __query={"prompt": task_instructions, "operator_class": "cognitive_agent"},
            )

            # 2. Parse the draft response
            draft_data = {}
            draft_id = None
            try:
                body = plan_result.split("\n", 1)[-1]
                draft_data = _json.loads(body)
                draft_id = draft_data.get("id")
            except (ValueError, IndexError, _json.JSONDecodeError):
                return _json.dumps({
                    "error": "plan_materialization_failed",
                    "detail": str(plan_result)[:500],
                })

            if not draft_id:
                return _json.dumps({
                    "error": "no_draft_id_returned",
                    "detail": str(plan_result)[:500],
                })

            # 3. Fetch the full draft content (plan JSON lives here)
            draft_detail = await proxy_to_api("GET", f"/ops/drafts/{draft_id}")
            content = None
            try:
                detail_body = draft_detail.split("\n", 1)[-1]
                detail_data = _json.loads(detail_body)
                content = detail_data.get("content")
            except (ValueError, IndexError, _json.JSONDecodeError):
                pass

            # 4. Build the rich presentation
            presentation: dict = {
                "draft_id": draft_id,
                "status": draft_data.get("status", "draft"),
                "operator_class": draft_data.get("operator_class"),
                "execution_decision": (draft_data.get("context") or {}).get("execution_decision"),
                "risk_band": (draft_data.get("context") or {}).get("risk_band"),
            }

            # Parse plan content for tasks + graph
            if content:
                try:
                    plan = _json.loads(content) if isinstance(content, str) else content
                except _json.JSONDecodeError:
                    plan = {}

                presentation["title"] = plan.get("title", task_instructions[:80])
                presentation["objective"] = plan.get("objective", task_instructions)

                tasks = plan.get("tasks") or []
                task_summary = []
                for t in tasks:
                    task_summary.append({
                        "id": t.get("id", "?"),
                        "title": t.get("title", "?"),
                        "scope": t.get("scope", "?"),
                        "depends_on": t.get("depends") or t.get("depends_on") or [],
                        "status": t.get("status", "pending"),
                        "role": (t.get("agent_assignee") or {}).get("role", "?"),
                    })
                presentation["tasks"] = task_summary
                presentation["task_count"] = len(task_summary)

                # Generate Mermaid graph
                try:
                    presentation["graph"] = _generate_mermaid_graph(plan)
                except Exception:
                    presentation["graph"] = None
            else:
                presentation["title"] = task_instructions[:80]
                presentation["objective"] = task_instructions
                presentation["tasks"] = []
                presentation["task_count"] = 0
                presentation["graph"] = None
                presentation["note"] = "Plan content not yet materialized; the draft may still be generating."

            return _json.dumps(presentation, indent=2, default=str)

        except Exception as e:
            return _json.dumps({"error": "propose_plan_failed", "detail": str(e)})

    @mcp.tool()
    async def gimo_create_draft(task_instructions: str, target_agent_id: str = "auto") -> str:
        """Creates an Ops Draft based on task instructions with Mermaid planning."""
        try:
            from .bridge import proxy_to_api
            # R21: MCP-originated drafts are cognitive_agent so policy gating
            # whitelists them at fallback_to_most_restrictive_human_review.
            result = await proxy_to_api(
                "POST", "/ops/drafts",
                __body={
                    "prompt": task_instructions,
                    "provider": "mcp",
                    "context": {"operator_class": "cognitive_agent", "surface_type": "mcp"},
                },
            )
            return result
        except Exception as e: return str(e)

    @mcp.tool()
    async def gimo_run_task(task_instructions: str, target_agent_id: str = "auto") -> str:
        """Automatically create, approve, and execute a plan through the full governance chain.

        **This is the BYPASS path.** It creates a draft, approves it, and starts
        execution in one step WITHOUT presenting the plan for human review. Use
        this ONLY when the human has explicitly authorized unreviewed execution
        (e.g. "just run it", "skip review", "auto-approve").

        For the canonical review path where the human sees and confirms the plan
        before execution, use ``gimo_propose_structured_plan`` followed by
        ``gimo_approve_draft`` after human confirmation.
        """
        try:
            from .bridge import proxy_to_api
            import json
            # 1. Create draft via HTTP (no LLM — instant)
            # R21: MCP-originated drafts are cognitive_agent so policy gating
            # whitelists them at fallback_to_most_restrictive_human_review.
            draft_result = await proxy_to_api(
                "POST", "/ops/drafts",
                __body={
                    "prompt": task_instructions,
                    "provider": "mcp_auto",
                    "context": {"operator_class": "cognitive_agent", "surface_type": "mcp"},
                },
            )
            # Extract draft ID from proxy response (format: "✅ Success (201):\n{json}")
            draft_id = None
            try:
                body = draft_result.split("\n", 1)[-1]
                data = json.loads(body)
                draft_id = data.get("id")
            except (json.JSONDecodeError, ValueError, IndexError):
                pass
            if not draft_id:
                return f"Draft creation failed:\n{draft_result}"
            # 2. Approve via HTTP (risk gate, intent gate, auto_run gate)
            approve_result = await proxy_to_api(
                "POST", f"/ops/drafts/{draft_id}/approve",
                __query={"auto_run": "true"},
            )
            return approve_result
        except Exception as e: return str(e)

    @mcp.tool()
    async def gimo_resolve_handover(run_id: str, decision: str, edited_state: dict = None) -> str:
        """Resume a blocked run after human intervention/handover decision.

        R18 Change 7 — HITL decisions are recorded as draft entries in the
        ops draft store so every handover has an auditable entry that the
        proof chain and governance snapshot can cite. The actual workflow
        resume is then delegated to /ops/workflows/{id}/resume.
        """
        from .bridge import proxy_to_api
        import json as _json
        try:
            await proxy_to_api(
                "POST", "/ops/drafts",
                __body={
                    "prompt": f"hitl_resolve_handover(run_id={run_id}, decision={decision})",
                    "execution": {"intent_class": "hitl_decision"},
                    "acceptance_criteria": [],
                    "context": {
                        "kind": "hitl_decision",
                        "run_id": run_id,
                        "decision": decision,
                        "edited_state": edited_state or {},
                    },
                },
            )
        except Exception as exc:
            logger.warning("gimo_resolve_handover: draft record failed: %s", exc)
        try:
            return await proxy_to_api(
                "POST", f"/ops/runs/{run_id}/resume",
                __body={"decision": decision, "edited_state": edited_state or {}},
            )
        except Exception as exc:
            return _json.dumps({
                "status": "draft_recorded_only",
                "run_id": run_id,
                "decision": decision,
                "error": str(exc),
            })

    @mcp.tool()
    async def gimo_get_draft(draft_id: str) -> str:
        """Returns the raw plan content for a given draft."""
        from .bridge import proxy_to_api
        return await proxy_to_api("GET", f"/ops/drafts/{draft_id}")

    @mcp.tool()
    async def gimo_approve_draft(draft_id: str, auto_run: bool = True) -> str:
        """Approve a draft through the full governance chain (risk gate, intent gate, auto_run gate, audit log).

        **Call this ONLY after the human has reviewed and confirmed the plan.**
        The canonical flow is: ``gimo_propose_structured_plan`` → human reviews
        the presented plan in the chat → human says "yes" → operator calls this
        tool. Do NOT call this without human confirmation unless the human has
        explicitly granted a session-wide bypass (e.g. "auto-approve everything").

        Args:
            draft_id: ID of the draft to approve
            auto_run: Whether to automatically run after approval (default True)
        """
        from .bridge import proxy_to_api
        return await proxy_to_api(
            "POST", f"/ops/drafts/{draft_id}/approve",
            __query={"auto_run": str(auto_run).lower()},
        )

    @mcp.tool()
    async def gimo_get_task_status(run_id: str) -> str:
        """Check if a run is pending, running, or done."""
        from .bridge import proxy_to_api
        return await proxy_to_api("GET", f"/ops/runs/{run_id}")

    @mcp.tool()
    async def gimo_get_plan_graph(draft_or_run_id: str) -> str:
        """Returns the Mermaid graph visualization for a draft or run."""
        try:
            from .bridge import proxy_to_api
            import json
            if draft_or_run_id.startswith("r_"):
                result = await proxy_to_api("GET", f"/ops/runs/{draft_or_run_id}")
                try:
                    data = json.loads(result.split("\n", 1)[-1])
                    approved_id = data.get("approved_id", "")
                    if approved_id:
                        approved_result = await proxy_to_api("GET", f"/ops/approved/{approved_id}")
                        approved_data = json.loads(approved_result.split("\n", 1)[-1])
                        content = approved_data.get("content")
                    else:
                        content = None
                except (json.JSONDecodeError, ValueError):
                    return f"Could not parse run data for {draft_or_run_id}"
            else:
                result = await proxy_to_api("GET", f"/ops/drafts/{draft_or_run_id}")
                try:
                    data = json.loads(result.split("\n", 1)[-1])
                    content = data.get("content")
                except (json.JSONDecodeError, ValueError):
                    return f"Could not parse draft data for {draft_or_run_id}"
            if not content:
                return f"No plan found for {draft_or_run_id}"
            graph = _generate_mermaid_graph(content)
            return f"```mermaid\\n{graph}\\n```"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def gimo_spawn_subagent(
        name: str,
        task: str,
        role: str = "worker",
        provider: str = "auto",
        model: str = "auto",
        execution_policy: str = "workspace_safe",
        workspace_path: str = "",
    ) -> str:
        """Spawn a governed sub-agent with optional provider/model selection.

        Args:
            name: Agent name
            task: Task description for the agent
            role: Agent role (worker, reviewer, etc.)
            provider: Provider ID or "auto" for automatic selection
            model: Model ID or "auto" for automatic selection
            execution_policy: Execution policy (read_only, workspace_safe, etc.)
            workspace_path: Workspace directory (defaults to ORCH_REPO_ROOT)
        """
        try:
            import os
            from tools.gimo_server.services.agent_broker_service import AgentBrokerService, BrokerTaskDescriptor
            ws = workspace_path or os.environ.get("ORCH_REPO_ROOT", ".")
            result = await AgentBrokerService.spawn_governed_agent(
                BrokerTaskDescriptor(
                    name=name,
                    task=task,
                    role=role,
                    preferred_provider=provider,
                    preferred_model=model,
                    execution_policy=execution_policy,
                    workspace_path=ws,
                    parent_id="mcp",
                    # R20-003: surface the true caller instead of the
                    # hardcoded "agent_sdk" tag previously used by the
                    # broker. R20-001: MCP is a cognitive_agent operator.
                    surface_type="mcp",
                    surface_name=f"mcp:{name}",
                    operator_class="cognitive_agent",
                )
            )
            if result.get("spawned"):
                result["name"] = name
                result["workspace_path"] = ws
            return json.dumps(result, indent=2, default=str)
        except Exception as e: return str(e)

    @mcp.tool()
    async def gimo_list_agents() -> str:
        """Lists all available sub-agents and their descriptions."""
        try:
            from tools.gimo_server.services.sub_agent_manager import SubAgentManager
            await SubAgentManager.sync_with_ollama()
            agents = SubAgentManager.get_sub_agents()
            if not agents: return "No agents found."
            lines = ["Available GIMO Agents:"]
            for ag in agents: lines.append(f"- ID: {ag.id} | Name: {ag.name} | Description: {ag.description}")
            return "\\n".join(lines)
        except Exception as e: return str(e)

    @mcp.tool()
    async def gimo_web_search(query: str, providers: str = "duckduckgo", max_results: int = 10) -> str:
        """Search the web using GIMO's parallel multi-provider search engine.
        providers: comma-separated list from: duckduckgo,tavily,jina,brave,exa"""
        try:
            from tools.gimo_server.models.web_search import WebSearchQuery
            from tools.gimo_server.services.web_search_service import WebSearchService
            provider_list = [p.strip() for p in providers.split(",") if p.strip()]
            q = WebSearchQuery(query=query, providers=provider_list, max_results=max_results, include_content=True)
            response = await WebSearchService.search(q)
            if response.results:
                from tools.gimo_server.services.web_search_content_extractor import extract_content_for_results
                response.results = await extract_content_for_results(response.results[:5])
            lines = [f"Search: {response.query} ({response.fusion_time_ms:.0f}ms, {len(response.providers_used)} providers)"]
            for r in response.results[:max_results]:
                lines.append(f"\n--- {r.title} ---\nURL: {r.url}\nScore: {r.relevance_score:.2f} ({r.provider})")
                if r.content:
                    lines.append(r.content[:1000])
                elif r.snippet:
                    lines.append(r.snippet)
            if response.providers_failed:
                lines.append(f"\nFailed: {', '.join(response.providers_failed)}")
            return "\n".join(lines)
        except Exception as e:
            return f"Search error: {e}"

    @mcp.tool()
    async def gimo_chat(message: str, thread_id: str = "", workspace_root: str = "") -> str:
        """Send a message to GIMO's agentic chat (fire-and-return).

        Because the agentic loop can take minutes (multi-turn LLM + tool execution)
        and MCP stdio clients enforce a ~60s timeout, this tool does NOT block on the
        response. It dispatches the chat in the background and returns immediately
        with the thread_id. Callers must poll the thread to retrieve results.

        Creates a new thread if thread_id is empty.

        Polling contract:
          - GET /ops/threads/{thread_id} returns the full thread including all turns.
          - When the agent finishes, new assistant turns appear with agent_id='orchestrator'
            (the agentic loop persists assistant responses under that agent_id).
          - On failure, a turn with agent_id='gimo_chat_error' is appended; its first
            text item begins with '[gimo_chat error]'.

        Returns:
            A status string containing the thread_id and polling instructions.
            Does NOT contain the assistant's response — fetch it from the thread.
        """
        from .bridge import proxy_to_api, _get_auth_token, BACKEND_URL
        import httpx
        import asyncio
        import json

        try:
            token = _get_auth_token()
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                # Create thread if needed
                if not thread_id:
                    ws = workspace_root or "."
                    resp = await client.post(
                        f"{BACKEND_URL}/ops/threads",
                        params={"workspace_root": ws, "title": "MCP Chat Session"},
                        headers=headers,
                    )
                    if resp.status_code != 201:
                        return f"Failed to create thread: HTTP {resp.status_code} {resp.text[:200]}"
                    thread_data = resp.json()
                    thread_id = thread_data.get("id", "")

            # Fire-and-return: launch chat in background, return immediately
            # The agentic loop can take minutes — MCP stdio times out at ~60s.
            # On failure, the background task posts an error message to the thread so
            # clients polling GET /ops/threads/{id} can discover it.
            captured_thread_id = thread_id
            captured_headers = dict(headers)

            async def _record_error(client: httpx.AsyncClient, error_text: str) -> None:
                """Record a background failure as a properly-attributed system turn.
                Uses /turns?agent_id=gimo_chat_error (NOT /messages, which hardcodes
                agent_id='User' and would falsely attribute the error to the user)."""
                try:
                    turn_resp = await client.post(
                        f"{BACKEND_URL}/ops/threads/{captured_thread_id}/turns",
                        params={"agent_id": "gimo_chat_error"},
                        headers=captured_headers,
                    )
                    if turn_resp.status_code in (200, 201):
                        turn_data = turn_resp.json()
                        turn_id = turn_data.get("id")
                        if turn_id:
                            await client.post(
                                f"{BACKEND_URL}/ops/threads/{captured_thread_id}/turns/{turn_id}/items",
                                params={"type": "text", "content": f"[gimo_chat error] {error_text[:500]}"},
                                headers=captured_headers,
                            )
                except Exception:
                    pass

            async def _background_chat():
                try:
                    async with httpx.AsyncClient(timeout=300.0) as bg_client:
                        chat_resp = await bg_client.post(
                            f"{BACKEND_URL}/ops/threads/{captured_thread_id}/chat",
                            json={"content": message},
                            headers=captured_headers,
                        )
                        if chat_resp.status_code >= 400:
                            await _record_error(
                                bg_client,
                                f"HTTP {chat_resp.status_code}: {chat_resp.text[:300]}",
                            )
                except Exception as exc:
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as err_client:
                            await _record_error(
                                err_client,
                                f"{type(exc).__name__}: {str(exc)[:300]}",
                            )
                    except Exception:
                        pass

            # Keep a strong reference to prevent GC of the background task
            _task = asyncio.ensure_future(_background_chat())
            _BACKGROUND_CHAT_TASKS.add(_task)
            _task.add_done_callback(_BACKGROUND_CHAT_TASKS.discard)

            return (
                f"Chat dispatched (fire-and-return) on thread {thread_id}.\n"
                f"The agentic loop is running in the background — this tool does NOT "
                f"return the assistant response inline.\n"
                f"To poll: GET /ops/threads/{thread_id}. When the agent finishes, new "
                f"turns appear with agent_id='orchestrator'. On failure a turn with "
                f"agent_id='gimo_chat_error' is appended (item content begins with "
                f"'[gimo_chat error]').\n"
                f"Thread ID: {thread_id}"
            )

        except Exception as e:
            return f"gimo_chat error: {e}"

    # ── P2: Plan Approval Tools ───────────────────────────────────────────────

    @mcp.tool()
    async def gimo_approve_plan(thread_id: str) -> str:
        """Approve the proposed execution plan in the given thread.

        P2: The thread transitions to the executing workflow phase and begins running the approved plan.
        """
        from .bridge import _get_auth_token, BACKEND_URL
        import httpx

        try:
            token = _get_auth_token()
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{BACKEND_URL}/ops/threads/{thread_id}/plan/respond",
                    params={"action": "approve"},
                    json={"feedback": "Approved via MCP"},
                    headers=headers,
                )

                if resp.status_code != 200:
                    return f"Failed to approve plan: HTTP {resp.status_code} {resp.text[:200]}"

                result = resp.json()
                plan_id = result.get("plan_id", "")
            return f"✓ Plan approved. Execution started (plan_id: {plan_id}). Workflow phase: {result.get('workflow_phase', 'executing')}"

        except Exception as e:
            return f"gimo_approve_plan error: {e}"

    @mcp.tool()
    async def gimo_reject_plan(thread_id: str, feedback: str = "") -> str:
        """Reject the proposed plan and ask the agent to revise.

        P2: The thread transitions back to the planning workflow phase so the agent can revise the proposal.
        """
        from .bridge import _get_auth_token, BACKEND_URL
        import httpx

        try:
            token = _get_auth_token()
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{BACKEND_URL}/ops/threads/{thread_id}/plan/respond",
                    params={"action": "reject", "feedback": feedback or "Plan rejected. Please revise."},
                    headers=headers,
                )

                if resp.status_code != 200:
                    return f"Failed to reject plan: HTTP {resp.status_code} {resp.text[:200]}"

                result = resp.json()
            return f"✗ Plan rejected. Agent will revise. Workflow phase: {result.get('workflow_phase', 'planning')}"

        except Exception as e:
            return f"gimo_reject_plan error: {e}"

    @mcp.tool()
    async def gimo_generate_team_config(
        plan_id: str | None = None,
        objective: str | None = None,
    ) -> str:
        """Generate Claude Code Agent Teams config from a GIMO plan.

        Exactly one of ``plan_id`` or ``objective`` must be provided.

        - ``plan_id`` mode: Loads an existing draft/run and generates the team
          config from its content.
        - ``objective`` mode (R17): Creates a new draft from the free-text
          objective and materializes it before generating the team config.

        Args:
            plan_id: Existing plan/draft ID to generate team config from.
            objective: Free-text objective; a draft will be created and
                materialized.
        """
        try:
            import json
            from tools.gimo_server.services.agent_teams_service import AgentTeamsService
            from .bridge import proxy_to_api
            from .native_inputs import GenerateTeamConfigInput

            try:
                params = GenerateTeamConfigInput(plan_id=plan_id, objective=objective)
            except Exception as ve:
                return json.dumps({
                    "error": "Invalid arguments for gimo_generate_team_config",
                    "detail": str(ve),
                })

            # Objective mode (R17.1): delegate to the canonical backend
            # endpoint /ops/generate-plan, which is the SINGLE authoritative
            # path for structured plan materialization (validation,
            # canonicalization, CustomPlan registration). The bridge no
            # longer maintains a parallel pipeline.
            if params.objective is not None:
                create_result = await proxy_to_api(
                    "POST", "/ops/generate-plan",
                    __query={"prompt": params.objective},
                )
                if not isinstance(create_result, str) or not create_result.startswith("✅ Success"):
                    return json.dumps({
                        "error": "Failed to generate plan from objective via /ops/generate-plan",
                        "detail": (create_result or "")[:300],
                    })
                try:
                    body = create_result.split("\n", 1)[-1]
                    plan_id = json.loads(body).get("id")
                except (json.JSONDecodeError, ValueError, IndexError):
                    plan_id = None
                if not plan_id:
                    return json.dumps({
                        "error": "/ops/generate-plan returned no draft id",
                        "detail": create_result[:300],
                    })
            else:
                plan_id = params.plan_id

            # Load plan content via HTTP
            content = None
            draft_status: str | None = None
            draft_error: str | None = None
            if plan_id.startswith("r_"):
                result = await proxy_to_api("GET", f"/ops/runs/{plan_id}")
                try:
                    data = json.loads(result.split("\n", 1)[-1])
                    approved_id = data.get("approved_id", "")
                    if approved_id:
                        approved_result = await proxy_to_api("GET", f"/ops/approved/{approved_id}")
                        approved_data = json.loads(approved_result.split("\n", 1)[-1])
                        content = approved_data.get("content")
                except (json.JSONDecodeError, ValueError):
                    pass
            else:
                result = await proxy_to_api("GET", f"/ops/drafts/{plan_id}")
                try:
                    data = json.loads(result.split("\n", 1)[-1])
                    content = data.get("content")
                    draft_status = data.get("status")
                    draft_error = data.get("error")
                except (json.JSONDecodeError, ValueError):
                    pass
                # R17.1: any missing content here is a backend bug —
                # /ops/generate-plan is the canonical materialization path.
                # The bridge no longer maintains a parallel pipeline.

            if not content:
                # R17.2: surface the backend's real failure reason instead of
                # collapsing to a generic 'Plan not found or empty' message.
                # /ops/generate-plan persists the failure cause on the draft
                # (status='error', error='...'); the MCP client must reflect it.
                if draft_status == "error" or draft_error:
                    return json.dumps({
                        "error": draft_error or f"Plan generation failed for {plan_id}",
                        "draft_id": plan_id,
                        "draft_status": draft_status or "error",
                    })
                return json.dumps({"error": f"Plan not found or empty: {plan_id}"})

            try:
                plan_data = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError as parse_exc:
                return json.dumps({
                    "error": f"Plan content is not valid JSON for {plan_id}",
                    "detail": str(parse_exc),
                    "content_preview": str(content)[:200],
                })

            config = AgentTeamsService.generate_team_config(plan_data)
            return json.dumps(config, indent=2)
        except Exception as e:
            return f"Error generating team config: {e}"

    @mcp.tool()
    async def gimo_gics_model_reliability(model_id: str) -> str:
        """Get GICS reliability record for a specific model.

        Args:
            model_id: Model identifier (e.g. "claude-sonnet-4-6", "gpt-4o")
        """
        try:
            import json
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            result = SagpGateway.get_gics_insight(prefix=f"model:{model_id}", limit=50)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def gimo_gics_anomaly_report() -> str:
        """Get all models with active anomaly flags from GICS."""
        try:
            import json
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            result = SagpGateway.get_gics_insight(prefix="anomaly:", limit=100)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    logger.info("Registered Native Tools")
