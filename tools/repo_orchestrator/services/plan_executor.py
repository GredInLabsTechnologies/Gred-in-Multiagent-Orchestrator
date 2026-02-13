"""
PlanExecutor -- Parallel task orchestration engine for GIMO.

Resolves task dependency graphs, identifies parallelizable groups,
and executes them concurrently via asyncio.gather.
"""
import asyncio
import logging
from typing import Dict, List, Optional
from collections import defaultdict

from tools.repo_orchestrator.models import Plan, PlanTask, DelegationRequest

logger = logging.getLogger("orchestrator.plan_executor")


class PlanExecutor:

    @staticmethod
    def resolve_parallel_groups(tasks: List[PlanTask]) -> List[List[PlanTask]]:
        """
        Topological sort with level grouping.
        Returns a list of groups, where each group contains tasks
        that can run in parallel (all dependencies satisfied by prior groups).
        """
        task_map: Dict[str, PlanTask] = {t.id: t for t in tasks}
        in_degree: Dict[str, int] = {t.id: 0 for t in tasks}
        dependents: Dict[str, List[str]] = defaultdict(list)

        for task in tasks:
            for dep_id in task.dependencies:
                if dep_id in task_map:
                    in_degree[task.id] += 1
                    dependents[dep_id].append(task.id)

        groups: List[List[PlanTask]] = []
        ready = [tid for tid, deg in in_degree.items() if deg == 0]

        while ready:
            group = [task_map[tid] for tid in ready]
            groups.append(group)

            next_ready = []
            for tid in ready:
                for dep_tid in dependents[tid]:
                    in_degree[dep_tid] -= 1
                    if in_degree[dep_tid] == 0:
                        next_ready.append(dep_tid)
            ready = next_ready

        return groups

    @classmethod
    async def execute_plan(cls, plan: Plan) -> Dict:
        """
        Execute a plan by resolving dependency groups and running each group
        in parallel via asyncio.gather.
        """
        from tools.repo_orchestrator.services.plan_service import PlanService
        from tools.repo_orchestrator.services.sub_agent_manager import SubAgentManager
        from tools.repo_orchestrator.models import PlanUpdateRequest

        # Mark plan as executing
        await PlanService.update_plan(plan.id, PlanUpdateRequest(status="executing"))

        groups = cls.resolve_parallel_groups(plan.tasks)
        results: Dict[str, str] = {}

        try:
            for group_idx, group in enumerate(groups):
                logger.info(f"Plan {plan.id}: executing group {group_idx + 1}/{len(groups)} "
                            f"({len(group)} tasks in parallel)")

                # Mark tasks as running
                for task in group:
                    task.status = "running"

                # Broadcast updated plan state
                await PlanService.update_plan(plan.id, PlanUpdateRequest())

                # Launch all tasks in this group in parallel
                coros = [
                    cls._execute_single_task(plan, task, SubAgentManager)
                    for task in group
                ]
                group_results = await asyncio.gather(*coros, return_exceptions=True)

                # Process results
                for task, result in zip(group, group_results):
                    if isinstance(result, Exception):
                        task.status = "failed"
                        results[task.id] = f"ERROR: {result}"
                        logger.error(f"Task {task.id} failed: {result}")
                    else:
                        task.status = "done"
                        results[task.id] = result
                        logger.info(f"Task {task.id} completed successfully")

                # Check for failures -- if any task failed, mark plan as failed
                if any(t.status == "failed" for t in group):
                    await PlanService.update_plan(plan.id, PlanUpdateRequest(status="failed"))
                    return {"status": "failed", "results": results, "failed_group": group_idx}

            # All groups completed successfully
            await PlanService.update_plan(plan.id, PlanUpdateRequest(status="completed"))
            return {"status": "completed", "results": results}

        except Exception as e:
            logger.error(f"Plan {plan.id} execution error: {e}")
            await PlanService.update_plan(plan.id, PlanUpdateRequest(status="failed"))
            return {"status": "failed", "error": str(e), "results": results}

    @classmethod
    async def _execute_single_task(cls, plan: Plan, task: PlanTask, manager) -> str:
        """Execute a single plan task by delegating to a sub-agent."""
        # Find which agent is assigned to this task
        assigned_agent = None
        for assignment in plan.assignments:
            if task.id in assignment.taskIds:
                assigned_agent = assignment.agentId
                break

        agent_id = assigned_agent or "api"

        # Create a sub-agent for this task
        req = DelegationRequest(
            subTaskDescription=f"[{task.title}] {task.description}",
            modelPreference="llama3",
        )
        sub_agent = await manager.create_sub_agent(agent_id, req)

        # Execute the task
        result = await manager.execute_task(sub_agent.id, task.description)
        return result

    @classmethod
    async def delegate_batch(cls, parent_id: str, requests: List[DelegationRequest]) -> List:
        """
        Delegate multiple tasks to sub-agents in parallel.
        Each request creates a sub-agent and immediately starts execution.
        """
        from tools.repo_orchestrator.services.sub_agent_manager import SubAgentManager

        async def create_and_execute(req: DelegationRequest):
            agent = await SubAgentManager.create_sub_agent(parent_id, req)
            result = await SubAgentManager.execute_task(agent.id, req.subTaskDescription)
            return {"agent_id": agent.id, "result": result, "status": "completed"}

        coros = [create_and_execute(req) for req in requests]
        results = await asyncio.gather(*coros, return_exceptions=True)

        output = []
        for req, result in zip(requests, results):
            if isinstance(result, Exception):
                output.append({
                    "task": req.subTaskDescription,
                    "status": "failed",
                    "error": str(result)
                })
            else:
                output.append(result)

        return output
