# GIMO Master Implementation Plan v2 — Production Executable

## Context

This plan covers ALL discoveries from the QA audit session. GIMO has critical missing models, no web search implementation, and no parent-child run lifecycle. Three agents execute this plan: ALPHA and BETA in parallel, GAMMA after both complete.

**Already done (DO NOT revert):** QualityRating, CircuitBreakerConfigModel, ToolEntry, CliDependency*, ProviderValidate*, ProviderModelInstall*, provider catalog update (29 providers), ops_models.py conversation model exports, RoleProfile fix.

**Still broken:** SubAgent and SubAgentConfig models are imported in `sub_agent_manager.py` line 7 but DO NOT EXIST anywhere. This is a runtime ImportError.

---

## Execution Order

```
┌─────────────────┐    ┌─────────────────┐
│  AGENT ALPHA    │    │  AGENT BETA     │
│  Wake-on-Demand │    │  Web Search     │
│  + SubAgent fix │    │  Fusion Engine  │
└────────┬────────┘    └────────┬────────┘
         │    (parallel)        │
         └──────────┬───────────┘
                    │
            ┌───────▼────────┐
            │  AGENT GAMMA   │
            │  Integration   │
            │  + Validation  │
            └────────────────┘
```

---

## AGENT ALPHA — Wake-on-Demand Multi-Agent + SubAgent Models

### Invocation
> "GIMO Implementation Plan. Agent ALPHA. Proceed."

### System Prompt

```
You are Agent ALPHA for the GIMO multi-agent orchestrator project.
Your mission is to implement the Wake-on-Demand multi-agent system AND fix the missing SubAgent/SubAgentConfig models.

ABSOLUTE RULES — VIOLATION OF ANY RULE INVALIDATES YOUR ENTIRE OUTPUT:
1. You ONLY create or modify the files listed in YOUR DELIVERABLES section. No other files.
2. You NEVER delete existing fields, methods, imports, or classes.
3. You NEVER rename existing symbols.
4. You follow EXACTLY the Pydantic patterns already in the codebase (BaseModel, Field, Optional, Literal).
5. You follow EXACTLY the async patterns already in RunWorker (asyncio.Event, asyncio.create_task).
6. You do NOT touch routers, __init__.py, ops_models.py, or main.py — Agent GAMMA owns those.
7. You do NOT touch any web search code — Agent BETA owns that.
8. You do NOT run tests or validation — Agent GAMMA handles that.
9. Every new status literal goes into the EXISTING OpsRunStatus Literal type in core.py.
10. Every new event must use NotificationService.publish(event_type, payload) — the existing pattern.
11. You MUST complete ALL deliverables. Partial delivery is not acceptable.
```

### DELIVERABLE 1: Create `tools/gimo_server/models/sub_agent.py`

**Why:** `sub_agent_manager.py` line 7 imports `from tools.gimo_server.models import SubAgent, SubAgentConfig` but these classes DO NOT EXIST. This is a runtime ImportError.

```python
"""Sub-agent lifecycle models."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SubAgentConfig(BaseModel):
    """Configuration for a sub-agent instance."""
    model: str = "qwen2.5-coder:3b"
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout_seconds: int = 300


class SubAgent(BaseModel):
    """Runtime state of a spawned sub-agent."""
    id: str
    parentId: str
    name: str = ""
    model: str = "qwen2.5-coder:3b"
    status: str = "starting"  # starting, idle, working, failed, terminated, offline
    config: SubAgentConfig = Field(default_factory=SubAgentConfig)
    worktreePath: Optional[str] = None
    description: str = ""
    currentTask: Optional[str] = None
    result: Optional[str] = None
```

**Validation:** These fields match EXACTLY what `sub_agent_manager.py` uses:
- Line 95-99: `SubAgentConfig(model=..., temperature=..., max_tokens=...)`
- Line 112-120: `SubAgent(id=..., parentId=..., name=..., model=..., status=..., config=..., worktreePath=...)`
- Line 138-146: `SubAgent(id=..., parentId=..., name=..., model=..., status=..., config=..., description=...)`
- Line 193: `agent.currentTask = task`
- Line 216: `agent.result = response`

### DELIVERABLE 2: Modify `tools/gimo_server/models/core.py`

**Change 1:** Add `"awaiting_subagents"` to `OpsRunStatus` (line 10-27). Insert after `"cancelled"` on line 15:

```python
OpsRunStatus = Literal[
    "pending",
    "running",
    "done",
    "error",
    "cancelled",
    "awaiting_subagents",
    "MERGE_LOCKED",
    # ... rest unchanged
]
```

**Change 2:** Add 3 fields to `OpsRun` class after `created_at` (line 90):

```python
    parent_run_id: Optional[str] = None
    child_run_ids: List[str] = Field(default_factory=list)
    awaiting_count: int = 0
```

**Change 3:** Add `ChildRunRequest` model after `OpsCreateRunRequest` (line 30):

```python
class ChildRunRequest(BaseModel):
    parent_run_id: str
    prompt: str
    context: Dict[str, Any] = Field(default_factory=dict)
    agent_profile: Optional[str] = None
```

### DELIVERABLE 3: Modify `tools/gimo_server/services/notification_service.py`

**Change:** Add critical event types at line 93-95. Change:

```python
is_critical = payload.get("critical", False) or event_type in (
    "system_degraded", "action_requires_approval", "security_alert",
)
```

To:

```python
is_critical = payload.get("critical", False) or event_type in (
    "system_degraded", "action_requires_approval", "security_alert",
    "child_run_completed", "all_children_completed",
)
```

### DELIVERABLE 4: Modify `tools/gimo_server/services/run_worker.py`

**Change 1:** Add import after line 23:

```python
from .notification_service import NotificationService
```

**Change 2:** Modify `_is_still_active` (line 112-114) to include new status:

```python
def _is_still_active(self, run_id: str) -> bool:
    run = OpsService.get_run(run_id)
    return run is not None and run.status in ("pending", "running", "awaiting_subagents")
```

**Change 3:** Add method after `_execute_run` (after line 454):

```python
async def _handle_child_completion(self, child_run_id: str) -> None:
    """Called when a child run finishes. Decrements parent counter and wakes if zero."""
    child_run = OpsService.get_run(child_run_id)
    if not child_run or not child_run.parent_run_id:
        return

    parent_run = OpsService.get_run(child_run.parent_run_id)
    if not parent_run:
        return

    await NotificationService.publish("child_run_completed", {
        "parent_run_id": parent_run.id,
        "child_run_id": child_run_id,
        "child_status": child_run.status,
        "critical": True,
    })

    parent_run.awaiting_count = max(0, parent_run.awaiting_count - 1)
    OpsService.append_log(
        parent_run.id, level="INFO",
        msg=f"Child {child_run_id} completed ({child_run.status}). Remaining: {parent_run.awaiting_count}"
    )

    if parent_run.awaiting_count == 0:
        OpsService.update_run_status(parent_run.id, "running", msg="All child runs completed. Resuming.")
        await NotificationService.publish("all_children_completed", {
            "parent_run_id": parent_run.id,
            "critical": True,
        })
        self.notify()
```

**Change 4:** Modify `_execute_run` finally block (line 443-454):

```python
async def _execute_run(self, run_id: str) -> None:
    try:
        from .engine_service import EngineService
        await EngineService.execute_run(run_id)
    except Exception:
        logger.exception("Failed to execute run %s via EngineService", run_id)
        try:
            OpsService.update_run_status(run_id, "error", msg="Internal engine error")
        except Exception:
            pass
    finally:
        self._running_ids.discard(run_id)
        run = OpsService.get_run(run_id)
        if run and run.parent_run_id and run.status in ("done", "error"):
            await self._handle_child_completion(run_id)
```

### DELIVERABLE 5: Create `tools/gimo_server/services/child_run_service.py`

```python
"""Service for spawning child OpsRuns from a parent run."""
from __future__ import annotations
import uuid
import logging
from typing import Any, Dict, List, Optional

from ..ops_models import OpsRun
from .ops_service import OpsService

logger = logging.getLogger("orchestrator.services.child_run")


class ChildRunService:
    """Manages parent-child OpsRun lifecycle."""

    @staticmethod
    def spawn_child(
        parent_run_id: str,
        prompt: str,
        context: Dict[str, Any] = None,
        agent_profile_role: Optional[str] = None,
    ) -> OpsRun:
        parent = OpsService.get_run(parent_run_id)
        if not parent:
            raise ValueError(f"Parent run {parent_run_id} not found")
        if parent.status not in ("running", "awaiting_subagents"):
            raise ValueError(f"Parent run {parent_run_id} not in spawnable state: {parent.status}")

        child_id = f"run_{uuid.uuid4().hex[:12]}"
        child = OpsRun(
            id=child_id,
            approved_id=parent.approved_id,
            status="pending",
            parent_run_id=parent_run_id,
            repo_id=parent.repo_id,
            draft_id=parent.draft_id,
        )

        OpsService._runs[child_id] = child
        parent.child_run_ids.append(child_id)
        parent.awaiting_count += 1

        OpsService.append_log(
            parent_run_id, level="INFO",
            msg=f"Spawned child run {child_id} (total children: {len(parent.child_run_ids)})"
        )
        return child

    @staticmethod
    def pause_parent(parent_run_id: str) -> None:
        parent = OpsService.get_run(parent_run_id)
        if not parent:
            raise ValueError(f"Parent run {parent_run_id} not found")
        if parent.awaiting_count == 0:
            raise ValueError("Cannot pause: no children pending")
        OpsService.update_run_status(
            parent_run_id, "awaiting_subagents",
            msg=f"Paused. Waiting for {parent.awaiting_count} child run(s)."
        )

    @staticmethod
    def get_children_status(parent_run_id: str) -> List[Dict[str, Any]]:
        parent = OpsService.get_run(parent_run_id)
        if not parent:
            return []
        result = []
        for cid in parent.child_run_ids:
            child = OpsService.get_run(cid)
            if child:
                result.append({
                    "id": child.id,
                    "status": child.status,
                    "started_at": child.started_at.isoformat() if child.started_at else None,
                })
        return result
```

### DELIVERABLE 6: Create `tools/gimo_server/engine/stages/subagent_gate.py`

```python
"""Pipeline stage that pauses a run when it has pending child runs."""
from __future__ import annotations
import logging
from ..contracts import StageInput, StageOutput

logger = logging.getLogger(__name__)


class SubagentGate:
    """Checks if run has pending children and halts (pauses) if so."""
    name = "subagent_gate"

    async def execute(self, input: StageInput) -> StageOutput:
        from ...services.ops_service import OpsService
        run = OpsService.get_run(input.run_id)
        if not run:
            return StageOutput(status="fail", error="Run not found")
        if run.awaiting_count > 0:
            OpsService.update_run_status(
                input.run_id, "awaiting_subagents",
                msg=f"Halting pipeline: {run.awaiting_count} child run(s) pending"
            )
            return StageOutput(
                status="halt",
                artifacts={"reason": "awaiting_subagents", "children": run.child_run_ids},
            )
        return StageOutput(status="continue")

    async def rollback(self, input: StageInput) -> None:
        pass
```

### AGENT ALPHA FILE MANIFEST (EXHAUSTIVE)

| # | File | Action | Purpose |
|---|------|--------|---------|
| 1 | `tools/gimo_server/models/sub_agent.py` | CREATE | Fix missing SubAgent/SubAgentConfig models |
| 2 | `tools/gimo_server/models/core.py` | MODIFY | Add awaiting_subagents status, OpsRun fields, ChildRunRequest |
| 3 | `tools/gimo_server/services/notification_service.py` | MODIFY | Add critical event types |
| 4 | `tools/gimo_server/services/run_worker.py` | MODIFY | Add child completion handler, modify _execute_run |
| 5 | `tools/gimo_server/services/child_run_service.py` | CREATE | Parent-child lifecycle service |
| 6 | `tools/gimo_server/engine/stages/subagent_gate.py` | CREATE | Pipeline halt stage for child waits |

---

## AGENT BETA — Parallel Web Search Fusion Engine

### Invocation
> "GIMO Implementation Plan. Agent BETA. Proceed."

### System Prompt

```
You are Agent BETA for the GIMO multi-agent orchestrator project.
Your mission is to implement the Parallel Web Search Fusion Engine.

ABSOLUTE RULES — VIOLATION OF ANY RULE INVALIDATES YOUR ENTIRE OUTPUT:
1. You ONLY create the files listed in YOUR DELIVERABLES section. No other files.
2. You NEVER modify any existing file — Agent GAMMA owns all modifications.
3. You follow EXACTLY the Pydantic BaseModel patterns from the codebase (see examples in tools/gimo_server/models/*.py).
4. You follow EXACTLY the async patterns (asyncio.gather, asyncio.wait_for, asyncio.create_task).
5. All HTTP calls use httpx.AsyncClient (already a dependency).
6. All providers MUST be optional — if API key is missing, skip silently and return [].
7. DuckDuckGo requires NO API key and MUST always be available as fallback.
8. You do NOT touch any multi-agent, OpsRun, or pipeline code — Agent ALPHA owns that.
9. You do NOT touch routers, __init__.py, ops_models.py, or main.py — Agent GAMMA owns those.
10. You do NOT run tests or validation — Agent GAMMA handles that.
11. You MUST complete ALL deliverables. Partial delivery is not acceptable.

PROVIDER API REFERENCE (verified March 2026):
- DuckDuckGo: GET https://html.duckduckgo.com/html/ (params: q=query) — free, no key, parse HTML results
- Tavily: POST https://api.tavily.com/search (json: api_key, query, max_results, search_depth) — env: TAVILY_API_KEY
- Jina: GET https://s.jina.ai/{query} (header: Accept: application/json, opt Bearer JINA_API_KEY) — free tier 100 RPM
- Brave: GET https://api.search.brave.com/res/v1/web/search (params: q, count; header: X-Subscription-Token) — env: BRAVE_API_KEY
- Exa: POST https://api.exa.ai/search (json: query, num_results; header: x-api-key) — env: EXA_API_KEY
```

### DELIVERABLE 1: Create `tools/gimo_server/models/web_search.py`

```python
"""Models for the parallel web search fusion engine."""
from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

WebSearchProvider = Literal[
    "duckduckgo", "tavily", "jina", "brave", "exa",
]


class WebSearchQuery(BaseModel):
    query: str
    max_results: int = Field(default=10, ge=1, le=50)
    providers: List[WebSearchProvider] = Field(default_factory=lambda: ["duckduckgo"])
    include_content: bool = False
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)


class WebSearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    content: Optional[str] = None
    provider: WebSearchProvider
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    position: int = 0


class WebSearchFusionResponse(BaseModel):
    query: str
    results: List[WebSearchResult] = Field(default_factory=list)
    providers_used: List[WebSearchProvider] = Field(default_factory=list)
    providers_failed: List[str] = Field(default_factory=list)
    total_results: int = 0
    fusion_time_ms: float = 0.0
    deduplicated_count: int = 0
```

### DELIVERABLE 2: Create `tools/gimo_server/services/web_search_providers.py`

```python
"""Individual web search provider adapters — each returns List[WebSearchResult]."""
from __future__ import annotations
import logging
import os
import re
from typing import List
from urllib.parse import unquote
import httpx

from ..models.web_search import WebSearchResult

logger = logging.getLogger("orchestrator.services.web_search_providers")
_HTTP_TIMEOUT = 10.0


async def search_duckduckgo(query: str, max_results: int = 10) -> List[WebSearchResult]:
    """DuckDuckGo HTML search — always free, no API key required."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "GIMO-Agent/1.0"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            results = []
            links = re.findall(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', resp.text)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:td|div|span)>', resp.text, re.DOTALL)
            for i, (url, title) in enumerate(links[:max_results]):
                clean_title = re.sub(r"<[^>]+>", "", title).strip()
                clean_snippet = re.sub(r"<[^>]+>", "", snippets[i] if i < len(snippets) else "").strip()
                actual_url = url
                if "uddg=" in url:
                    m = re.search(r"uddg=([^&]+)", url)
                    if m:
                        actual_url = unquote(m.group(1))
                results.append(WebSearchResult(
                    title=clean_title, url=actual_url, snippet=clean_snippet,
                    provider="duckduckgo", relevance_score=1.0 - (i * 0.05), position=i,
                ))
            return results
    except Exception as e:
        logger.warning("DuckDuckGo search failed: %s", e)
        return []


async def search_tavily(query: str, max_results: int = 10) -> List[WebSearchResult]:
    """Tavily Search API — LLM-optimized. Requires TAVILY_API_KEY env var."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post("https://api.tavily.com/search", json={
                "api_key": api_key, "query": query, "max_results": max_results,
                "search_depth": "advanced", "include_answer": True,
            })
            resp.raise_for_status()
            data = resp.json()
            return [
                WebSearchResult(
                    title=item.get("title", ""), url=item.get("url", ""),
                    snippet=item.get("content", "")[:500], content=item.get("raw_content"),
                    provider="tavily", relevance_score=item.get("score", 0.5), position=i,
                )
                for i, item in enumerate(data.get("results", [])[:max_results])
            ]
    except Exception as e:
        logger.warning("Tavily search failed: %s", e)
        return []


async def search_jina(query: str, max_results: int = 10) -> List[WebSearchResult]:
    """Jina Search API — free tier available. Uses JINA_API_KEY if set."""
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("JINA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(f"https://s.jina.ai/{query}", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [
                WebSearchResult(
                    title=item.get("title", ""), url=item.get("url", ""),
                    snippet=item.get("description", "")[:500], content=item.get("content"),
                    provider="jina", relevance_score=1.0 - (i * 0.05), position=i,
                )
                for i, item in enumerate(data.get("data", [])[:max_results])
            ]
    except Exception as e:
        logger.warning("Jina search failed: %s", e)
        return []


async def search_brave(query: str, max_results: int = 10) -> List[WebSearchResult]:
    """Brave Search API — 2000 free queries/month. Requires BRAVE_API_KEY."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": min(max_results, 20)},
                headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                WebSearchResult(
                    title=item.get("title", ""), url=item.get("url", ""),
                    snippet=item.get("description", "")[:500],
                    provider="brave", relevance_score=1.0 - (i * 0.04), position=i,
                )
                for i, item in enumerate(data.get("web", {}).get("results", [])[:max_results])
            ]
    except Exception as e:
        logger.warning("Brave search failed: %s", e)
        return []


async def search_exa(query: str, max_results: int = 10) -> List[WebSearchResult]:
    """Exa Neural Search API. Requires EXA_API_KEY."""
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post("https://api.exa.ai/search", json={
                "query": query, "num_results": max_results, "use_autoprompt": True,
            }, headers={"Content-Type": "application/json", "x-api-key": api_key})
            resp.raise_for_status()
            data = resp.json()
            return [
                WebSearchResult(
                    title=item.get("title", ""), url=item.get("url", ""),
                    snippet=item.get("text", "")[:500],
                    provider="exa", relevance_score=item.get("score", 0.5), position=i,
                )
                for i, item in enumerate(data.get("results", [])[:max_results])
            ]
    except Exception as e:
        logger.warning("Exa search failed: %s", e)
        return []


PROVIDER_REGISTRY = {
    "duckduckgo": search_duckduckgo,
    "tavily": search_tavily,
    "jina": search_jina,
    "brave": search_brave,
    "exa": search_exa,
}
```

### DELIVERABLE 3: Create `tools/gimo_server/services/web_search_service.py`

```python
"""Parallel web search fusion — dispatches to multiple providers simultaneously."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, List, Set
from urllib.parse import urlparse

from ..models.web_search import WebSearchQuery, WebSearchResult, WebSearchFusionResponse, WebSearchProvider
from .web_search_providers import PROVIDER_REGISTRY

logger = logging.getLogger("orchestrator.services.web_search")


class WebSearchService:
    """Parallel multi-provider web search with result fusion and cross-reference ranking."""

    @staticmethod
    async def search(query: WebSearchQuery) -> WebSearchFusionResponse:
        start = time.monotonic()
        providers = list(query.providers or ["duckduckgo"])
        if "duckduckgo" not in providers:
            providers.append("duckduckgo")

        tasks = {}
        for provider in providers:
            search_fn = PROVIDER_REGISTRY.get(provider)
            if search_fn:
                tasks[provider] = asyncio.create_task(
                    asyncio.wait_for(search_fn(query.query, query.max_results), timeout=query.timeout_seconds)
                )

        all_results: List[WebSearchResult] = []
        providers_used: List[WebSearchProvider] = []
        providers_failed: List[str] = []

        for provider, task in tasks.items():
            try:
                results = await task
                if results:
                    all_results.extend(results)
                    providers_used.append(provider)
                else:
                    providers_failed.append(f"{provider}:empty")
            except asyncio.TimeoutError:
                providers_failed.append(f"{provider}:timeout")
            except Exception as e:
                providers_failed.append(f"{provider}:{str(e)[:50]}")

        fused, dedup_count = WebSearchService._fuse_results(all_results)
        elapsed_ms = (time.monotonic() - start) * 1000

        return WebSearchFusionResponse(
            query=query.query,
            results=fused[:query.max_results],
            providers_used=providers_used,
            providers_failed=providers_failed,
            total_results=len(fused),
            fusion_time_ms=round(elapsed_ms, 1),
            deduplicated_count=dedup_count,
        )

    @staticmethod
    def _fuse_results(results: List[WebSearchResult]) -> tuple[List[WebSearchResult], int]:
        seen: Dict[str, WebSearchResult] = {}
        provider_counts: Dict[str, Set[str]] = {}
        dedup_count = 0

        for r in results:
            norm = WebSearchService._normalize_url(r.url)
            if norm in seen:
                dedup_count += 1
                provider_counts[norm].add(r.provider)
                existing = seen[norm]
                if r.content and not existing.content:
                    seen[norm] = r
                boost = len(provider_counts[norm]) * 0.1
                seen[norm].relevance_score = min(1.0, seen[norm].relevance_score + boost)
            else:
                seen[norm] = r
                provider_counts[norm] = {r.provider}

        return sorted(seen.values(), key=lambda x: x.relevance_score, reverse=True), dedup_count

    @staticmethod
    def _normalize_url(url: str) -> str:
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")
            path = parsed.path.rstrip("/")
            return f"{host}{path}"
        except Exception:
            return url.lower().strip("/")
```

### DELIVERABLE 4: Create `tools/gimo_server/services/web_search_content_extractor.py`

```python
"""Content extraction — fetches and cleans page content for search results."""
from __future__ import annotations
import asyncio
import logging
import re
from typing import List
import httpx

from ..models.web_search import WebSearchResult

logger = logging.getLogger("orchestrator.services.web_search_content")
_EXTRACT_TIMEOUT = 8.0
_MAX_CONTENT_LENGTH = 5000


async def extract_content_for_results(
    results: List[WebSearchResult], max_concurrent: int = 5,
) -> List[WebSearchResult]:
    sem = asyncio.Semaphore(max_concurrent)

    async def _fetch_one(result: WebSearchResult) -> WebSearchResult:
        if result.content:
            return result
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=_EXTRACT_TIMEOUT, follow_redirects=True) as client:
                    resp = await client.get(result.url, headers={"User-Agent": "GIMO-Agent/1.0"})
                    resp.raise_for_status()
                    result.content = _clean_html(resp.text)[:_MAX_CONTENT_LENGTH]
            except Exception as e:
                logger.debug("Content extraction failed for %s: %s", result.url, e)
            return result

    return await asyncio.gather(*[_fetch_one(r) for r in results])


def _clean_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()
```

### AGENT BETA FILE MANIFEST (EXHAUSTIVE)

| # | File | Action | Purpose |
|---|------|--------|---------|
| 1 | `tools/gimo_server/models/web_search.py` | CREATE | Search query/result/response models |
| 2 | `tools/gimo_server/services/web_search_providers.py` | CREATE | 5 provider adapters (DDG, Tavily, Jina, Brave, Exa) |
| 3 | `tools/gimo_server/services/web_search_service.py` | CREATE | Parallel fusion service with dedup + cross-reference ranking |
| 4 | `tools/gimo_server/services/web_search_content_extractor.py` | CREATE | HTML content extraction pipeline |

---

## AGENT GAMMA — Integration, Exports, Routers & Validation

### Invocation
> "GIMO Implementation Plan. Agent GAMMA. Proceed."

### System Prompt

```
You are Agent GAMMA for the GIMO multi-agent orchestrator project.
Your mission is to integrate Agent ALPHA and Agent BETA's deliverables: wire exports, create routers, register compositions, and validate ALL imports.

ABSOLUTE RULES — VIOLATION OF ANY RULE INVALIDATES YOUR ENTIRE OUTPUT:
1. You ONLY modify or create the files listed in YOUR DELIVERABLES section.
2. You NEVER change business logic in services — only imports, exports, and router wiring.
3. You follow the EXACT import pattern in ops_models.py: try absolute / except relative, BOTH blocks must be IDENTICAL.
4. You follow the EXACT router pattern: FastAPI APIRouter with prefix and tags.
5. You follow the EXACT router mounting pattern from ops_routes.py: router.include_router(xxx_router.router).
6. After ALL changes, you run the validation commands in DELIVERABLE 8. If ANY fails, you fix it before declaring done.
7. You MUST complete ALL deliverables. Partial delivery is not acceptable.

CRITICAL CONTEXT:
- Router mounting for /ops sub-routers: done in tools/gimo_server/ops_routes.py via router.include_router()
- Router mounting for top-level routers: done in tools/gimo_server/main.py via app.include_router()
- MCP tools: registered in tools/gimo_server/mcp_bridge/native_tools.py inside register_native_tools(mcp)
- Engine compositions: registered in tools/gimo_server/services/engine_service.py _COMPOSITION_MAP dict
- Models export chain: models/*.py → models/__init__.py → ops_models.py (both try/except blocks)

FILES CREATED BY AGENT ALPHA (you must wire these):
- tools/gimo_server/models/sub_agent.py (exports: SubAgent, SubAgentConfig)
- tools/gimo_server/models/core.py (new exports: ChildRunRequest; modified: OpsRunStatus, OpsRun)
- tools/gimo_server/services/child_run_service.py (exports: ChildRunService)
- tools/gimo_server/engine/stages/subagent_gate.py (exports: SubagentGate)

FILES CREATED BY AGENT BETA (you must wire these):
- tools/gimo_server/models/web_search.py (exports: WebSearchProvider, WebSearchQuery, WebSearchResult, WebSearchFusionResponse)
- tools/gimo_server/services/web_search_service.py (exports: WebSearchService)
- tools/gimo_server/services/web_search_content_extractor.py (exports: extract_content_for_results)
```

### DELIVERABLE 1: Modify `tools/gimo_server/models/__init__.py`

Add SubAgent imports BEFORE the existing `from .core` block (new first import):

```python
from .sub_agent import SubAgent, SubAgentConfig
```

Add `ChildRunRequest` to the existing `from .core import (...)` block.

Add web_search imports after the `from .eval import (...)` block:

```python
from .web_search import (
    WebSearchProvider, WebSearchQuery, WebSearchResult, WebSearchFusionResponse,
)
```

### DELIVERABLE 2: Modify `tools/gimo_server/ops_models.py`

Add to BOTH try and except import blocks (keep blocks identical):

In the first import group (core models), add `ChildRunRequest`:
```python
OpsApproveResponse, OpsCreateRunRequest, ChildRunRequest, RepoEntry, RunEvent, RunLogEntry,
```

Add `SubAgent, SubAgentConfig` somewhere in the import list.

Add at the end of the import list:
```python
WebSearchProvider, WebSearchQuery, WebSearchResult, WebSearchFusionResponse,
```

**BOTH blocks must be identical.**

### DELIVERABLE 3: Create `tools/gimo_server/routers/ops/web_search_router.py`

```python
"""API router for parallel web search."""
from __future__ import annotations
from fastapi import APIRouter
from ...models.web_search import WebSearchQuery, WebSearchFusionResponse
from ...services.web_search_service import WebSearchService
from ...services.web_search_content_extractor import extract_content_for_results

router = APIRouter(prefix="/search", tags=["web-search"])


@router.post("/web", response_model=WebSearchFusionResponse)
async def search(query: WebSearchQuery):
    response = await WebSearchService.search(query)
    if query.include_content and response.results:
        response.results = await extract_content_for_results(response.results)
    return response
```

### DELIVERABLE 4: Create `tools/gimo_server/routers/ops/child_run_router.py`

```python
"""API router for child run management (wake-on-demand)."""
from __future__ import annotations
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
from ...models.core import ChildRunRequest
from ...services.child_run_service import ChildRunService

router = APIRouter(prefix="/child-runs", tags=["child-runs"])


@router.post("/spawn", response_model=Dict[str, Any])
async def spawn_child(req: ChildRunRequest):
    try:
        child = ChildRunService.spawn_child(
            parent_run_id=req.parent_run_id, prompt=req.prompt,
            context=req.context, agent_profile_role=req.agent_profile,
        )
        return {"child_run_id": child.id, "status": child.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{parent_run_id}/pause")
async def pause_parent(parent_run_id: str):
    try:
        ChildRunService.pause_parent(parent_run_id)
        return {"status": "awaiting_subagents"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{parent_run_id}/children")
async def get_children(parent_run_id: str):
    return ChildRunService.get_children_status(parent_run_id)
```

### DELIVERABLE 5: Modify `tools/gimo_server/ops_routes.py`

Add imports at line 8-10 (inside the `from .routers.ops import (...)` block):

```python
from .routers.ops import (
    plan_router, run_router, eval_router, trust_router, config_router, observability_router,
    mastery_router, skills_router, custom_plan_router, conversation_router, hitl_router,
    provider_auth_router, catalog_router, tools_router, policy_router, dependencies_router,
    web_search_router, child_run_router,
)
```

Add router mounting after line 30:

```python
router.include_router(web_search_router.router)
router.include_router(child_run_router.router)
```

### DELIVERABLE 6: Modify `tools/gimo_server/services/engine_service.py`

Add to `_COMPOSITION_MAP` dict (after "slice0" entry, before the closing `}`):

```python
"multi_agent": [
    "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
    "tools.gimo_server.engine.stages.risk_gate:RiskGate",
    "tools.gimo_server.engine.stages.plan_stage:PlanStage",
    "tools.gimo_server.engine.stages.llm_execute:LlmExecute",
    "tools.gimo_server.engine.stages.subagent_gate:SubagentGate",
],
```

### DELIVERABLE 7: Modify `tools/gimo_server/mcp_bridge/native_tools.py`

Add inside `register_native_tools(mcp)`, after the existing `gimo_list_agents` tool (before `logger.info("Registered Native Tools")`):

```python
@mcp.tool()
async def gimo_web_search(query: str, providers: str = "duckduckgo", max_results: int = 10) -> str:
    """Search the web using GIMO's parallel multi-provider search engine.
    providers: comma-separated list from: duckduckgo,tavily,jina,brave,exa"""
    try:
        from tools.gimo_server.models.web_search import WebSearchQuery
        from tools.gimo_server.services.web_search_service import WebSearchService
        provider_list = [p.strip() for p in providers.split(",") if p.strip()]
        q = WebSearchQuery(query=query, providers=provider_list, max_results=max_results, include_content=True)
        response = await WebSearchService.search(q)
        if response.results:
            from tools.gimo_server.services.web_search_content_extractor import extract_content_for_results
            response.results = await extract_content_for_results(response.results[:5])
        lines = [f"Search: {response.query} ({response.fusion_time_ms:.0f}ms, {len(response.providers_used)} providers)"]
        for r in response.results[:max_results]:
            lines.append(f"\n--- {r.title} ---\nURL: {r.url}\nScore: {r.relevance_score:.2f} ({r.provider})")
            if r.content:
                lines.append(r.content[:1000])
            elif r.snippet:
                lines.append(r.snippet)
        if response.providers_failed:
            lines.append(f"\nFailed: {', '.join(response.providers_failed)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"
```

### DELIVERABLE 8: Validation (MANDATORY — run in order, fix until ALL pass)

```bash
# 1. SubAgent models (was broken before this plan)
python -c "from tools.gimo_server.models.sub_agent import SubAgent, SubAgentConfig; print('OK: sub_agent models')"

# 2. All model exports
python -c "from tools.gimo_server.ops_models import *; print('OK: ops_models')"

# 3. SubAgentManager (was crashing due to missing SubAgent)
python -c "from tools.gimo_server.services.sub_agent_manager import SubAgentManager; print('OK: sub_agent_manager')"

# 4. Web search service
python -c "from tools.gimo_server.services.web_search_service import WebSearchService; print('OK: web_search')"

# 5. Child run service
python -c "from tools.gimo_server.services.child_run_service import ChildRunService; print('OK: child_run')"

# 6. New routers
python -c "from tools.gimo_server.routers.ops.web_search_router import router; print('OK: web_search_router')"
python -c "from tools.gimo_server.routers.ops.child_run_router import router; print('OK: child_run_router')"

# 7. Engine composition
python -c "from tools.gimo_server.services.engine_service import EngineService; assert 'multi_agent' in EngineService._COMPOSITION_MAP; print('OK: multi_agent composition')"

# 8. Full ops_routes import
python -c "from tools.gimo_server.ops_routes import router; print('OK: ops_routes')"
```

### AGENT GAMMA FILE MANIFEST (EXHAUSTIVE)

| # | File | Action | Purpose |
|---|------|--------|---------|
| 1 | `tools/gimo_server/models/__init__.py` | MODIFY | Add SubAgent, SubAgentConfig, ChildRunRequest, web_search exports |
| 2 | `tools/gimo_server/ops_models.py` | MODIFY | Add all new models to BOTH import blocks |
| 3 | `tools/gimo_server/routers/ops/web_search_router.py` | CREATE | Web search API endpoint |
| 4 | `tools/gimo_server/routers/ops/child_run_router.py` | CREATE | Child run management API endpoints |
| 5 | `tools/gimo_server/ops_routes.py` | MODIFY | Mount new routers |
| 6 | `tools/gimo_server/services/engine_service.py` | MODIFY | Register multi_agent composition |
| 7 | `tools/gimo_server/mcp_bridge/native_tools.py` | MODIFY | Register gimo_web_search MCP tool |
| 8 | Run validation commands | RUN | All 8 checks must pass |

---

## GLOBAL CONSTRAINTS (ALL AGENTS)

1. **File ownership is exclusive.** No file may be modified by more than one agent. Cross-check your manifest against the other agents' manifests.
2. **No new dependencies.** `httpx`, `pydantic`, `fastapi`, `asyncio` are all already available.
3. **No changes to existing tests.**
4. **No changes to provider_catalog_service_impl.py** (already updated).
5. **No changes to existing model fields.** Only additions.
6. **Execution order:** ALPHA and BETA run in parallel → GAMMA runs after both.
7. **Every new Pydantic model MUST appear in:** (a) its `models/*.py` file, (b) `models/__init__.py`, (c) `ops_models.py` both import blocks.
8. **`StageOutput(status="halt")`** is a clean pipeline pause — no rollback triggered (confirmed in `pipeline.py` lines 78-79).
9. **All async events use `await NotificationService.publish()`** — never synchronous.
10. **DuckDuckGo is the ONLY mandatory search provider.** All others are API-key gated.
11. **SubAgent and SubAgentConfig** must match the usage in `sub_agent_manager.py` exactly (fields verified against lines 95-120, 138-149, 193, 216).

---

## PROVIDER CATALOG REFERENCE (2026 Free Tiers for Agentic Code)

Already implemented in `provider_catalog_service_impl.py`. This reference is for agents that need provider context:

| Provider | Free Model IDs | Tool Calling | List Endpoint |
|----------|---------------|-------------|---------------|
| OpenRouter | `*:free` suffix models | Yes (OpenAI-compat) | `GET /api/v1/models` |
| Groq | llama-3.3-70b-versatile, llama-3.1-8b-instant | Yes | `GET /openai/v1/models` |
| Google | gemini-2.5-flash, gemini-2.0-flash | Yes (functionDeclarations) | `GET /v1beta/models` |
| DeepSeek | deepseek-chat (V3), deepseek-reasoner | Yes (OpenAI-compat) | `GET /models` |
| Together | llama-3.3-70b-instruct-turbo-free | Yes | `GET /v1/models` |
| Fireworks | $1 credit models | Yes | `GET /inference/v1/models` |
| HuggingFace | Qwen2.5-Coder-32B-Instruct | No native | Hub API |
| Mistral | codestral-latest, open-mistral-nemo | Yes (some models) | `GET /v1/models` |
| Cohere | command-a-03-2025 (trial key) | Yes (first-class) | SDK `models.list()` |
| Qwen/DashScope | qwen2.5-coder-32b-instruct | Yes | `GET /compatible-mode/v1/models` |
| Ollama | qwen2.5-coder:32b (local, no limit) | Application-level | `GET /api/tags` |
| ZAI | glm-4-flash (10M tokens/month free) | Yes | OpenAI-compat |

---

## COMPLETE FILE OWNERSHIP MAP

```
AGENT ALPHA owns:
  CREATE: models/sub_agent.py, services/child_run_service.py, engine/stages/subagent_gate.py
  MODIFY: models/core.py, services/notification_service.py, services/run_worker.py

AGENT BETA owns:
  CREATE: models/web_search.py, services/web_search_providers.py, services/web_search_service.py, services/web_search_content_extractor.py

AGENT GAMMA owns:
  CREATE: routers/ops/web_search_router.py, routers/ops/child_run_router.py
  MODIFY: models/__init__.py, ops_models.py, ops_routes.py, services/engine_service.py, mcp_bridge/native_tools.py
  RUN: validation commands
```

Total: **10 new files, 8 modified files, 0 new dependencies.**
