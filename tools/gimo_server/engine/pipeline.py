from __future__ import annotations
import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel
from .contracts import StageInput, StageOutput, ExecutionStage, JournalEntry
from .journal import RunJournal

logger = logging.getLogger(__name__)

class PipelineConfig(BaseModel):
    max_retries: int = 2
    retry_delay_seconds: float = 1.0
    stop_on_failure: bool = True

class Pipeline:
    def __init__(
        self,
        run_id: str,
        stages: List[ExecutionStage],
        config: Optional[PipelineConfig] = None,
        on_stage_transition: Optional[Callable[[str, str], None]] = None,
    ):
        self.run_id = run_id
        self.stages = stages
        self.config = config or PipelineConfig()
        self.results: Dict[str, StageOutput] = {}
        self.artifacts: Dict[str, Any] = {}
        self.journal: List[JournalEntry] = []
        self._journal_store: Optional[RunJournal] = None
        # R17 Cluster A: heartbeat hook fired on every stage transition.
        # Signature: (stage_name, phase) where phase ∈ {"start", "end"}.
        self._on_stage_transition = on_stage_transition

    def _ensure_journal_store(self, context: Dict[str, Any]) -> None:
        journal_path = context.get("journal_path")
        if not journal_path:
            return
        if self._journal_store is None:
            self._journal_store = RunJournal(storage_path=str(journal_path))

    async def run(self, initial_context: Dict[str, Any]) -> List[StageOutput]:
        current_context = initial_context.copy()
        self._ensure_journal_store(current_context)
        execution_history: List[tuple[ExecutionStage, StageInput]] = []

        for stage in self.stages:
            stage_input = StageInput(
                run_id=self.run_id,
                context=current_context,
                artifacts=self.artifacts
            )

            if self._on_stage_transition:
                try:
                    self._on_stage_transition(stage.name, "start")
                except Exception:
                    logger.debug("on_stage_transition(start) hook failed", exc_info=True)

            output = await self._execute_stage_with_retries(stage, stage_input)
            self.results[stage.name] = output
            execution_history.append((stage, stage_input))

            if self._on_stage_transition:
                try:
                    self._on_stage_transition(stage.name, "end")
                except Exception:
                    logger.debug("on_stage_transition(end) hook failed", exc_info=True)
            
            if output.journal_entry:
                self.journal.append(output.journal_entry)
                if self._journal_store:
                    self._journal_store.append(output.journal_entry)
            
            self.artifacts.update(output.artifacts)
            
            if output.status == "fail" and self.config.stop_on_failure:
                # Trigger rollback for all completed stages in reverse order
                logger.warning("Pipeline failed at stage %s. Triggering rollback.", stage.name)
                rollback_errors: list[tuple[str, Exception]] = []
                for completed_stage, completed_input in reversed(execution_history):
                    try:
                        await completed_stage.rollback(completed_input)
                    except Exception as rb_err:
                        logger.error("Error during rollback of %s: %s", completed_stage.name, rb_err)
                        rollback_errors.append((completed_stage.name, rb_err))
                if rollback_errors:
                    output.artifacts["rollback_status"] = "partial"
                    output.artifacts["rollback_errors"] = [
                        f"{name}: {err}" for name, err in rollback_errors
                    ]
                else:
                    output.artifacts["rollback_status"] = "clean"
                break
            if output.status == "halt":
                break
                
        return list(self.results.values())


    async def _execute_stage_with_retries(self, stage: ExecutionStage, input: StageInput) -> StageOutput:
        last_error: Optional[Exception] = None

        for attempt in range(self.config.max_retries + 1):
            try:
                started_at = datetime.now(timezone.utc)
                output = await stage.execute(input)
                finished_at = datetime.now(timezone.utc)

                if not output.journal_entry:
                    output.journal_entry = self._create_journal_entry(
                        stage, input, output, started_at, finished_at,
                        "completed" if output.status != "fail" else "failed",
                    )

                if output.status == "retry" and attempt == self.config.max_retries:
                    output = StageOutput(
                        status="fail",
                        artifacts={
                            **dict(output.artifacts or {}),
                            "error": f"Stage requested retry but max retries exhausted: {stage.name}",
                        },
                        journal_entry=output.journal_entry,
                    )
                if output.status != "retry" or attempt == self.config.max_retries:
                    return output

            except Exception as e:
                last_error = e
                if attempt == self.config.max_retries:
                    break

            await asyncio.sleep(self.config.retry_delay_seconds * (2 ** attempt))

        finished_at = datetime.now(timezone.utc)
        err_text = str(last_error) if last_error else "Max retries exceeded"
        failed_output = StageOutput(status="fail", artifacts={"error": err_text}, error=err_text)
        failed_output.journal_entry = self._create_journal_entry(
            stage, input, failed_output, finished_at, finished_at, "failed",
        )
        return failed_output

    def _create_journal_entry(
        self, stage: ExecutionStage, input: StageInput, output: StageOutput, 
        started_at: datetime, finished_at: datetime, status: str
    ) -> JournalEntry:
        input_json = input.model_dump_json()
        output_json = output.model_dump_json()
        input_hash = hashlib.sha256(input_json.encode()).hexdigest()
        output_hash = hashlib.sha256(output_json.encode()).hexdigest()
        
        return JournalEntry(
            step_id=f"{self.run_id}_{stage.name}_{started_at.timestamp()}",
            stage_name=stage.name,
            started_at=started_at,
            finished_at=finished_at,
            input_hash=input_hash,
            output_hash=output_hash,
            input_snapshot=input.model_dump(),
            output_snapshot=output.model_dump(),
            status=status
        )
