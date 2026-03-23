from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, Literal, Optional, Protocol
from pydantic import BaseModel, Field

class StageInput(BaseModel):
    run_id: str
    context: Dict[str, Any] = Field(default_factory=dict)
    artifacts: Dict[str, Any] = Field(default_factory=dict)  # Outputs de stages previos

class JournalEntry(BaseModel):
    step_id: str
    stage_name: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    input_hash: str
    output_hash: str
    input_snapshot: Dict[str, Any]
    output_snapshot: Dict[str, Any]
    status: Literal["completed", "failed", "retried", "rolled_back"]

class StageOutput(BaseModel):
    status: Literal["continue", "halt", "retry", "fail"]
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    journal_entry: Optional[JournalEntry] = None
    error: Optional[str] = None


class FileTaskSpec(BaseModel):
    """Explicit contract for file-write tasks.

    When present in StageInput.context["file_task_spec"], FileWrite uses this
    as the authoritative source for target_path instead of regex extraction.
    """
    kind: Literal["file_task"] = "file_task"
    target_path: str
    write_mode: Literal["create", "overwrite", "append"] = "overwrite"
    allowed_root: Optional[str] = None
    requires_review: bool = False


class ExecutionStage(Protocol):
    name: str
    async def execute(self, input: StageInput) -> StageOutput: ...
    async def rollback(self, input: StageInput) -> None: ...
