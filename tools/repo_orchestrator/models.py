from dataclasses import dataclass
from typing import List, Optional

from pydantic import BaseModel


@dataclass
class RepoEntry:
    name: str
    path: str


class VitaminizeResponse(BaseModel):
    status: str
    created_files: List[str]
    active_repo: Optional[str] = None


class StatusResponse(BaseModel):
    version: str
    uptime_seconds: float


class UiStatusResponse(BaseModel):
    version: str
    uptime_seconds: float
    allowlist_count: int
    last_audit_line: Optional[str] = None
    service_status: str


class FileWriteRequest(BaseModel):
    path: str
    content: str
