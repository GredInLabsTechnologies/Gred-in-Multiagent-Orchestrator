from __future__ import annotations

import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, Span
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


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
            item["event"] = "end"

        self.ui_spans.append(item)


class ObservabilityService:
    """Industrial-grade observability store using OpenTelemetry.

    Provides distributed tracing and metrics with backward compatibility for the MVP UI.
    """

    _lock = threading.RLock()
    _initialized = False
    
    # Internal buffer for UI compatibility
    _ui_spans: Deque[Dict[str, Any]] = deque(maxlen=5000)
    _ui_metrics: Dict[str, Any] = {
        "workflows_total": 0,
        "nodes_total": 0,
        "nodes_failed": 0,
        "tokens_total": 0,
        "cost_total_usd": 0.0,
    }
    
    # OTel components
    _tracer: trace.Tracer = None
    _meter: metrics.Meter = None
    
    # Metrics instruments
    _workflows_counter = None
    _nodes_counter = None
    _nodes_failed_counter = None
    _tokens_counter = None
    _cost_counter = None

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
            # For now, we use PeriodicExportingMetricReader + Console
            reader = PeriodicExportingMetricReader(ConsoleMetricExporter())
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
    def get_metrics(cls) -> Dict[str, Any]:
        with cls._lock:
            return dict(cls._ui_metrics)

    @classmethod
    def list_traces(cls, *, limit: int = 20) -> List[Dict[str, Any]]:
        """Returns a list of aggregated traces (latest first)."""
        with cls._lock:
            raw_spans = list(cls._ui_spans)
        
        # Group by trace_id
        traces: Dict[str, Dict[str, Any]] = {}
        
        for span in raw_spans:
            t_id = span["trace_id"]
            if t_id not in traces:
                traces[t_id] = {
                    "trace_id": t_id,
                    "root_span": None,
                    "spans": [],
                    "start_time": span["timestamp"],
                    "end_time": span["timestamp"],
                    "status": "pending",
                    "duration_ms": 0
                }
            
            trace_obj = traces[t_id]
            trace_obj["spans"].append(span)
            
            # Determine root span (workflow kind)
            if span["kind"] == "workflow" and span.get("event") != "end":
                trace_obj["root_span"] = span
                trace_obj["start_time"] = span["timestamp"]
                trace_obj["workflow_id"] = span.get("workflow_id")
            
            # Update end time
            if span["timestamp"] > trace_obj["end_time"]:
                trace_obj["end_time"] = span["timestamp"]
            
            # Update status if we see a completion event
            if span["kind"] == "workflow" and span.get("event") == "end":
                 trace_obj["status"] = span.get("status", "completed")

        # Post-process traces
        result = []
        for t in traces.values():
            if not t["root_span"]:
                # If we missed the start event (deque rotation), try to infer or skip
                if t["spans"]:
                     t["root_span"] = t["spans"][0] # Fallback
            
            # Calculate duration
            try:
                start = datetime.fromisoformat(t["start_time"].replace('Z', '+00:00'))
                end = datetime.fromisoformat(t["end_time"].replace('Z', '+00:00'))
                t["duration_ms"] = int((end - start).total_seconds() * 1000)
            except Exception:
                t["duration_ms"] = 0
            
            result.append(t)
            
        # Sort by start_time descending
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
            if span["kind"] == "workflow" and span.get("event") != "end":
                trace_obj["root_span"] = span
                trace_obj["start_time"] = span["timestamp"]
            if span["kind"] == "workflow" and span.get("event") == "end":
                trace_obj["status"] = span.get("status", "completed")
                trace_obj["end_time"] = span["timestamp"]

        if not trace_obj["root_span"] and raw_spans:
             trace_obj["root_span"] = raw_spans[0]

        return trace_obj

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._ui_spans.clear()
            cls._active_spans.clear()
            # Reset UI internal metrics
            for k in cls._ui_metrics:
                cls._ui_metrics[k] = 0.0 if isinstance(cls._ui_metrics[k], float) else 0
            # Keep _initialized=True so the SDK is not re-initialized,
            # but ensure the UISpanProcessor still references our reset dicts.
