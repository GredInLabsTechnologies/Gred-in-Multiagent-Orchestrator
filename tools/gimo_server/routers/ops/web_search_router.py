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
