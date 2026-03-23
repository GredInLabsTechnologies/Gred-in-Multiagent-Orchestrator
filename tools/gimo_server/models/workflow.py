from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

class WorkflowNode(BaseModel):
    id: str
    type: Literal[
        "llm_call", "tool_call", "human_review", "eval",
        "transform", "sub_graph", "agent_task", "contract_check",
    ]
    config: Dict[str, Any] = Field(default_factory=dict)
    agent: Optional[str] = None
    timeout: Optional[int] = None
    retries: int = 0

class WorkflowEdge(BaseModel):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    condition: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

class WorkflowGraph(BaseModel):
    id: str
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]
    state_schema: Dict[str, Any] = Field(default_factory=dict)
    reducers: Dict[str, str] = Field(default_factory=dict)

class WorkflowCheckpoint(BaseModel):
    node_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: Dict[str, Any]
    output: Any
    status: Literal["completed", "failed"]

class WorkflowState(BaseModel):
    version: int = 1
    data: Dict[str, Any] = Field(default_factory=dict)
    checkpoints: List[WorkflowCheckpoint] = Field(default_factory=list)

class WorkflowExecuteRequest(BaseModel):
    workflow: WorkflowGraph
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    persist_checkpoints: bool = True
    workflow_timeout_seconds: Optional[int] = None

class ContractCheck(BaseModel):
    type: Literal["file_exists", "tests_pass", "function_exists", "no_new_vulnerabilities", "custom"]
    params: Dict[str, Any] = Field(default_factory=dict)

class WorkflowContract(BaseModel):
    pre_conditions: List[ContractCheck] = Field(default_factory=list)
    post_conditions: List[ContractCheck] = Field(default_factory=list)
    rollback: List[Dict[str, Any]] = Field(default_factory=list)
    blast_radius: Literal["low", "medium", "high", "critical"] = "low"
