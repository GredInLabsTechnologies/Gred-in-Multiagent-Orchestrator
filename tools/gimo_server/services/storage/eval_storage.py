from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from ...ops_models import EvalDataset, EvalRunReport

logger = logging.getLogger("orchestrator.services.storage.eval")

class EvalStorage:
    """Storage logic for evaluation datasets and reports.
    Persists entirely via GICS.
    """

    def __init__(self, conn: Optional[Any] = None, gics: Optional[Any] = None):
        self._conn = conn # Kept for backward compatibility
        self.gics = gics

    def ensure_tables(self) -> None:
        """No-op: using GICS."""
        pass

    def save_eval_report(self, report: EvalRunReport | Dict[str, Any]) -> int:
        if not self.gics:
            return 0
            
        data = report.model_dump() if isinstance(report, EvalRunReport) else dict(report)
        workflow_id = data.get("workflow_id", "unknown")
        run_id = int(time.time() * 1000)
        data["run_id"] = run_id
        data["eval_run_id"] = run_id  # keep both names for model compat
        
        try:
            self.gics.put(f"er:{workflow_id}:{run_id}", data)
        except Exception as e:
            logger.error("Failed to push eval report %s to GICS: %s", run_id, e)
        
        return run_id

    def save_eval_dataset(
        self,
        dataset: EvalDataset | Dict[str, Any],
        *,
        version_tag: Optional[str] = None,
    ) -> int:
        if not self.gics:
            return 0
            
        data = dataset.model_dump() if isinstance(dataset, EvalDataset) else dict(dataset)
        workflow_id = data.get("workflow_id", "unknown")
        version = version_tag or "latest"
        dataset_id = int(time.time() * 1000)
        data["dataset_id"] = dataset_id
        data["version_tag"] = version
        
        try:
            self.gics.put(f"ed:{workflow_id}:{version}", data)
        except Exception as e:
            logger.error("Failed to push eval dataset %s to GICS: %s", dataset_id, e)

        return dataset_id

    def list_eval_datasets(self, *, workflow_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.gics:
            return []
            
        try:
            prefix = "ed:"
            if workflow_id:
                prefix += f"{workflow_id}:"
            
            items = self.gics.scan(prefix=prefix, include_fields=True)
            datasets = []
            for item in items:
                fields = item.get("fields", {})
                datasets.append({
                    "dataset_id": fields.get("dataset_id", 0),
                    "workflow_id": fields.get("workflow_id"),
                    "version_tag": fields.get("version_tag", "latest"),
                    "created_at": item.get("timestamp") or fields.get("created_at"),
                    "name": fields.get("name", "Untitled Dataset"),
                    "description": fields.get("description", ""),
                    "cases": fields.get("cases", []),
                })
            datasets.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
            return datasets[:limit]
        except Exception as e:
            logger.error("Failed to list eval datasets from GICS: %s", e)
            return []

    def get_eval_dataset(self, dataset_id: int) -> Optional[Dict[str, Any]]:
        if not self.gics:
            return None
            
        try:
            items = self.gics.scan(prefix="ed:", include_fields=True)
            for item in items:
                fields = item.get("fields", {})
                if fields.get("dataset_id") == dataset_id:
                    return {
                        "dataset_id": dataset_id,
                        "workflow_id": fields.get("workflow_id"),
                        "version_tag": fields.get("version_tag", "latest"),
                        "created_at": item.get("timestamp") or fields.get("created_at"),
                        "dataset": fields,
                    }
        except Exception as e:
            logger.error("Failed to get eval dataset %s from GICS: %s", dataset_id, e)
            
        return None

    def list_eval_reports(self, *, workflow_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.gics:
            return []
            
        try:
            prefix = "er:"
            if workflow_id:
                prefix += f"{workflow_id}:"
            
            items = self.gics.scan(prefix=prefix, include_fields=True)
            reports = []
            for item in items:
                fields = item.get("fields", {})
                reports.append({
                    "run_id": fields.get("run_id", 0),
                    "workflow_id": fields.get("workflow_id"),
                    "gate_passed": bool(fields.get("gate_passed")),
                    "pass_rate": float(fields.get("pass_rate", 0.0)),
                    "avg_score": float(fields.get("avg_score", 0.0)),
                    "total_cases": int(fields.get("total_cases", 0)),
                    "passed_cases": int(fields.get("passed_cases", 0)),
                    "failed_cases": int(fields.get("failed_cases", 0)),
                    "created_at": item.get("timestamp") or fields.get("created_at"),
                })
            reports.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
            return reports[:limit]
        except Exception as e:
            logger.error("Failed to list eval reports from GICS: %s", e)
            return []

    def get_eval_report(self, run_id: int) -> Optional[Dict[str, Any]]:
        if not self.gics:
            return None
            
        try:
            items = self.gics.scan(prefix="er:", include_fields=True)
            for item in items:
                fields = item.get("fields", {})
                if fields.get("run_id") == run_id:
                    return {
                        "run_id": run_id,
                        "workflow_id": fields.get("workflow_id"),
                        "created_at": item.get("timestamp") or fields.get("created_at"),
                        "report": fields,
                    }
        except Exception as e:
            logger.error("Failed to get eval report %s from GICS: %s", run_id, e)
            
        return None
