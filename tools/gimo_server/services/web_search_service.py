"""Parallel web search fusion — dispatches to multiple providers simultaneously."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Set, Tuple
from urllib.parse import urlparse

from ..models.web_search import (
    WebSearchFusionResponse,
    WebSearchProvider,
    WebSearchQuery,
    WebSearchResult,
)
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
                    asyncio.wait_for(
                        search_fn(query.query, query.max_results),
                        timeout=query.timeout_seconds,
                    )
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
            except Exception as exc:
                providers_failed.append(f"{provider}:{str(exc)[:50]}")

        fused, dedup_count = WebSearchService._fuse_results(all_results)
        elapsed_ms = (time.monotonic() - start) * 1000

        return WebSearchFusionResponse(
            query=query.query,
            results=fused[: query.max_results],
            providers_used=providers_used,
            providers_failed=providers_failed,
            total_results=len(fused),
            fusion_time_ms=round(elapsed_ms, 1),
            deduplicated_count=dedup_count,
        )

    @staticmethod
    def _fuse_results(results: List[WebSearchResult]) -> Tuple[List[WebSearchResult], int]:
        seen: Dict[str, WebSearchResult] = {}
        provider_counts: Dict[str, Set[str]] = {}
        dedup_count = 0

        for result in results:
            norm = WebSearchService._normalize_url(result.url)
            if norm in seen:
                dedup_count += 1
                provider_counts[norm].add(result.provider)
                existing = seen[norm]
                if result.content and not existing.content:
                    seen[norm] = result
                boost = len(provider_counts[norm]) * 0.1
                seen[norm].relevance_score = min(1.0, seen[norm].relevance_score + boost)
            else:
                seen[norm] = result
                provider_counts[norm] = {result.provider}

        return sorted(seen.values(), key=lambda item: item.relevance_score, reverse=True), dedup_count

    @staticmethod
    def _normalize_url(url: str) -> str:
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")
            path = parsed.path.rstrip("/")
            return f"{host}{path}"
        except Exception:
            return url.lower().strip("/")
