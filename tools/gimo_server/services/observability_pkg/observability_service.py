from __future__ import annotations

import os
import json
import logging
import threading
from collections import Counter
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("orchestrator.observability")

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, Span
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from ...config import OPS_DATA_DIR
from ..run_lifecycle import is_active_run_status


from opentelemetry.sdk.trace import SpanProcessor

class UISpanProcessor(SpanProcessor):
    """Bridge OTel spans to the internal deque for UI compatibility."""
    
    def __init__(self, ui_spans: Deque[Dict[str, Any]], ui_metrics: Dict[str, Any]):
        self.ui_spans = ui_spans
        self.ui_metrics = ui_metrics

    def on_end(self, span: Span) -> None:
        attrs = dict(span.attributes or {})
        kind = attrs.get("kind", "node")
        
        # Build UI-compatible trace item
        item = {
            "kind": kind,
            "workflow_id": attrs.get("workflow_id"),
            "trace_id": format(span.get_span_context().trace_id, '032x'),
            "span_id": format(span.get_span_context().span_id, '016x'),
            "timestamp": datetime.fromtimestamp(span.end_time / 1e9, tz=timezone.utc).isoformat(),
            "status": attrs.get("status") or ("completed" if span.status.is_ok else "failed"),
        }
        
        if kind == "node":
            item.update({
                "node_id": attrs.get("node_id"),
                "node_type": attrs.get("node_type"),
                "step_id": attrs.get("step_id"),
                "duration_ms": attrs.get("duration_ms", int((span.end_time - span.start_time) / 1e6)),
                "tokens_used": attrs.get("tokens_used", 0),
                "cost_usd": attrs.get("cost_usd", 0.0),
            })
            
            # Update metrics
            with ObservabilityService._lock:
                self.ui_metrics["nodes_total"] += 1
                if item["status"] == "failed":
                    self.ui_metrics["nodes_failed"] += 1
                self.ui_metrics["tokens_total"] += int(item.get("tokens_used") or 0)
                self.ui_metrics["cost_total_usd"] += float(item.get("cost_usd") or 0.0)
        
        elif kind == "workflow":
            with ObservabilityService._lock:
                self.ui_metrics["workflows_total"] += 1
            item["started_at"] = datetime.fromtimestamp(span.start_time / 1e9, tz=timezone.utc).isoformat()
            item["duration_ms"] = int((span.end_time - span.start_time) / 1e6)
            item["event"] = "end"

        self.ui_spans.append(item)


class ObservabilityService:
    """Industrial-grade observability store using OpenTelemetry.

    Provides distributed tracing and metrics with backward compatibility for the MVP UI.
    """

    _lock = threading.RLock()
    _initialized = False
    OBS_LOG_SCHEMA_VERSION = "1.0"
    AI_USAGE_LOG_PATH: Path = OPS_DATA_DIR / "logs" / "ai_usage.jsonl"
    
    # Internal buffer for UI compatibility
    _ui_spans: Deque[Dict[str, Any]] = deque(maxlen=5000)
    _structured_events: Deque[Dict[str, Any]] = deque(maxlen=5000)
    _ui_metrics: Dict[str, Any] = {
        "workflows_total": 0,
        "nodes_total": 0,
        "nodes_failed": 0,
        "tokens_total": 0,
        "cost_total_usd": 0.0,
    }
    _stage_latency: Dict[str, List[float]] = {}
    _run_outcome_counters: Counter[str] = Counter()
    _error_category_counters: Counter[str] = Counter()
    
    # OTel components
    _tracer: trace.Tracer = None
    _meter: metrics.Meter = None
    
    # Metrics instruments
    _workflows_counter = None
    _nodes_counter = None
    _nodes_failed_counter = None
    _tokens_counter = None
    _cost_counter = None
    _stuck_run_threshold_seconds: int = 30 * 60

    _active_spans: Dict[str, trace.Span] = {}

    @classmethod
    def _initialize_sdk(cls):
        with cls._lock:
            if cls._initialized:
                return

            resource = Resource.create({"service.name": "gimo-server"})
            
            # --- Tracing Setup ---
            tracer_provider = TracerProvider(resource=resource)
            
            # 1. Console Exporter (for debugging)
            tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            
            # 2. UI Compatibility Processor
            tracer_provider.add_span_processor(UISpanProcessor(cls._ui_spans, cls._ui_metrics))
            
            # 3. OTLP Exporter (if configured)
            otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            if otlp_endpoint:
                tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
            
            trace.set_tracer_provider(tracer_provider)
            cls._tracer = trace.get_tracer(__name__)

            # --- Metrics Setup ---
            # Note: Prometheus or OTLP metrics could be added here.
            # For now, we use PeriodicExportingMetricReader, but we pipe the
            # console exporter to os.devnull instead of stdout. Rationale:
            # the background metric-export thread ticks on a timer and, when
            # pytest (or any harness) closes the captured stdout, the
            # exporter hits "I/O operation on closed file" and spams the log
            # during teardown. Metrics are still recorded via the in-process
            # counters and the UI span processor — the Console exporter was
            # only ever a debug sink.
            _metrics_sink = open(os.devnull, "w", encoding="utf-8")
            reader = PeriodicExportingMetricReader(ConsoleMetricExporter(out=_metrics_sink))
            meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
            metrics.set_meter_provider(meter_provider)
            cls._meter = metrics.get_meter(__name__)

            # Initialize instruments
            cls._workflows_counter = cls._meter.create_counter("gimo.workflows.total", description="Total workflows started")
            cls._nodes_counter = cls._meter.create_counter("gimo.nodes.total", description="Total nodes executed")
            cls._nodes_failed_counter = cls._meter.create_counter("gimo.nodes.failed", description="Total nodes failed")
            cls._tokens_counter = cls._meter.create_counter("gimo.tokens.total", description="Total tokens consumed")
            cls._cost_counter = cls._meter.create_counter("gimo.cost.total", description="Total cost in USD")

            cls._initialized = True

    @classmethod
    def record_workflow_start(cls, workflow_id: str, trace_id: str) -> None:
        if not cls._initialized:
            cls._initialize_sdk()
        
        with cls._lock:
            # Metrics (OTel)
            cls._workflows_counter.add(1, {"workflow_id": workflow_id})
            
            # OTel Span
            span = cls._tracer.start_span(
                f"workflow:{workflow_id}",
                attributes={"workflow_id": workflow_id, "kind": "workflow"}
            )
            cls._active_spans[trace_id] = span

    @classmethod
    def record_workflow_end(cls, workflow_id: str, trace_id: str, status: str = "completed") -> None:
        """Ends a workflow span and cleans up resources."""
        if not cls._initialized:
            return

        with cls._lock:
            span = cls._active_spans.pop(trace_id, None)
            if span:
                span.set_attribute("status", status)
                if status == "failed":
                    span.set_status(trace.Status(trace.StatusCode.ERROR))
                span.end()

    @classmethod
    def record_node_span(
        cls,
        *,
        workflow_id: str,
        trace_id: str,
        step_id: str,
        node_id: str,
        node_type: str,
        status: str,
        duration_ms: int,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        if not cls._initialized:
            cls._initialize_sdk()
            
        with cls._lock:
            # Metrics (OTel)
            cls._nodes_counter.add(1, {"node_type": node_type, "status": status})
            if status == "failed":
                cls._nodes_failed_counter.add(1, {"node_id": node_id})
            cls._tokens_counter.add(int(tokens_used or 0))
            cls._cost_counter.add(float(cost_usd or 0.0))

            # OTel Span
            parent_span = cls._active_spans.get(trace_id)
            context = trace.set_span_in_context(parent_span) if parent_span else None
            
            with cls._tracer.start_as_current_span(
                f"node:{node_id}",
                context=context,
                attributes={
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "node_id": node_id,
                    "node_type": node_type,
                    "status": status,
                    "tokens_used": int(tokens_used or 0),
                    "cost_usd": float(cost_usd or 0.0),
                    "kind": "node",
                    "duration_ms": int(duration_ms)
                }
            ) as span:
                if status == "failed":
                    span.set_status(trace.Status(trace.StatusCode.ERROR))

    @classmethod
    def record_handoff_event(
        cls,
        *,
        workflow_id: str,
        trace_id: str,
        source_node: str,
        target_node: str,
        summary: str,
        timestamp: str,
    ) -> None:
        if not cls._initialized:
            cls._initialize_sdk()

        with cls._lock:
            cls._ui_spans.append(
                {
                    "kind": "handoff",
                    "workflow_id": workflow_id,
                    "trace_id": trace_id,
                    "span_id": "handoff",
                    "timestamp": timestamp,
                    "status": "completed",
                    "source_node": source_node,
                    "target_node": target_node,
                    "summary": summary,
                }
            )

    @classmethod
    def record_structured_event(
        cls,
        *,
        event_type: str,
        status: str,
        trace_id: str,
        request_id: str,
        run_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Record Phase-8 structured observability event (versioned schema)."""
        if not cls._initialized:
            cls._initialize_sdk()

        stage = kwargs.get("stage", "")
        latency_ms = float(kwargs.get("latency_ms") or 0.0)
        error_category = kwargs.get("error_category", "")

        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "schema_version": cls.OBS_LOG_SCHEMA_VERSION,
            "event_type": event_type,
            "status": status,
            "trace_id": trace_id,
            "request_id": request_id,
            "run_id": run_id,
            "actor": kwargs.get("actor", ""),
            "intent_class": kwargs.get("intent_class", ""),
            "repo_id": kwargs.get("repo_id", ""),
            "baseline_version": kwargs.get("baseline_version", ""),
            "model_attempted": kwargs.get("model_attempted", ""),
            "final_model_used": kwargs.get("final_model_used", ""),
            "stage": stage,
            "latency_ms": latency_ms,
            "error_category": error_category,
            "metadata": kwargs.get("metadata") or {},
        }

        with cls._lock:
            cls._structured_events.append(event)

            if stage:
                cls._stage_latency.setdefault(stage, []).append(latency_ms)

            if status == "FALLBACK_MODEL_USED":
                cls._run_outcome_counters["fallback"] += 1
            if status == "HUMAN_APPROVAL_REQUIRED":
                cls._run_outcome_counters["human_approval_required"] += 1
            if status in {"DRAFT_REJECTED_FORBIDDEN_SCOPE", "BASELINE_TAMPER_DETECTED"}:
                cls._run_outcome_counters["policy_block"] += 1
            if status:
                cls._run_outcome_counters["total"] += 1
            if error_category:
                cls._error_category_counters[error_category] += 1

        return event

    @classmethod
    def list_structured_events(cls, *, limit: int = 200) -> List[Dict[str, Any]]:
        with cls._lock:
            if limit <= 0:
                return []
            return list(cls._structured_events)[-limit:]

    @classmethod
    def record_ai_usage(
        cls,
        *,
        run_id: str,
        draft_id: str,
        provider_type: str,
        auth_mode: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        status: str,
        latency_ms: float,
        request_id: str,
        error_code: str = "",
    ) -> Dict[str, Any]:
        """Phase 6.5 usage/audit event persisted as JSONL (no secrets)."""
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": str(run_id or ""),
            "draft_id": str(draft_id or ""),
            "provider_type": str(provider_type or ""),
            "auth_mode": str(auth_mode or ""),
            "model": str(model or ""),
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
            "cost_usd": float(cost_usd or 0.0),
            "status": str(status or ""),
            "latency_ms": float(latency_ms or 0.0),
            "request_id": str(request_id or ""),
            "error_code": str(error_code or ""),
        }
        try:
            cls.AI_USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with cls.AI_USAGE_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            # Observability must never crash the run path.
            pass
        return payload

    @classmethod
    def get_alerts(cls) -> List[Dict[str, Any]]:
        """Return Sev-0/Sev-1 alerts required by Phase 8 observability."""
        metrics = cls.get_metrics()
        alerts: List[Dict[str, Any]] = []

        error_rate = float(metrics.get("error_rate", 0.0) or 0.0)
        fallback_rate = float(metrics.get("fallback_rate", 0.0) or 0.0)
        policy_block_rate = float(metrics.get("policy_block_rate", 0.0) or 0.0)
        human_approval_rate = float(metrics.get("human_approval_required_rate", 0.0) or 0.0)
        errors_by_category = dict(metrics.get("errors_by_category") or {})
        stuck_runs = int(metrics.get("stuck_runs", 0) or 0)

        if errors_by_category.get("baseline", 0) > 0:
            alerts.append(
                {
                    "severity": "SEV-0",
                    "code": "BASELINE_TAMPER_DETECTED",
                    "message": "Baseline tamper events detected",
                }
            )

        if error_rate >= 0.10:
            alerts.append(
                {
                    "severity": "SEV-1",
                    "code": "HIGH_ERROR_RATE",
                    "message": f"Error rate is high ({error_rate:.2%})",
                }
            )
        if fallback_rate >= 0.40:
            alerts.append(
                {
                    "severity": "SEV-1",
                    "code": "HIGH_FALLBACK_RATE",
                    "message": f"Fallback rate is high ({fallback_rate:.2%})",
                }
            )
        if policy_block_rate >= 0.30:
            alerts.append(
                {
                    "severity": "SEV-1",
                    "code": "HIGH_POLICY_BLOCK_RATE",
                    "message": f"Policy block rate is high ({policy_block_rate:.2%})",
                }
            )
        if human_approval_rate >= 0.70:
            alerts.append(
                {
                    "severity": "SEV-1",
                    "code": "HIGH_HUMAN_APPROVAL_RATE",
                    "message": f"Human approval required rate is high ({human_approval_rate:.2%})",
                }
            )
        if stuck_runs > 0:
            alerts.append(
                {
                    "severity": "SEV-1",
                    "code": "STUCK_RUN_DETECTED",
                    "message": f"Detected {stuck_runs} active run(s) without heartbeat/progress",
                }
            )

        # P9: Anomaly detection
        from .anomaly_detection_service import AnomalyDetectionService

        anomalies = AnomalyDetectionService.detect_anomalies()
        for anomaly in anomalies:
            alerts.append(
                {
                    "severity": "SEV-1",
                    "code": "PRESET_QUALITY_ANOMALY",
                    "message": (
                        f"Preset '{anomaly['preset']}' quality anomaly in {anomaly['task_semantic']}: "
                        f"current {anomaly['current_quality']:.1f} < baseline "
                        f"{anomaly['baseline_mean']:.1f} - {AnomalyDetectionService.ANOMALY_THRESHOLD_SIGMA}σ "
                        f"({anomaly['threshold']:.1f}), gap={anomaly['gap']:.1f}"
                    ),
                    "metadata": anomaly,
                }
            )

        # P9: Downgraded presets
        downgraded = AnomalyDetectionService.get_downgrade_list()
        if downgraded:
            alerts.append(
                {
                    "severity": "SEV-1",
                    "code": "PRESETS_DOWNGRADED",
                    "message": f"{len(downgraded)} preset(s) auto-downgraded due to failure_streak ≥ 5: {', '.join(downgraded)}",
                    "metadata": {"downgraded_presets": downgraded},
                }
            )

        return alerts

    @classmethod
    def _compute_run_health_metrics(cls) -> Dict[str, Any]:
        """Best-effort run-health snapshot used for P2 operational SLI/SLO monitoring."""
        now = datetime.now(timezone.utc)
        try:
            from ..ops_service import OpsService

            runs = OpsService.list_runs()
        except Exception:
            return {
                "active_runs": 0,
                "terminal_runs": 0,
                "stuck_runs": 0,
                "stuck_run_ids": [],
                "run_completion_ratio": 1.0,
                "stuck_run_threshold_seconds": int(cls._stuck_run_threshold_seconds),
            }

        active_runs = [r for r in runs if is_active_run_status(getattr(r, "status", ""))]
        terminal_runs = [r for r in runs if r not in active_runs]
        stuck_run_ids: List[str] = []

        for run in active_runs:
            anchor = getattr(run, "heartbeat_at", None) or getattr(run, "started_at", None) or getattr(run, "created_at", None)
            if not anchor:
                continue
            try:
                age_s = (now - anchor).total_seconds()
            except Exception:
                continue
            if age_s >= float(cls._stuck_run_threshold_seconds):
                stuck_run_ids.append(str(run.id))

        total = len(active_runs) + len(terminal_runs)
        completion_ratio = float(len(terminal_runs)) / float(total) if total else 1.0

        return {
            "active_runs": len(active_runs),
            "terminal_runs": len(terminal_runs),
            "stuck_runs": len(stuck_run_ids),
            "stuck_run_ids": stuck_run_ids,
            "run_completion_ratio": completion_ratio,
            "stuck_run_threshold_seconds": int(cls._stuck_run_threshold_seconds),
        }

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        with cls._lock:
            metrics = dict(cls._ui_metrics)

            total_outcomes = max(1, int(cls._run_outcome_counters.get("total", 0)))
            fallback_rate = float(cls._run_outcome_counters.get("fallback", 0)) / total_outcomes
            human_approval_rate = float(cls._run_outcome_counters.get("human_approval_required", 0)) / total_outcomes
            policy_block_rate = float(cls._run_outcome_counters.get("policy_block", 0)) / total_outcomes

            latency_by_stage = {
                stage: (sum(values) / len(values) if values else 0.0)
                for stage, values in cls._stage_latency.items()
            }
            avg_latency = sum(latency_by_stage.values()) / len(latency_by_stage) if latency_by_stage else 0.0
            error_rate = float(metrics.get("nodes_failed", 0)) / max(1, int(metrics.get("nodes_total", 0)))

            # Fase 8 canonical metrics
            metrics.update(
                {
                    "schema_version": cls.OBS_LOG_SCHEMA_VERSION,
                    "latency_ms_by_stage": latency_by_stage,
                    "fallback_rate": fallback_rate,
                    "human_approval_required_rate": human_approval_rate,
                    "policy_block_rate": policy_block_rate,
                    "errors_by_category": dict(cls._error_category_counters),
                }
            )

            # UI backward/forward compatibility aliases
            metrics.update(
                {
                    "total_workflows": int(metrics.get("workflows_total", 0)),
                    "active_workflows": int(cls._run_outcome_counters.get("total", 0)),
                    "total_tokens": int(metrics.get("tokens_total", 0)),
                    "estimated_cost": float(metrics.get("cost_total_usd", 0.0)),
                    "error_rate": error_rate,
                    "avg_latency_ms": avg_latency,
                }
            )

        run_health = cls._compute_run_health_metrics()
        metrics.update(run_health)
        return metrics

    @classmethod
    def _group_spans(cls, raw_spans: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        traces: Dict[str, Dict[str, Any]] = {}
        for span in raw_spans:
            t_id = span["trace_id"]
            if t_id not in traces:
                traces[t_id] = {
                    "trace_id": t_id, "root_span": None, "spans": [],
                    "start_time": span["timestamp"], "end_time": span["timestamp"],
                    "status": "pending", "duration_ms": 0
                }
            
            trace_obj = traces[t_id]
            trace_obj["spans"].append(span)
            
            if span["kind"] == "workflow":
                if trace_obj["root_span"] is None or span.get("event") != "end":
                    trace_obj["root_span"] = span
                trace_obj["workflow_id"] = span.get("workflow_id")
                trace_obj["start_time"] = span.get("started_at", span["timestamp"])
                if span.get("event") == "end":
                    trace_obj["status"] = span.get("status", "completed")
             
            if span["timestamp"] > trace_obj["end_time"]:
                trace_obj["end_time"] = span["timestamp"]
            
        return traces

    @classmethod
    def _finalize_traces(cls, traces: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for t in traces.values():
            if not t["root_span"] and t["spans"]:
                t["root_span"] = t["spans"][0]
            t["duration_ms"] = cls._resolve_trace_duration_ms(t)
            result.append(t)
        return result

    @classmethod
    def _resolve_trace_duration_ms(cls, trace_obj: Dict[str, Any]) -> int:
        root_duration_raw = (trace_obj.get("root_span") or {}).get("duration_ms")
        root_duration = int(root_duration_raw) if isinstance(root_duration_raw, (int, float)) else 0
        if root_duration > 0:
            return root_duration

        node_durations = [
            int(span.get("duration_ms", 0))
            for span in trace_obj.get("spans", [])
            if span.get("kind") == "node" and isinstance(span.get("duration_ms"), (int, float))
        ]
        summed_node_duration = sum(d for d in node_durations if d > 0)
        if summed_node_duration > 0:
            return summed_node_duration

        try:
            start = datetime.fromisoformat(str(trace_obj["start_time"]).replace('Z', '+00:00'))
            end = datetime.fromisoformat(str(trace_obj["end_time"]).replace('Z', '+00:00'))
            return int((end - start).total_seconds() * 1000)
        except Exception:
            return 0

    @classmethod
    def list_traces(cls, *, limit: int = 20) -> List[Dict[str, Any]]:
        """Returns a list of aggregated traces (latest first)."""
        with cls._lock:
            raw_spans = list(cls._ui_spans)
        
        traces = cls._group_spans(raw_spans)
        result = cls._finalize_traces(traces)
        result.sort(key=lambda x: x["start_time"], reverse=True)
        return result[:limit]

    @classmethod
    def get_trace(cls, trace_id: str) -> Optional[Dict[str, Any]]:
        with cls._lock:
            raw_spans = [s for s in cls._ui_spans if s["trace_id"] == trace_id]
        
        if not raw_spans:
            return None
            
        # Re-use aggregation logic (simplified)
        trace_obj = {
            "trace_id": trace_id,
            "root_span": None,
            "spans": raw_spans,
            "start_time": raw_spans[0]["timestamp"],
            "end_time": raw_spans[-1]["timestamp"],
            "status": "active",
            "duration_ms": 0
        }
        
        for span in raw_spans:
            if span["kind"] == "workflow":
                if trace_obj["root_span"] is None or span.get("event") != "end":
                    trace_obj["root_span"] = span
                trace_obj["start_time"] = span.get("started_at", span["timestamp"])
                trace_obj["workflow_id"] = span.get("workflow_id")
                if span.get("event") == "end":
                    trace_obj["status"] = span.get("status", "completed")
                    trace_obj["end_time"] = span["timestamp"]

        if not trace_obj["root_span"] and raw_spans:
             trace_obj["root_span"] = raw_spans[0]

        trace_obj["duration_ms"] = cls._resolve_trace_duration_ms(trace_obj)

        return trace_obj

    # --- Migrated from legacy simple ObservabilityService (preserved for compat) ---

    @classmethod
    def record_usage(cls, data: Dict[str, Any]) -> None:
        """Legacy: record a raw AI-usage audit payload to the JSONL log.

        Prefer `record_ai_usage` for new call sites; kept because the simple
        ObservabilityService exposed it as a public helper.
        """
        payload = dict(data or {})
        payload["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            cls.AI_USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with cls.AI_USAGE_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - observability never crashes hot path
            logger.error("Failed to log usage: %s", exc)

    @classmethod
    def record_llm_usage(
        cls,
        *,
        thread_id: Optional[str] = None,
        model: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        tools_executed: int = 0,
        tool_call_format: str = "none",
        estimated: bool = False,
    ) -> None:
        """Single sink for agentic chat / LLM usage.

        Writes to (1) in-memory UI metrics (segregating estimated vs exact
        totals), (2) the AI usage audit JSONL, and (3) per-thread metadata.
        Migrated verbatim from the legacy simple ObservabilityService so no
        telemetry is lost during the unification.
        """
        if not cls._initialized:
            cls._initialize_sdk()

        total = int(prompt_tokens or 0) + int(completion_tokens or 0)

        with cls._lock:
            if estimated:
                cls._ui_metrics.setdefault("tokens_estimated", 0)
                cls._ui_metrics.setdefault("cost_estimated_usd", 0.0)
                cls._ui_metrics["tokens_estimated"] += total
                cls._ui_metrics["cost_estimated_usd"] += float(cost_usd or 0.0)
            else:
                cls._ui_metrics["tokens_total"] += total
                cls._ui_metrics["cost_total_usd"] += float(cost_usd or 0.0)

        # Append-only audit log (reuse the JSONL sink).
        cls.record_usage({
            "thread_id": thread_id,
            "model": model,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "cost_usd": float(cost_usd or 0.0),
            "tools_executed": int(tools_executed or 0),
            "tool_call_format": tool_call_format,
            "estimated": bool(estimated),
        })

        # Per-thread metadata so the UI conversation view can show tokens/cost.
        if thread_id:
            try:
                from ..conversation_service import ConversationService

                def _update(t):
                    prev = t.metadata.get("usage") if isinstance(t.metadata.get("usage"), dict) else {}
                    t.metadata["usage"] = {
                        "prompt_tokens": prev.get("prompt_tokens", 0) + int(prompt_tokens or 0),
                        "completion_tokens": prev.get("completion_tokens", 0) + int(completion_tokens or 0),
                        "cost_usd": prev.get("cost_usd", 0.0) + float(cost_usd or 0.0),
                        "total_tokens": prev.get("total_tokens", 0) + total,
                        "estimated": bool(prev.get("estimated") or estimated),
                    }
                    return True

                ConversationService.mutate_thread(thread_id, _update)
            except Exception:
                logger.debug("Failed to update thread usage for %s", thread_id, exc_info=True)

    @classmethod
    def record_agent_action(cls, event: Any) -> None:
        """Logs an agent action event for behavioral analysis.

        Kept as a log-only sink (parity with the legacy simple service); a
        future iteration can route this through GICS or a dedicated store.
        """
        try:
            agent_id = getattr(event, "agent_id", None)
            tool = getattr(event, "tool", None)
            outcome = getattr(event, "outcome", None)
            logger.info("Agent Action: %s -> %s (%s)", agent_id, tool, outcome)
        except Exception:
            logger.debug("record_agent_action failed", exc_info=True)

    @classmethod
    def get_agent_insights(cls, agent_id: str) -> List[Any]:
        """Return simulated optimization recommendations for an agent.

        Preserves the legacy stub behavior; the real analysis pipeline is a
        separate service and will replace this shim when wired up.
        """
        try:
            from ..ops_models import AgentInsight  # local import to avoid cycles
        except Exception:
            return []

        return [
            AgentInsight(
                type="PERFORMANCE",
                priority="medium",
                message=f"Agent {agent_id} has high latency on 'search' tool.",
                recommendation="Consider using a faster model for simple searches.",
                agent_id=agent_id,
            )
        ]

    @classmethod
    def record_span(cls, kind: str, name: str, attributes: Dict[str, Any]) -> None:
        """Legacy minimal span recording — UI compatibility shim.

        New call sites should use `record_node_span`, `record_workflow_start`,
        or `record_handoff_event`. This keeps parity with the simple service's
        free-form span API.
        """
        if not cls._initialized:
            cls._initialize_sdk()

        span = {
            "kind": kind,
            "name": name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(attributes or {}),
        }
        with cls._lock:
            cls._ui_spans.append(span)
            if (attributes or {}).get("status") == "failed":
                cls._ui_metrics["nodes_failed"] += 1
            if kind == "node":
                cls._ui_metrics["nodes_total"] += 1
                cls._ui_metrics["tokens_total"] += int((attributes or {}).get("tokens_used", 0) or 0)
                cls._ui_metrics["cost_total_usd"] += float((attributes or {}).get("cost_usd", 0.0) or 0.0)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._ui_spans.clear()
            cls._structured_events.clear()
            cls._active_spans.clear()
            cls._stage_latency = {}
            cls._run_outcome_counters = Counter()
            cls._error_category_counters = Counter()
            # Reset UI internal metrics
            for k in cls._ui_metrics:
                cls._ui_metrics[k] = 0.0 if isinstance(cls._ui_metrics[k], float) else 0
            # Keep _initialized=True so the SDK is not re-initialized,
            # but ensure the UISpanProcessor still references our reset dicts.
