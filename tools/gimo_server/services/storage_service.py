from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from ..ops_models import EvalDataset, EvalRunReport, TrustEvent

from .storage.workflow_storage import WorkflowStorage
from .storage.eval_storage import EvalStorage
from .storage.trust_storage import TrustStorage
from .storage.config_storage import ConfigStorage
from .storage.cost_storage import CostStorage
from .gics_service import GicsService

logger = logging.getLogger("orchestrator.services.storage")

class StorageService:
    """Storage service for operational data (Facade for domain-specific storage).
    Powered entirely by GICS.
    """

    # Class-level GICS reference — set once at startup by main.py lifespan.
    # All StorageService() calls without explicit gics= will use this.
    _shared_gics: Optional[GicsService] = None

    @classmethod
    def set_shared_gics(cls, gics: Optional[GicsService]) -> None:
        """Set the shared GICS instance for all StorageService instances."""
        cls._shared_gics = gics

    def __init__(self, gics: Optional[GicsService] = None, conn: Optional[Any] = None):
        resolved = gics or self.__class__._shared_gics
        if not resolved:
            logger.critical(
                "StorageService created without GICS — all persistence will silently no-op. "
                "Ensure GICS is running and StorageService.set_shared_gics() was called at startup."
            )
        self.gics = resolved
        
        # Initialize sub-storages sharing the GICS instance
        self.workflows = WorkflowStorage(gics=self.gics)
        self.eval = EvalStorage(gics=self.gics)
        self.trust = TrustStorage(gics_service=self.gics)
        self.config = ConfigStorage(gics=self.gics)
        self.cost = CostStorage(gics=self.gics)

    # --- Workflow Domain ---
    def save_workflow(self, workflow_id: str, data: str) -> None:
        return self.workflows.save_workflow(workflow_id, data)

    def save_checkpoint(self, workflow_id: str, node_id: str, state: Any, output: Optional[Any], status: str) -> None:
        return self.workflows.save_checkpoint(workflow_id, node_id, state, output, status)

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        return self.workflows.get_workflow(workflow_id)

    def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        return self.workflows.list_checkpoints(workflow_id)

    # --- Trust Domain ---
    def save_trust_event(self, event: TrustEvent | Dict[str, Any]) -> None:
        return self.trust.save_trust_event(event)

    def save_trust_events(self, events: List[TrustEvent | Dict[str, Any]]) -> None:
        return self.trust.save_trust_events(events)

    def list_trust_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.trust.list_trust_events(limit)

    def list_trust_events_by_dimension(self, dimension_key: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.trust.list_trust_events_by_dimension(dimension_key, limit)

    def get_trust_record(self, dimension_key: str) -> Optional[Dict[str, Any]]:
        return self.trust.get_trust_record(dimension_key)

    def upsert_trust_record(self, record: Dict[str, Any]) -> None:
        return self.trust.upsert_trust_record(record)

    def list_trust_records(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.trust.list_trust_records(limit)

    # --- Config Domain ---
    def get_circuit_breaker_config(self, dimension_key: str) -> Optional[Dict[str, Any]]:
        return self.config.get_circuit_breaker_config(dimension_key)

    def upsert_circuit_breaker_config(self, dimension_key: str, config: Dict[str, Any]) -> Dict[str, Any]:
        return self.config.upsert_circuit_breaker_config(dimension_key, config)

    def register_tool_call_idempotency_key(self, *, idempotency_key: str, tool: str, context: Optional[str] = None) -> bool:
        return self.config.register_tool_call_idempotency_key(idempotency_key=idempotency_key, tool=tool, context=context)

    # --- Eval Domain ---
    def save_eval_report(self, report: EvalRunReport | Dict[str, Any]) -> int:
        return self.eval.save_eval_report(report)

    def save_eval_dataset(self, dataset: EvalDataset | Dict[str, Any], *, version_tag: Optional[str] = None) -> int:
        return self.eval.save_eval_dataset(dataset, version_tag=version_tag)

    def list_eval_datasets(self, *, workflow_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        return self.eval.list_eval_datasets(workflow_id=workflow_id, limit=limit)

    def get_eval_dataset(self, dataset_id: int) -> Optional[Dict[str, Any]]:
        return self.eval.get_eval_dataset(dataset_id)

    def list_eval_reports(self, *, workflow_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        return self.eval.list_eval_reports(workflow_id=workflow_id, limit=limit)

    def get_eval_report(self, run_id: int) -> Optional[Dict[str, Any]]:
        return self.eval.get_eval_report(run_id)

    def close(self) -> None:
        # GICS lifecycle is managed by GIMO App, so we don't close it here.
        pass
