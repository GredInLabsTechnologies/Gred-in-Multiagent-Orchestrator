"""Individual web search provider adapters — each returns List[WebSearchResult]."""
from __future__ import annotations

import logging
import os
import re
from typing import List
from urllib.parse import quote
from urllib.parse import unquote

import httpx

from ..models.web_search import WebSearchResult

logger = logging.getLogger("orchestrator.services.web_search_providers")
_HTTP_TIMEOUT = 10.0


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


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
            snippets = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</(?:td|div|span)>',
                resp.text,
                re.DOTALL,
            )
            for i, (url, title) in enumerate(links[:max_results]):
                clean_title = re.sub(r"<[^>]+>", "", title).strip()
                clean_snippet = re.sub(r"<[^>]+>", "", snippets[i] if i < len(snippets) else "").strip()
                actual_url = url
                if "uddg=" in url:
                    match = re.search(r"uddg=([^&]+)", url)
                    if match:
                        actual_url = unquote(match.group(1))
                results.append(
                    WebSearchResult(
                        title=clean_title,
                        url=actual_url,
                        snippet=clean_snippet,
                        provider="duckduckgo",
                        relevance_score=_clamp_score(1.0 - (i * 0.05)),
                        position=i,
                    )
                )
            return results
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
        return []


async def search_tavily(query: str, max_results: int = 10) -> List[WebSearchResult]:
    """Tavily Search API — LLM-optimized. Requires TAVILY_API_KEY env var."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                WebSearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "")[:500],
                    content=item.get("raw_content"),
                    provider="tavily",
                    relevance_score=_clamp_score(item.get("score", 0.5)),
                    position=i,
                )
                for i, item in enumerate(data.get("results", [])[:max_results])
            ]
    except Exception as exc:
        logger.warning("Tavily search failed: %s", exc)
        return []


async def search_jina(query: str, max_results: int = 10) -> List[WebSearchResult]:
    """Jina Search API — free tier available. Uses JINA_API_KEY if set."""
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("JINA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            encoded_query = quote(query, safe="")
            resp = await client.get(f"https://s.jina.ai/{encoded_query}", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [
                WebSearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", "")[:500],
                    content=item.get("content"),
                    provider="jina",
                    relevance_score=_clamp_score(1.0 - (i * 0.05)),
                    position=i,
                )
                for i, item in enumerate(data.get("data", [])[:max_results])
            ]
    except Exception as exc:
        logger.warning("Jina search failed: %s", exc)
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
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                WebSearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", "")[:500],
                    provider="brave",
                    relevance_score=_clamp_score(1.0 - (i * 0.04)),
                    position=i,
                )
                for i, item in enumerate(data.get("web", {}).get("results", [])[:max_results])
            ]
    except Exception as exc:
        logger.warning("Brave search failed: %s", exc)
        return []


async def search_exa(query: str, max_results: int = 10) -> List[WebSearchResult]:
    """Exa Neural Search API. Requires EXA_API_KEY."""
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                "https://api.exa.ai/search",
                json={
                    "query": query,
                    "num_results": max_results,
                    "use_autoprompt": True,
                },
                headers={"Content-Type": "application/json", "x-api-key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                WebSearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("text", "")[:500],
                    provider="exa",
                    relevance_score=_clamp_score(item.get("score", 0.5)),
                    position=i,
                )
                for i, item in enumerate(data.get("results", [])[:max_results])
            ]
    except Exception as exc:
        logger.warning("Exa search failed: %s", exc)
        return []


PROVIDER_REGISTRY = {
    "duckduckgo": search_duckduckgo,
    "tavily": search_tavily,
    "jina": search_jina,
    "brave": search_brave,
    "exa": search_exa,
}
