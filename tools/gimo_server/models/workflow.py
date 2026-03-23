from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union
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
    max_iterations: Optional[int] = None
    break_condition: Optional[str] = None

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

class SendAction(BaseModel):
    """Fase 3: acción de fan-out para map-reduce dinámico."""
    node: str
    state: Dict[str, Any] = Field(default_factory=dict)


class GraphCommand(BaseModel):
    """Fase 2: comando de routing con update atómico de estado.

    goto:   nodo destino (str) o lista de nodos (solo 1 sin Send).
    update: dict de actualizaciones de estado aplicadas vía StateManager.
    send:   lista de SendAction para map-reduce (Fase 3).
    graph:  "PARENT" para escapar de un subgraph al grafo padre.
    """
    goto: Optional[Union[str, List[str]]] = None
    update: Dict[str, Any] = Field(default_factory=dict)
    send: Optional[List[SendAction]] = None
    graph: Optional[str] = None


def is_graph_command(output: Any) -> bool:
    return isinstance(output, GraphCommand)


class WorkflowContract(BaseModel):
    pre_conditions: List[ContractCheck] = Field(default_factory=list)
    post_conditions: List[ContractCheck] = Field(default_factory=list)
    rollback: List[Dict[str, Any]] = Field(default_factory=list)
    blast_radius: Literal["low", "medium", "high", "critical"] = "low"
