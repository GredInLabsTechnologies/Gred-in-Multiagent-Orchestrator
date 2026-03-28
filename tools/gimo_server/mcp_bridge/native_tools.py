import time
import sys
import logging
from typing import Any
from mcp.server.fastmcp import FastMCP

# Keep original references for module loading and stat checking
_server_start_time = time.time()
logger = logging.getLogger("mcp_bridge.native_tools")

def register_native_tools(mcp: FastMCP):
    
    @mcp.tool()
    async def gimo_get_status() -> str:
        """Returns the current health status and basic system info of GIMO Engine."""
        try:
            from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService
            ollama_ok = await ProviderCatalogService._ollama_health()
            
            # Check backend port
            import socket
            backend_running = False
            try:
                with socket.create_connection(("127.0.0.1", 9325), timeout=0.5):
                    backend_running = True
            except:
                pass
                
            status = "RUNNING" if (ollama_ok or backend_running) else "STOPPED"
            details = []
            details.append(f"Engine: {status}")
            details.append(f"Ollama: {'CONNECTED' if ollama_ok else 'OFFLINE'}")
            details.append(f"Backend-API: {'UP' if backend_running else 'DOWN'}")
            
            return "\\n".join(details)
        except Exception as e:
            logger.error(f"gimo_get_status failed: {e}")
            return f"Error checking GIMO status: {e}"

    @mcp.tool()
    async def gimo_wake_ollama() -> str:
        """Attempts to start the local Ollama service if it is offline."""
        from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService
        success = await ProviderCatalogService.ensure_ollama_ready()
        if success:
            return "Ollama service is now ONLINE and ready."
        return "Failed to wake up Ollama. Check if it is installed and available in PATH."

    @mcp.tool()
    def gimo_start_engine() -> str:
        """
        Starts the GIMO backend (uvicorn on port 9325) and frontend (vite on port 5173).
        LOCAL_ONLY. Do not expose to external networks.
        """
        import socket, subprocess, sys, secrets
        from pathlib import Path

        def _is_port_open(port: int) -> bool:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return True
            except OSError:
                return False

        root = Path(__file__).resolve().parents[3]
        report = []

        python_exe = sys.executable
        for p in [".venv", "venv", "env"]:
            candidate = root / p / "Scripts" / "python.exe"
            if candidate.exists():
                python_exe = str(candidate)
                break
                
        env_file = root / ".env"
        env_content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
            
        token = None
        for line in env_content.splitlines():
            if line.startswith("ORCH_TOKEN="):
                token = line.split("=", 1)[1]
        
        if not token:
            token = secrets.token_hex(32)
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"\\nORCH_PORT=9325\\nORCH_TOKEN={token}\\n")
            ui_env = root / "tools" / "orchestrator_ui" / ".env.local"
            ui_env.parent.mkdir(parents=True, exist_ok=True)
            with open(ui_env, "w", encoding="utf-8") as f:
                f.write(f"VITE_ORCH_TOKEN={token}\\n")

        if _is_port_open(9325):
            report.append("✅ Backend: already running on 127.0.0.1:9325")
        else:
            try:
                subprocess.Popen(
                    [python_exe, "-m", "uvicorn", "tools.gimo_server.main:app", "--host", "127.0.0.1", "--port", "9325", "--log-level", "info"],
                    cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                )
                report.append("🚀 Backend: spawned uvicorn on 127.0.0.1:9325")
            except Exception as e:
                report.append(f"❌ Backend: failed to start — {e}")

        frontend_dir = root / "tools" / "orchestrator_ui"
        if _is_port_open(5173):
            report.append("✅ Frontend: already running on 127.0.0.1:5173")
        elif not frontend_dir.exists():
            report.append(f"⚠ Frontend: directory not found at {frontend_dir}")
        else:
            try:
                subprocess.Popen(
                    ["npm", "run", "dev", "--", "--host", "127.0.0.1"],
                    cwd=str(frontend_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, shell=True,  # nosec B602
                )
                report.append("🚀 Frontend: spawned vite on 127.0.0.1:5173")
            except Exception as e:
                report.append(f"❌ Frontend: failed to start — {e}")

        report.append("\\nOpen: http://127.0.0.1:5173 (allow ~5s for processes to boot)")
        return "\\n".join(report)

    @mcp.tool()
    def gimo_get_server_info() -> str:
        """Returns diagnostics for MCP bridge and staleness."""
        import hashlib, importlib
        from pathlib import Path
        from datetime import datetime, timezone

        uptime_s = int(time.time() - _server_start_time)
        started_at = datetime.fromtimestamp(_server_start_time, tz=timezone.utc).isoformat()
        
        # We need to reach into server.py to check worker
        from tools.gimo_server.mcp_bridge import server
        worker_running = getattr(server, "_active_run_worker", None) is not None

        module_keys = [
            "tools.gimo_server.services.run_worker",
            "tools.gimo_server.mcp_bridge.server",
            "tools.gimo_server.services.provider_service",
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
                    lines.append(f"  {mod_name.split('.')[-1]}: {p}\\n    mtime={int(disk_mtime)} hash={disk_hash} [{stale}]")
            except Exception as e:
                lines.append(f"  {mod_name.split('.')[-1]}: error → {e}")

        return "\\n".join(lines)

    @mcp.tool()
    async def gimo_reload_worker() -> str:
        """Hot-reloads the RunWorker module without restarting the MCP server process."""
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

        return "\\n".join(steps) + "\\n🚀 GIMO RunWorker hot-reloaded successfully."

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

    async def _generate_plan_for_task(task_instructions: str):
        from tools.gimo_server.services.provider_service import ProviderService
        from tools.gimo_server.ops_models import OpsPlan
        import json, time, re

        sys_prompt = (
            "You are a senior systems architect. Generate a JSON execution plan.\n"
            "RULES:\n"
            "- tasks[0] MUST have role 'Lead Orchestrator' with scope 'bridge'\n"
            "- Each worker task must have a unique id, title, description, and agent_assignee\n"
            "- agent_assignee must have: role, goal, backstory, model, system_prompt, instructions\n"
            "- Output ONLY valid JSON, no markdown, no explanations\n\n"
            f"Task: {task_instructions}\n\n"
            'JSON schema:\n'
            '{"id":"plan_...","title":"...","workspace":"...","created":"...","objective":"...",'
            '"tasks":[{"id":"t_orch","title":"[ORCH] ...","scope":"bridge","depends":[],"status":"pending",'
            '"description":"...","agent_assignee":{"role":"Lead Orchestrator","goal":"...","backstory":"...",'
            '"model":"qwen2.5-coder:3b","system_prompt":"...","instructions":["..."]}},'
            '{"id":"t_worker_1","title":"[WORKER] ...","scope":"file_write","depends":["t_orch"],'
        )
        try:
            response = await ProviderService.static_generate(prompt=sys_prompt, context={"task_type": "disruptive_planning"})
            raw = response.get("content", "").strip()
            # Strip markdown fences
            raw = re.sub(r"```(?:json)?\s*\n?", "", raw).strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()
            # Find first { to last }
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start:end + 1]
            parsed = json.loads(raw)
            return OpsPlan.model_validate(parsed)
        except Exception as exc:
            logger.error("Plan generation failed: %s", exc, exc_info=True)
            from datetime import datetime
            return OpsPlan(id=f"plan_{int(time.time())}", title="[FALLBACK] Plan", workspace="", created=datetime.now().isoformat(), objective=task_instructions, tasks=[], constraints=[])

    @mcp.tool()
    async def gimo_propose_structured_plan(task_instructions: str) -> str:
        """Generates a structured multi-step plan with task dependencies and Mermaid graph."""
        try:
            from tools.gimo_server.services.ops_service import OpsService
            from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService
            plan_data = await _generate_plan_for_task(task_instructions)
            graph = _generate_mermaid_graph(plan_data)
            draft = OpsService.create_draft(
                prompt=task_instructions,
                content=TaskDescriptorService.canonicalize_plan_content(plan_data),
                context={"structured": True, "mermaid": graph},
                provider="mcp_planner",
            )
            return f"🚀 Plan propuesto (Draft: {draft.id}):\\n```mermaid\\n{graph}\\n```"
        except Exception as e: return f"Error: {e}"

    @mcp.tool()
    async def gimo_create_draft(task_instructions: str, target_agent_id: str = "auto") -> str:
        """Creates an Ops Draft based on task instructions with Mermaid planning"""
        try:
            from tools.gimo_server.services.ops_service import OpsService
            from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService
            plan_data = await _generate_plan_for_task(task_instructions)
            graph = _generate_mermaid_graph(plan_data)
            draft = OpsService.create_draft(
                prompt=task_instructions,
                content=TaskDescriptorService.canonicalize_plan_content(plan_data),
                context={"structured": True, "mermaid": graph},
                provider="mcp",
            )
            return f"Draft: {draft.id}\\n```mermaid\\n{graph}\\n```"
        except Exception as e: return str(e)

    @mcp.tool()
    async def gimo_run_task(task_instructions: str, target_agent_id: str = "auto") -> str:
        """Automatically create and execute a whole plan based on instructions."""
        try:
            from tools.gimo_server.services.ops_service import OpsService
            from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService
            plan_data = await _generate_plan_for_task(task_instructions)
            graph = _generate_mermaid_graph(plan_data)
            draft = OpsService.create_draft(
                prompt=task_instructions,
                content=TaskDescriptorService.canonicalize_plan_content(plan_data),
                context={"structured": True, "mermaid": graph},
                provider="mcp_auto",
            )
            appr = OpsService.approve_draft(draft.id, approved_by="auto")
            run = OpsService.create_run(appr.id)
            return f"Running. Run ID: {run.id}\\nPlan:\\n```mermaid\\n{graph}\\n```"
        except Exception as e: return str(e)

    @mcp.tool()
    def gimo_resolve_handover(run_id: str, decision: str, edited_state: dict = None) -> str:
        """Resume a blocked run after human intervention/handover decision."""
        try:
            from tools.gimo_server.services.ops_service import OpsService
            OpsService.update_run_status(run_id, "running", msg=f"Resolved: {decision}")
            return "OK"
        except Exception as e: return str(e)

    @mcp.tool()
    def gimo_get_draft(draft_id: str) -> str:
        """Returns the raw plan content for a given draft."""
        try:
            from tools.gimo_server.services.ops_service import OpsService
            draft = OpsService.get_draft(draft_id)
            return draft.content if draft else "Not found"
        except Exception as e: return str(e)

    @mcp.tool()
    def gimo_approve_draft(draft_id: str) -> str:
        """Veto/Approve a draft. This generates a concrete Run."""
        try:
            from tools.gimo_server.services.ops_service import OpsService
            approved = OpsService.approve_draft(draft_id, approved_by="human")
            run = OpsService.create_run(approved.id)
            return f"Approved. Run: {run.id}"
        except Exception as e: return str(e)

    @mcp.tool()
    def gimo_get_task_status(run_id: str) -> str:
        """Check if a run is pending, running, or done."""
        try:
            from tools.gimo_server.services.ops_service import OpsService
            run = OpsService.get_run(run_id)
            return f"Status: {run.status}" if run else "Not found"
        except Exception as e: return str(e)

    @mcp.tool()
    def gimo_get_plan_graph(draft_or_run_id: str) -> str:
        """Returns the Mermaid graph visualization for a draft or run."""
        try:
            from tools.gimo_server.services.ops_service import OpsService
            content = None
            if draft_or_run_id.startswith("r_"):
                run = OpsService.get_run(draft_or_run_id)
                if run:
                    approved = OpsService.get_approved(run.approved_id)
                    content = approved.content if approved else None
            else:
                draft = OpsService.get_draft(draft_or_run_id)
                content = draft.content if draft else None
            if not content: return f"No plan found for {draft_or_run_id}"
            graph = _generate_mermaid_graph(content)
            return f"```mermaid\\n{graph}\\n```"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def gimo_spawn_subagent(name: str, task: str, role: str = "worker") -> str:
        try:
            from tools.gimo_server.services.sub_agent_manager import SubAgentManager
            req = {"modelPreference": "default", "constraints": {"role": role, "task": task}}
            agent = await SubAgentManager.create_sub_agent(parent_id="mcp", request=req)
            return f"Spawned: {agent.id}"
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
        """Send a message to GIMO's agentic chat and get a response with tool execution.

        P2: Enhanced with conversational planning. If the agent proposes a plan or asks
        a question, the response will include that information.

        Creates a new thread if thread_id is empty.
        Returns the assistant response, tool calls, and any pending actions (questions/plans).
        """
        from .bridge import proxy_to_api, _get_auth_token, BACKEND_URL
        import httpx
        import json

        try:
            token = _get_auth_token()
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            async with httpx.AsyncClient(timeout=300.0) as client:
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

                # Send chat message
                resp = await client.post(
                    f"{BACKEND_URL}/ops/threads/{thread_id}/chat",
                    params={"content": message},
                    headers=headers,
                )

                if resp.status_code != 200:
                    return f"Chat failed: HTTP {resp.status_code} {resp.text[:200]}"

                result = resp.json()
                response_text = result.get("response", "")
                tool_calls = result.get("tool_calls", [])
                usage = result.get("usage", {})
                finish_reason = result.get("finish_reason", "stop")

                # P2: Check thread state for pending actions
                thread_resp = await client.get(
                    f"{BACKEND_URL}/ops/threads/{thread_id}",
                    headers=headers,
                )
                thread_state = thread_resp.json() if thread_resp.status_code == 200 else {}
                proposed_plan = thread_state.get("proposed_plan")
                mood = thread_state.get("mood", "neutral")

                # Format output
                parts = [f"Thread: {thread_id} | Mood: {mood}"]
                if tool_calls:
                    parts.append(f"\nTool calls ({len(tool_calls)}):")
                    for tc in tool_calls:
                        status_icon = "+" if tc.get("status") == "success" else "x"
                        parts.append(f"  [{status_icon}] {tc.get('name', '?')} ({tc.get('risk', 'LOW')}) {tc.get('duration', 0):.1f}s")

                parts.append(f"\nResponse:\n{response_text}")

                # P2: Indicate pending actions
                if finish_reason == "user_question":
                    parts.append("\n[AWAITING USER ANSWER] Send another message to continue.")
                elif finish_reason == "plan_proposed" and proposed_plan:
                    plan_title = proposed_plan.get("title", "Execution Plan")
                    task_count = len(proposed_plan.get("tasks", []))
                    parts.append(f"\n[PLAN PROPOSED] {plan_title} ({task_count} tasks)")
                    parts.append("Use gimo_approve_plan() to approve or gimo_reject_plan() to reject.")

                tokens = usage.get("total_tokens", 0)
                cost = usage.get("cost_usd", 0)
                if tokens:
                    parts.append(f"\n[{tokens:,} tokens | ${cost:.4f}]")

                return "\n".join(parts)

        except Exception as e:
            return f"gimo_chat error: {e}"

    # ── P2: Plan Approval Tools ───────────────────────────────────────────────

    @mcp.tool()
    async def gimo_approve_plan(thread_id: str) -> str:
        """Approve the proposed execution plan in the given thread.

        P2: The agent will transition to executor mood and begin executing the plan.
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

        P2: The agent will transition back to dialoger mood and revise the plan based on feedback.
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

    logger.info("Registered Native Tools")
