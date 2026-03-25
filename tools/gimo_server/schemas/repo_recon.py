from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class ReconListRequest(BaseModel):
    path_handle: Optional[str] = None

class ReconSearchRequest(BaseModel):
    query: str

class ReconReadRequest(BaseModel):
    file_handle: str

class ReconEntry(BaseModel):
    name: str
    handle: str
    type: str
    size: int
    last_modified: str

class ReadProof(BaseModel):
    proof_id: str
    repo_handle: str
    artifact_handle: str
    kind: str
    evidence_hash: str
    base_commit: str
    timestamp: str

class FileContentResponse(BaseModel):
    handle: str
    content: str
    proof: ReadProof
