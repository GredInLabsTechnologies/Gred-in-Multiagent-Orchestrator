from pydantic import BaseModel
from typing import Optional, Dict, Any

class ContextCreateRequest(BaseModel):
    description: str
    metadata: Optional[Dict[str, Any]] = None

class ContextResolveRequest(BaseModel):
    evidence: str

class ContextCancelRequest(BaseModel):
    reason: str

class ContextRequestEntry(BaseModel):
    id: str
    session_id: str
    description: str
    status: str
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str
    result: Optional[str] = None
