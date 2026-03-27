from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict, Any

class DraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_paths: Optional[List[str]] = None
    acceptance_criteria: str
    worker_model: Optional[str] = None

class ValidatedTaskSpec(BaseModel):
    base_commit: str
    repo_handle: str
    allowed_paths: List[str]
    acceptance_criteria: str
    evidence_hash: str
    context_pack_id: str
    worker_model: str
    requires_manual_merge: bool

class RepoContextPack(BaseModel):
    id: str
    session_id: str
    repo_handle: str
    base_commit: str
    read_proofs: List[Dict[str, Any]]
    allowed_paths: List[str]

class DraftValidationResponse(BaseModel):
    draft_id: Optional[str] = None
    validated_task_spec: ValidatedTaskSpec
    repo_context_pack: RepoContextPack
