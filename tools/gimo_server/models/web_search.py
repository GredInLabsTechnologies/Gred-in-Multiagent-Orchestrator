"""Models for the parallel web search fusion engine."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


WebSearchProvider = Literal[
    "duckduckgo",
    "tavily",
    "jina",
    "brave",
    "exa",
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
