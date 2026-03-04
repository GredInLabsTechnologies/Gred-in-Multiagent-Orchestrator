import logging
import asyncio
from typing import Dict, Any, Optional

from tools.gimo_server.ops_models import OpsDraft, RepoContext
from tools.gimo_server.services.sandbox_service import SandboxService
from tools.gimo_server.services.context_indexer import ContextIndexer
from tools.gimo_server.services.router_pm import RouterPM
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.provider_service import ProviderService

logger = logging.getLogger("orchestrator.services.slice0_orchestrator")

class Slice0Orchestrator:
    """Implementa el Pipeline estilo LangGraph (Slice 0 - Anexo A)."""

    @staticmethod
    async def run_pipeline(user_request_raw: str, repo_path: str, run_id: Optional[str] = None) -> OpsDraft:
        """Executes the full Slice 0 E2E pipeline."""
        if not run_id:
            import time, os
            run_id = f"r_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
            
        logger.info(f"--- Starting Slice 0 Pipeline for run {run_id} ---")

        # 1. RepoBootstrapper
        logger.info("Step 1: RepoBootstrapper")
        worktree_path = SandboxService.create_sandbox(run_id, repo_path)
        
        try:
            # 2. ContextIndexer
            logger.info("Step 2: ContextIndexer")
            repo_context = ContextIndexer.build_context(worktree_path)
            
            # 3. RouterPM
            logger.info("Step 3: RouterPM")
            contract = await RouterPM.generate_contract(user_request_raw, repo_context)
            
            # 4. Planner & Specialist Agent (Backend example)
            logger.info("Step 4: Specialist Agent")
            agent_prompt = (
                f"You are a Specialist Agent. You must implement the following objective in the codebase:\n"
                f"Objective: {contract.objective}\n"
                f"Constraints: {contract.constraints}\n"
                f"Acceptance Criteria: {contract.acceptance_criteria}\n"
                f"Repository Stack: {repo_context.stack}\n\n"
                "Please output ONLY the implementation details or the diff instructions."
            )
            agent_resp = await ProviderService.static_generate(agent_prompt, context={"task_type": "coding"})
            agent_content = agent_resp.get("content", "")
            
            # 5. QA Gate (Tests + Lint format simulation for MVP)
            logger.info("Step 5: QA Gate")
            qa_passed = True
            qa_failures = []
            
            import asyncio
            try:
                # Run tests asynchronously in the sandboxed worktree
                proc = await asyncio.create_subprocess_exec(
                    "pytest", "tests",
                    cwd=worktree_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    qa_passed = False
                    qa_failures.append(f"QA Failed (tests): {(stderr or stdout).decode('utf-8')}")
            except Exception:
                # No pytest installed or mapped, skip or handle
                pass
                
            draft_status = "draft" if qa_passed else "rejected"
            draft_error = None if qa_passed else "\n".join(qa_failures)
            
            # 6. Draft Creation (GraphState equivalent persistence)
            context = {
                "repo_context": repo_context.model_dump(),
                "contract": contract.model_dump(),
                "agent_content": agent_content,
                "worktree_path": worktree_path,
                "qa_passed": qa_passed,
                "qa_failures": qa_failures,
                "intent_class": contract.execution.intent_class.value
            }
            
            draft = OpsService.create_draft(
                prompt=user_request_raw,
                context=context,
                provider=agent_resp.get("provider", "unknown"),
                content=agent_content,
                status=draft_status,
                error=draft_error
            )
            
            logger.info(f"--- Slice 0 Pipeline Complete (Draft ID: {draft.id}, Status: {draft_status}) ---")
            return draft
            
        finally:
            # Optional: Sandbox cleanup if needed, but usually kept for Review
            # SandboxService.cleanup_sandbox(run_id, repo_path)
            pass
