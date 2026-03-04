import os
import re

def refactor_observability():
    path = r"c:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator\tools\gimo_server\services\observability_service.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Refactor record_structured_event (less parameters)
    old_record = '''    @classmethod
    def record_structured_event(
        cls,
        *,
        event_type: str,
        status: str,
        trace_id: str,
        request_id: str,
        run_id: str,
        actor: str = "",
        intent_class: str = "",
        repo_id: str = "",
        baseline_version: str = "",
        model_attempted: str = "",
        final_model_used: str = "",
        stage: str = "",
        latency_ms: Optional[float] = None,
        error_category: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record Phase-8 structured observability event (versioned schema)."""
        if not cls._initialized:
            cls._initialize_sdk()

        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "schema_version": cls.OBS_LOG_SCHEMA_VERSION,
            "event_type": event_type,
            "status": status,
            "trace_id": trace_id,
            "request_id": request_id,
            "run_id": run_id,
            "actor": actor,
            "intent_class": intent_class,
            "repo_id": repo_id,
            "baseline_version": baseline_version,
            "model_attempted": model_attempted,
            "final_model_used": final_model_used,
            "stage": stage,
            "latency_ms": float(latency_ms or 0.0),
            "error_category": error_category,
            "metadata": metadata or {},
        }

        with cls._lock:
            cls._structured_events.append(event)

            if stage:
                cls._stage_latency.setdefault(stage, []).append(float(latency_ms or 0.0))

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

        return event'''

    new_record = '''    @classmethod
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

        return event'''

    content = content.replace(old_record, new_record)

    # 2. Refactor list_traces (reduce complexity)
    old_list_traces = '''    @classmethod
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
        return result[:limit]'''

    new_list_traces = '''    @classmethod
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
            
            if span["kind"] == "workflow" and span.get("event") != "end":
                trace_obj["root_span"] = span
                trace_obj["start_time"] = span["timestamp"]
                trace_obj["workflow_id"] = span.get("workflow_id")
            
            if span["timestamp"] > trace_obj["end_time"]:
                trace_obj["end_time"] = span["timestamp"]
            
            if span["kind"] == "workflow" and span.get("event") == "end":
                 trace_obj["status"] = span.get("status", "completed")
        return traces

    @classmethod
    def _finalize_traces(cls, traces: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for t in traces.values():
            if not t["root_span"] and t["spans"]:
                t["root_span"] = t["spans"][0]
            try:
                start = datetime.fromisoformat(t["start_time"].replace('Z', '+00:00'))
                end = datetime.fromisoformat(t["end_time"].replace('Z', '+00:00'))
                t["duration_ms"] = int((end - start).total_seconds() * 1000)
            except Exception:
                t["duration_ms"] = 0
            result.append(t)
        return result

    @classmethod
    def list_traces(cls, *, limit: int = 20) -> List[Dict[str, Any]]:
        """Returns a list of aggregated traces (latest first)."""
        with cls._lock:
            raw_spans = list(cls._ui_spans)
        
        traces = cls._group_spans(raw_spans)
        result = cls._finalize_traces(traces)
        result.sort(key=lambda x: x["start_time"], reverse=True)
        return result[:limit]'''
        
    content = content.replace(old_list_traces, new_list_traces)
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def refactor_ops_service():
    path = r"c:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator\tools\gimo_server\services\ops_service.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # refactor get_run_preview
    old_preview = '''    @classmethod
    def get_run_preview(
        cls,
        run_id: str,
        *,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return a stable preview payload for audit/UI contracts."""
        run = cls.get_run(run_id)
        if not run:
            return None

        approved = cls.get_approved(run.approved_id)
        if not approved:
            return None

        draft = cls.get_draft(approved.draft_id)
        context = dict((draft.context if draft else {}) or {})

        content = approved.content or ""
        diff_summary = context.get("diff_summary") or f"content_chars={len(content)}"
        risk_score = float(context.get("risk_score", 0.0) or 0.0)
        model_used = str(context.get("model_used") or approved.provider or "unknown")

        expected = str(context.get("policy_hash_expected") or "")
        runtime = str(context.get("policy_hash_runtime") or "")
        if not expected:
            expected = hashlib.sha256((approved.prompt or "").encode("utf-8", errors="ignore")).hexdigest()
        if not runtime:
            runtime = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()

        strategy_line = ""
        for entry in reversed(run.log or []):
            msg = str((entry or {}).get("msg") or "")
            if msg.startswith("Model strategy:"):
                strategy_line = msg
                break

        strategy_fields: Dict[str, str] = {}
        if strategy_line:
            payload = strategy_line.replace("Model strategy:", "").strip()
            for part in payload.split(" "):
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                strategy_fields[k.strip()] = v.strip()

        model_attempted = str(context.get("model_attempted") or strategy_fields.get("attempted") or "")
        failure_reason = str(context.get("failure_reason") or strategy_fields.get("failure_reason") or "")
        final_model_used = str(
            context.get("final_model_used")
            or strategy_fields.get("final_model")
            or model_used
            or "unknown"
        )
        fallback_used_raw = context.get("fallback_used", strategy_fields.get("fallback_used", False))
        fallback_used = bool(str(fallback_used_raw).lower() in {"1", "true", "yes"})

        preview = {
            "run_id": run.id,
            "draft_id": approved.draft_id,
            "status": run.status,
            "final_status": run.status,
            "diff_summary": diff_summary,
            "risk_score": risk_score,
            "intent_declared": str(context.get("intent_declared") or context.get("intent_class") or ""),
            "intent_effective": str(context.get("intent_effective") or context.get("intent_class") or ""),
            "decision_reason": str(context.get("decision_reason") or ""),
            "execution_decision": str(context.get("execution_decision") or ""),
            "model_used": model_used,
            "model_attempted": model_attempted,
            "failure_reason": failure_reason,
            "final_model_used": final_model_used,
            "fallback_used": fallback_used,
            "policy_decision_id": str(context.get("policy_decision_id") or ""),
            "policy_decision": str(context.get("policy_decision") or ""),
            "policy_status_code": str(context.get("policy_status_code") or ""),
            "policy_triggered_rules": list(context.get("policy_triggered_rules") or []),
            "policy_hash_expected": expected,
            "policy_hash_runtime": runtime,
            "baseline_version": str(context.get("baseline_version") or "v1"),
            "commit_before": str(context.get("commit_before") or run.commit_before or "unknown"),
            "commit_after": str(context.get("commit_after") or run.commit_after or "unknown"),
            "trace_id": str(trace_id or context.get("trace_id") or ""),
            "request_id": str(request_id or context.get("request_id") or ""),
            "updated_at": _utcnow().isoformat(),
        }
        return preview'''

    new_preview = '''    @classmethod
    def _extract_strategy_fields(cls, run: Any) -> Dict[str, str]:
        strategy_line = ""
        for entry in reversed(run.log or []):
            msg = str((entry or {}).get("msg") or "")
            if msg.startswith("Model strategy:"):
                strategy_line = msg
                break

        strategy_fields: Dict[str, str] = {}
        if strategy_line:
            payload = strategy_line.replace("Model strategy:", "").strip()
            for part in payload.split(" "):
                if "=" in part:
                    k, v = part.split("=", 1)
                    strategy_fields[k.strip()] = v.strip()
        return strategy_fields

    @classmethod
    def _extract_hashes(cls, context: dict, approved: Any, content: str) -> tuple[str, str]:
        expected = str(context.get("policy_hash_expected") or "")
        runtime = str(context.get("policy_hash_runtime") or "")
        if not expected:
            expected = hashlib.sha256((approved.prompt or "").encode("utf-8", errors="ignore")).hexdigest()
        if not runtime:
            runtime = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
        return expected, runtime

    @classmethod
    def get_run_preview(
        cls,
        run_id: str,
        *,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return a stable preview payload for audit/UI contracts."""
        run = cls.get_run(run_id)
        if not run: return None
        approved = cls.get_approved(run.approved_id)
        if not approved: return None
        draft = cls.get_draft(approved.draft_id)
        context = dict((draft.context if draft else {}) or {})

        content = approved.content or ""
        diff_summary = context.get("diff_summary") or f"content_chars={len(content)}"
        model_used = str(context.get("model_used") or approved.provider or "unknown")

        expected, runtime = cls._extract_hashes(context, approved, content)
        strategy_fields = cls._extract_strategy_fields(run)

        fallback_used_raw = context.get("fallback_used", strategy_fields.get("fallback_used", False))
        fallback_used = bool(str(fallback_used_raw).lower() in {"1", "true", "yes"})

        return {
            "run_id": run.id,
            "draft_id": approved.draft_id,
            "status": run.status,
            "final_status": run.status,
            "diff_summary": diff_summary,
            "risk_score": float(context.get("risk_score", 0.0) or 0.0),
            "intent_declared": str(context.get("intent_declared") or context.get("intent_class") or ""),
            "intent_effective": str(context.get("intent_effective") or context.get("intent_class") or ""),
            "decision_reason": str(context.get("decision_reason") or ""),
            "execution_decision": str(context.get("execution_decision") or ""),
            "model_used": model_used,
            "model_attempted": str(context.get("model_attempted") or strategy_fields.get("attempted") or ""),
            "failure_reason": str(context.get("failure_reason") or strategy_fields.get("failure_reason") or ""),
            "final_model_used": str(context.get("final_model_used") or strategy_fields.get("final_model") or model_used or "unknown"),
            "fallback_used": fallback_used,
            "policy_decision_id": str(context.get("policy_decision_id") or ""),
            "policy_decision": str(context.get("policy_decision") or ""),
            "policy_status_code": str(context.get("policy_status_code") or ""),
            "policy_triggered_rules": list(context.get("policy_triggered_rules") or []),
            "policy_hash_expected": expected,
            "policy_hash_runtime": runtime,
            "baseline_version": str(context.get("baseline_version") or "v1"),
            "commit_before": str(context.get("commit_before") or run.commit_before or "unknown"),
            "commit_after": str(context.get("commit_after") or run.commit_after or "unknown"),
            "trace_id": str(trace_id or context.get("trace_id") or ""),
            "request_id": str(request_id or context.get("request_id") or ""),
            "updated_at": _utcnow().isoformat(),
        }'''

    content = content.replace(old_preview, new_preview)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def refactor_provider_service():
    path = r"c:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator\tools\gimo_server\services\provider_service.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    old_invalidate = '''    @classmethod
    def _invalidate_caches_on_config_change(cls, before: Optional[ProviderConfig], cur_cfg: ProviderConfig) -> None:
        try:
            from .provider_catalog_service import ProviderCatalogService
            changed_types: set[str] = set()
            if before:
                all_ids = set(before.providers.keys()) | set(cur_cfg.providers.keys())
                for pid in all_ids:
                    prev = before.providers.get(pid)
                    cur = cur_cfg.providers.get(pid)
                    prev_type = None
                    if prev:
                        prev_type = cls.normalize_provider_type(prev.provider_type or prev.type)
                    cur_type = None
                    if cur:
                        cur_type = cls.normalize_provider_type(cur.provider_type or cur.type)
                    if prev_type:
                        changed_types.add(prev_type)
                    if cur_type:
                        changed_types.add(cur_type)
                    if prev and cur and (prev.auth_ref != cur.auth_ref or prev.auth_mode != cur.auth_mode):
                        if cur_type:
                            ProviderCatalogService.invalidate_cache(provider_type=cur_type, reason="credentials_changed")
            else:
                for entry in cur_cfg.providers.values():
                    changed_types.add(cls.normalize_provider_type(entry.provider_type or entry.type))

            # conservative safety net for first persist / broad changes
            for ctype in changed_types:
                ProviderCatalogService.invalidate_cache(provider_type=ctype, reason="provider_config_updated")
        except Exception:
            # cache invalidation should never block config persistence
            pass'''

    new_invalidate = '''    @classmethod
    def _get_changed_provider_types(cls, before: Optional[ProviderConfig], cur_cfg: ProviderConfig) -> set[str]:
        changed_types: set[str] = set()
        if not before:
            for entry in cur_cfg.providers.values():
                changed_types.add(cls.normalize_provider_type(entry.provider_type or entry.type))
            return changed_types

        all_ids = set(before.providers.keys()) | set(cur_cfg.providers.keys())
        for pid in all_ids:
            prev = before.providers.get(pid)
            cur = cur_cfg.providers.get(pid)
            
            prev_type = cls.normalize_provider_type(prev.provider_type or prev.type) if prev else None
            cur_type = cls.normalize_provider_type(cur.provider_type or cur.type) if cur else None
            
            if prev_type: changed_types.add(prev_type)
            if cur_type: changed_types.add(cur_type)
            
            if prev and cur and (prev.auth_ref != cur.auth_ref or prev.auth_mode != cur.auth_mode):
                if cur_type:
                    from .provider_catalog_service import ProviderCatalogService
                    ProviderCatalogService.invalidate_cache(provider_type=cur_type, reason="credentials_changed")
        
        return changed_types

    @classmethod
    def _invalidate_caches_on_config_change(cls, before: Optional[ProviderConfig], cur_cfg: ProviderConfig) -> None:
        try:
            from .provider_catalog_service import ProviderCatalogService
            changed_types = cls._get_changed_provider_types(before, cur_cfg)
            for ctype in changed_types:
                ProviderCatalogService.invalidate_cache(provider_type=ctype, reason="provider_config_updated")
        except Exception:
            pass'''

    content = content.replace(old_invalidate, new_invalidate)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    refactor_observability()
    refactor_ops_service()
    refactor_provider_service()
    print("Refactored final services")
