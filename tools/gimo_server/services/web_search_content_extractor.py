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
    results: List[WebSearchResult],
    max_concurrent: int = 5,
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
            except Exception as exc:
                logger.debug("Content extraction failed for %s: %s", result.url, exc)
            return result

    return await asyncio.gather(*[_fetch_one(r) for r in results])


def _clean_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()
