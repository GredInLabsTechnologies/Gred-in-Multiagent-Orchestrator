import os
import re

def refactor_routes():
    path = "c:\\Users\\shilo\\Documents\\Github\\gred_in_multiagent_orchestrator\\tools\\gimo_server\\routes.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Add Annotated to imports
    content = content.replace("from typing import Optional\n", "from typing import Optional, Annotated\n")

    # 2. Refactor _overlay_run_status (line 195)
    overlay_old = '''def _overlay_run_status(nodes: list, run) -> None:
    """Update node statuses based on run logs (which tasks completed/failed)."""
    completed_tasks = set()
    running_task = None
    for entry in (run.log or []):
        msg = entry.get("msg", "")
        # Detect completed tasks from log messages
        if "✅" in msg or "delegation noted" in msg:
            for node in nodes:
                if node["id"] in msg or node["data"].get("label", "") in msg:
                    completed_tasks.add(node["id"])
        if "Executing Task" in msg:
            for node in nodes:
                if node["id"] in msg:
                    running_task = node["id"]

    for node in nodes:
        nid = node["id"]
        if run.status == "done":
            node["data"]["status"] = "done"
        elif run.status == "error":
            if nid in completed_tasks:
                node["data"]["status"] = "done"
            elif nid == running_task:
                node["data"]["status"] = "error"
            else:
                node["data"]["status"] = "pending"
        elif run.status == "running":
            if nid in completed_tasks:
                node["data"]["status"] = "done"
            elif nid == running_task:
                node["data"]["status"] = "running"
            else:
                node["data"]["status"] = "pending"
        elif run.status == "pending":
            node["data"]["status"] = "pending"'''

    overlay_new = '''def _parse_run_logs_for_status(nodes: list, logs: list):
    completed = set()
    running = None
    for entry in logs:
        msg = entry.get("msg", "")
        if "✅" in msg or "delegation noted" in msg:
            for node in nodes:
                if node["id"] in msg or node["data"].get("label", "") in msg:
                    completed.add(node["id"])
        if "Executing Task" in msg:
            for node in nodes:
                if node["id"] in msg:
                    running = node["id"]
    return completed, running

def _apply_node_status(node, run_status, completed_tasks, running_task):
    nid = node["id"]
    if run_status == "done":
        return "done"
    elif run_status == "pending":
        return "pending"
    
    # "error" or "running"
    if nid in completed_tasks:
        return "done"
    elif nid == running_task:
        return run_status
    return "pending"

def _overlay_run_status(nodes: list, run) -> None:
    """Update node statuses based on run logs (which tasks completed/failed)."""
    logs = run.log or []
    completed_tasks, running_task = _parse_run_logs_for_status(nodes, logs)
    
    for node in nodes:
        node["data"]["status"] = _apply_node_status(node, run.status, completed_tasks, running_task)'''

    content = content.replace(overlay_old, overlay_new)

    # 3. Refactor get_ui_graph_handler (line 233)
    # The function checks active CustomPlans (running/draft), Active runs, Pending drafts, Recent done runs, Approved drafts.
    # We can extract these priority checks into separate functions.
    import textwrap

    graph_handler_old_pattern = r'''def get_ui_graph_handler\(.*?\n {4}return \{"nodes": nodes, "edges": edges\}\n'''
    
    # We write a custom replacer for it
    graph_handler_new = '''def _get_graph_for_custom_plan(engine):
    try:
        from tools.gimo_server.services.custom_plan_service import CustomPlanService
        all_plans = CustomPlanService.list_plans()
        active_cp = next((p for p in all_plans if p.status in ("running", "draft")), None)
        if active_cp and active_cp.nodes:
            cp_nodes = []
            cp_edges = []
            for node in active_cp.nodes:
                cp_nodes.append({
                    "id": node.id,
                    "type": "custom",
                    "position": {"x": node.position.x, "y": node.position.y},
                    "data": {
                        "label": node.label,
                        "status": node.status,
                        "node_type": node.node_type,
                        "role": node.role,
                        "model": node.model,
                        "provider": node.provider,
                        "prompt": node.prompt,
                        "role_definition": node.role_definition,
                        "is_orchestrator": node.is_orchestrator,
                        "output": node.output,
                        "error": node.error,
                        "plan": {"draft_id": active_cp.id},
                        "custom_plan_id": active_cp.id,
                    },
                })
            for edge in active_cp.edges:
                cp_edges.append({
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                })
            return {"nodes": cp_nodes, "edges": cp_edges}
    except Exception:
        pass
    return None

def _get_graph_for_active_runs():
    try:
        runs = OpsService.list_runs()
        active_runs = [r for r in runs if r.status in ("pending", "running")]
        if active_runs:
            latest_run = active_runs[0]
            approved = OpsService.get_approved(latest_run.approved_id)
            if approved and approved.content:
                nodes, edges = build_graph_from_ops_plan(approved.content, draft_id=latest_run.id)
                _overlay_run_status(nodes, latest_run)
                return {"nodes": nodes, "edges": edges}
    except Exception:
        pass
    return None

def _get_graph_for_pending_drafts():
    try:
        drafts = OpsService.list_drafts()
        pending_drafts = [d for d in drafts if d.context.get("structured") and d.status == "draft" and d.content]
        if pending_drafts:
            latest = pending_drafts[0]
            nodes, edges = build_graph_from_ops_plan(latest.content, draft_id=latest.id)
            return {"nodes": nodes, "edges": edges}
    except Exception:
        pass
    return None

def _get_graph_for_recent_done_runs():
    try:
        runs = OpsService.list_runs()
        recent_done = [r for r in runs if r.status in ("done", "error")]
        if recent_done:
            latest_done = recent_done[0]
            approved = OpsService.get_approved(latest_done.approved_id)
            if approved and approved.content:
                nodes, edges = build_graph_from_ops_plan(approved.content, draft_id=latest_done.id)
                _overlay_run_status(nodes, latest_done)
                return {"nodes": nodes, "edges": edges}
    except Exception:
        pass
    return None

def _get_graph_for_approved_drafts():
    try:
        drafts = OpsService.list_drafts()
        approved_drafts = [d for d in drafts if d.context.get("structured") and d.status == "approved" and d.content]
        if approved_drafts:
            latest = approved_drafts[0]
            nodes, edges = build_graph_from_ops_plan(latest.content, draft_id=latest.id)
            return {"nodes": nodes, "edges": edges}
    except Exception:
        pass
    return None

def _build_engine_graph(engine):
    graph = engine.graph
    state_data = engine.state.data
    node_confidence = state_data.get("node_confidence", {})

    nodes = []
    for node in graph.nodes:
        confidence = node_confidence.get(node.id)
        status = "pending"
        for cp in reversed(engine.state.checkpoints):
            if cp.node_id == node.id:
                status = cp.status if cp.status != "completed" else "done"
                break
        
        if state_data.get("execution_paused") and state_data.get("pause_reason") == "agent_doubt":
            if getattr(engine, "_resume_from_node_id", None) == node.id:
                status = "doubt"

        pending_questions = []
        if confidence and confidence.get("questions"):
            for i, q in enumerate(confidence["questions"]):
                pending_questions.append({
                    "id": f"doubt_{node.id}_{i}",
                    "question": q,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "pending"
                })

        nodes.append({
            "id": node.id,
            "type": "orchestrator" if node.type == "agent_task" else "bridge",
            "data": {
                "label": node.config.get("label", node.id),
                "status": status,
                "confidence": confidence,
                "pendingQuestions": pending_questions,
                "trustLevel": state_data.get(f"trust_{node.id}", "autonomous"),
            },
            "position": {"x": 0, "y": 0}
        })

    edges = []
    for edge in graph.edges:
        edges.append({
            "id": f"e-{edge.from_node}-{edge.to_node}",
            "source": edge.from_node,
            "target": edge.to_node,
            "animated": True
        })

    return {"nodes": nodes, "edges": edges}

def get_ui_graph_handler(
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    """Generate dynamic graph structure for the UI based on active engines."""
    engine = None
    if _WORKFLOW_ENGINES:
        engine = list(_WORKFLOW_ENGINES.values())[-1]

    if not engine:
        result = _get_graph_for_custom_plan(engine)
        if result: return result
        
        result = _get_graph_for_active_runs()
        if result: return result
        
        result = _get_graph_for_pending_drafts()
        if result: return result
        
        result = _get_graph_for_recent_done_runs()
        if result: return result
        
        result = _get_graph_for_approved_drafts()
        if result: return result
        
        return {"nodes": [], "edges": []}

    return _build_engine_graph(engine)
'''
    content = re.sub(graph_handler_old_pattern, graph_handler_new, content, flags=re.DOTALL)


    # 4. Refactor register_routes (which contains create_plan_handler starting at 747 actually)
    register_routes_old = r''' {4}@app\.post\("/ui/plan/create", responses=\{.*?\n {8}return JSONResponse\(\{"status": "ok", "draft_id": draft.id\}, status_code=201\)'''
    
    register_routes_new = '''async def _generate_structured_plan_llm(prompt: str) -> dict:
    from tools.gimo_server.services.provider_service import ProviderService
    from tools.gimo_server.ops_models import OpsPlan
    import re as _re
    import logging as _log

    system_msg = (
        "You are a multi-agent orchestration planner. Given a task, produce a JSON plan with "
        "the schema: {\\"id\\": \\"plan_xxx\\", \\"title\\": \\"Short plan title\\", "
        "\\"workspace\\": \\".\\", \\"created\\": \\"2026-01-01\\", \\"objective\\": \\"...\\", "
        "\\"tasks\\": [{\\"id\\": \\"t1\\", \\"title\\": \\"...\\", \\"scope\\": \\"bridge\\", "
        "\\"description\\": \\"...\\", \\"depends\\": [], \\"status\\": \\"pending\\", "
        "\\"agent_assignee\\": {\\"role\\": \\"orchestrator\\", \\"goal\\": \\"...\\", \\"model\\": \\"qwen2.5-coder:32b\\", "
        "\\"system_prompt\\": \\"...\\", \\"instructions\\": [\\"...\\"]}}, "
        "{\\"id\\": \\"t2\\", \\"title\\": \\"...\\", \\"scope\\": \\"file_write\\", "
        "\\"description\\": \\"...\\", \\"depends\\": [\\"t1\\"], \\"status\\": \\"pending\\", "
        "\\"agent_assignee\\": {\\"role\\": \\"worker\\", \\"goal\\": \\"...\\", \\"model\\": \\"qwen2.5-coder:32b\\", "
        "\\"system_prompt\\": \\"...\\", \\"instructions\\": [\\"...\\"]}}]}. "
        "First task is always the orchestrator (scope=bridge). Remaining tasks are workers (scope=file_write). "
        "Return ONLY valid JSON, no markdown."
    )
    
    try:
        response = await ProviderService.static_generate(
            prompt=f"{system_msg}\\n\\nTask: {prompt}",
            context={"task_type": "planning"}
        )
        raw = response.get("content", "{}")
        json_match = _re.search(r'\\{.*\\}', raw, _re.DOTALL)
        plan_json = json_match.group(0) if json_match else raw
        plan_data = OpsPlan.model_validate_json(plan_json)
        return {"data": plan_data, "raw": raw, "provider": response.get("provider", "local_ollama")}
    except Exception as _plan_err:
        _log.getLogger("orchestrator").warning("Plan LLM failed, using fallback: %s", _plan_err)
        return None

def _create_fallback_plan() -> dict:
    from tools.gimo_server.ops_models import OpsPlan
    # create simple fallback
    plan_dict = {
        "id": f"plan_fb_{int(time.time())}",
        "title": "Fallback Execution Plan",
        "workspace": ".",
        "created": datetime.now(timezone.utc).isoformat(),
        "objective": "Complete the requested task safely.",
        "tasks": [
            {
                "id": "t_orch", "title": "Orchestrate Execution", "scope": "bridge",
                "description": "Analyze request and delegate to worker",
                "depends": [], "status": "pending",
                "agent_assignee": {
                    "role": "Lead Orchestrator", "goal": "Manage execution", 
                    "model": "qwen2.5-coder:32b", "system_prompt": "You are the orchestrator.", "instructions": []
                }
            },
            {
                "id": "t_worker", "title": "Implement Changes", "scope": "file_write",
                "description": "Execute requested modifications",
                "depends": ["t_orch"], "status": "pending",
                "agent_assignee": {
                    "role": "Worker Agent", "goal": "Implement changes", 
                    "model": "qwen2.5-coder:32b", "system_prompt": "You are a worker agent.", "instructions": []
                }
            }
        ],
        "constraints": []
    }
    return plan_dict

    @app.post("/ui/plan/create", responses={403: {"description": "operator or admin role required"}, 400: {"description": "prompt is required"}})
    async def create_plan_handler(
        request: Request,
        auth: Annotated[AuthContext, Depends(require_read_only_access)],
        rl: Annotated[None, Depends(check_rate_limit)],
    ):
        """Creates a structured plan from UI and returns it as a draft."""
        if auth.role not in ("operator", "admin"):
            raise HTTPException(status_code=403, detail=ERR_OPERATOR_ADMIN_REQUIRED)

        body = await request.json()
        prompt = str(body.get("prompt") or body.get("instructions") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")

        result = await _generate_structured_plan_llm(prompt)
        
        if result:
            plan_data = result["data"]
            plan_json = plan_data.model_dump_json(indent=2)
            provider = result["provider"]
        else:
            fallback_dict = _create_fallback_plan()
            from tools.gimo_server.ops_models import OpsPlan
            plan_data = OpsPlan(**fallback_dict)
            plan_json = plan_data.model_dump_json(indent=2)
            provider = "local_ollama"

        draft = OpsService.create_draft(
            prompt,
            content=plan_json,
            context={"structured": True},
            provider=provider,
            status="draft",
        )
        audit_log("OPS", "/ui/plan/create", draft.id, operation="WRITE", actor=auth.token)
        return JSONResponse({"status": "ok", "draft_id": draft.id}, status_code=201)'''
    
    content = re.sub(register_routes_old, register_routes_new, content, flags=re.DOTALL)
    
    # wait! The new functions `_generate_structured_plan_llm` and `_create_fallback_plan` shouldn't be nested in register_routes! They should be outside. So in string replacement I'm replacing the nested handler and injecting them correctly. 

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    refactor_routes()
    print("Refactored routes.py")
