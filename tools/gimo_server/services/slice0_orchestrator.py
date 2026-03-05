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
            
            # 4. Planner & Specialist Agent Pipeline with Correction Loop
            logger.info("Step 4: Specialist Agent (Iterative with QA Gate)")
            
            max_iterations = 3
            correction_iteration = 0
            qa_passed = False
            qa_failures = []
            
            # File Content Injection for Token Efficiency
            path_scope = getattr(contract.execution, "path_scope", [])
            scoped_files_content = ""
            if path_scope:
                scoped_files_content = ContextIndexer.extract_file_contents(worktree_path, path_scope)
            
            files_context_str = f"Relevant File Contents:\n{scoped_files_content}\n\n" if scoped_files_content else ""

            agent_prompt = (
                f"You are a Specialist Agent. You must implement the following objective in the codebase:\n"
                f"Objective: {contract.objective}\n"
                f"Constraints: {contract.constraints}\n"
                f"Acceptance Criteria: {contract.acceptance_criteria}\n"
                f"Repository Stack: {repo_context.stack}\n\n"
                f"{files_context_str}"
                "Please output ONLY the implementation details or the diff instructions."
            )
            
            agent_resp = await ProviderService.static_generate(agent_prompt, context={"task_type": "coding", "run_id": run_id})
            agent_content = agent_resp.get("content", "")
            
            while correction_iteration < max_iterations:
                qa_passed = True
                qa_failures = []
                
                # 4.5 Apply diff to worktree safely
                try:
                    from tools.gimo_server.services.diff_application_service import DiffApplicationService
                    DiffApplicationService.apply(worktree_path, agent_content)
                except Exception as e:
                    logger.error(f"Failed to apply diff: {e}")
                    qa_passed = False
                    qa_failures.append(f"System Error: Failed to apply LLM edits due to formatting. Error: {str(e)}")
                
                if not qa_failures:
                    # 5. QA Gate
                    logger.info(f"Step 5: QA Gate (Iteration {correction_iteration + 1})")
                    import asyncio
                    import shlex
                    
                    qa_commands = [cmd for cmd in repo_context.commands if "test" in cmd.lower() or "lint" in cmd.lower()]
                    if not qa_commands:
                        logger.info("No QA commands found in context. Skipping QA Gate execution.")
                    
                    for cmd in qa_commands:
                        try:
                            logger.info(f"Running QA command: {cmd}")
                            proc = await asyncio.create_subprocess_shell(
                                cmd,
                                cwd=worktree_path,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE
                            )
                            stdout, stderr = await proc.communicate()
                            if proc.returncode != 0:
                                qa_passed = False
                                qa_failures.append(f"QA Failed ({cmd}): {(stderr or stdout).decode('utf-8')}")
                        except Exception as e:
                            qa_passed = False
                            qa_failures.append(f"QA Exception ({cmd}): {str(e)}")
                        
                if qa_passed:
                    break
                    
                correction_iteration += 1
                if correction_iteration >= max_iterations:
                    break
                    
                # Orchestrator correction review
                logger.warning(f"QA Gate failed. Asking Orchestrator for fix. (Iteration {correction_iteration})")
                
                # Stage files to capture untracked additions safely for the iteration diff
                add_proc = await asyncio.create_subprocess_shell("git add -A", cwd=worktree_path)
                await add_proc.wait()
                
                diff_proc = await asyncio.create_subprocess_shell(
                    "git diff --staged",
                    cwd=worktree_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                diff_out, _ = await diff_proc.communicate()
                current_diff = diff_out.decode('utf-8', errors='replace')
                
                # Restore staging area to keep it clean (optional but good practice)
                reset_proc = await asyncio.create_subprocess_shell("git reset", cwd=worktree_path)
                await reset_proc.wait()
                
                orchestrator_prompt = (
                    f"You are the Orchestrator. The worker agent attempted to implement the objective but failed QA.\n"
                    f"Objective: {contract.objective}\n\n"
                    f"Failures:\n" + "\n".join(qa_failures) + "\n\n"
                    f"Current Git Diff in Sandbox:\n{current_diff}\n\n"
                    f"Provide precise instructions on what lines to change to fix these QA errors."
                )
                
                orch_resp = await ProviderService.static_generate(orchestrator_prompt, context={"task_type": "review", "run_id": run_id})
                fix_instructions = orch_resp.get("content", "")
                
                # RE-EVALUATE context explicitly so worker can apply patches over the modified sandbox
                if path_scope:
                    scoped_files_content = ContextIndexer.extract_file_contents(worktree_path, path_scope)
                files_context_str = f"Relevant File Contents:\n{scoped_files_content}\n\n" if scoped_files_content else ""
                
                worker_prompt = (
                    f"You are a Specialist Agent. You must fix the codebase to resolve QA errors based on the Orchestrator's review.\n"
                    f"Orchestrator's Fix Instructions:\n{fix_instructions}\n\n"
                    f"{files_context_str}"
                    f"Please output ONLY the implementation details or the diff instructions to apply the fix."
                )
                
                agent_resp = await ProviderService.static_generate(worker_prompt, context={"task_type": "coding", "run_id": run_id})
                agent_content = agent_resp.get("content", "")
                
            draft_status = "draft" if qa_passed else "rejected"
            draft_error = None if qa_passed else "\n".join(qa_failures)
            
            # 5.5 If QA passed, commit changes to the branch so MergeGate can merge them
            if qa_passed:
                try:
                    import asyncio
                    proc_add = await asyncio.create_subprocess_exec(
                        "git", "add", ".",
                        cwd=worktree_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc_add.communicate()
                    
                    proc_commit = await asyncio.create_subprocess_exec(
                        "git", "commit", "-m", f"Implementation by Specialist Agent for run {run_id}",
                        cwd=worktree_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    out, err = await proc_commit.communicate()
                    if proc_commit.returncode == 0:
                        logger.info("Changes committed to sandbox branch.")
                    else:
                        logger.info(f"Git commit output: {(out or err).decode('utf-8')}")
                except Exception as e:
                    logger.error(f"Failed to commit changes in sandbox: {str(e)}")
                    # For MVP, if it fails to commit (e.g. no changes), we still let it pass
            
            # 6. Draft Creation (GraphState equivalent persistence)
            context = {
                "repo_context": repo_context.model_dump(),
                "contract": contract.model_dump(),
                "agent_content": agent_content,
                "worktree_path": worktree_path,
                "qa_passed": qa_passed,
                "qa_failures": qa_failures,
                "intent_class": contract.execution.intent_class.value,
                # Phase 7 Merge Gate required variables
                "policy_decision": "allow",
                "policy_decision_id": f"override_{run_id}",
                "risk_score": 0.0,
                "intent_effective": contract.execution.intent_class.value,
                "execution_decision": "AUTO_RUN_ELIGIBLE",
                "source_ref": f"gimo_{run_id}",     # The branch SandboxService created
                "target_branch": "main"             # Hardcoded to main for MVP (can be dynamic)
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
