from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class QualityRating(BaseModel):
    score: int
    alerts: List[str] = Field(default_factory=list)
    heuristics: Dict[str, Any] = Field(default_factory=dict)


class ProviderBudget(BaseModel):
    provider: str
    max_cost_usd: Optional[float] = None
    period: Literal["daily", "weekly", "monthly", "total"] = "monthly"

    @field_validator("max_cost_usd")
    @classmethod
    def validate_max_cost(cls, v):
        if v is not None and v < 0:
            raise ValueError("max_cost_usd must be >= 0")
        return v

class CascadeConfig(BaseModel):
    enabled: bool = False
    min_tier: str = "local"
    max_tier: str = "opus"
    quality_threshold: int = 65
    max_escalations: int = 2

    @field_validator("quality_threshold")
    @classmethod
    def validate_quality(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError("quality_threshold must be between 0 and 100")
        return v

    @field_validator("max_escalations")
    @classmethod
    def validate_escalations(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_escalations must be >= 0")
        return v

class EcoModeConfig(BaseModel):
    mode: Literal["off", "binary", "smart"] = "off"
    floor_tier: str = "local"
    confidence_threshold_aggressive: float = 0.85
    confidence_threshold_moderate: float = 0.70

    @field_validator("confidence_threshold_aggressive", "confidence_threshold_moderate")
    @classmethod
    def validate_thresholds(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("Confidence thresholds must be between 0.0 and 1.0")
        return v

class UserEconomyConfig(BaseModel):
    autonomy_level: Literal["manual", "advisory", "guided", "autonomous"] = "manual"
    global_budget_usd: Optional[float] = None
    provider_budgets: List[ProviderBudget] = Field(default_factory=list)
    alert_thresholds: List[int] = Field(default_factory=lambda: [50, 25, 10])
    cascade: CascadeConfig = Field(default_factory=CascadeConfig)
    eco_mode: EcoModeConfig = Field(default_factory=EcoModeConfig)
    allow_roi_routing: bool = False
    model_floor: Optional[str] = None
    model_ceiling: Optional[str] = None
    cache_enabled: bool = False
    cache_ttl_hours: int = 24
    show_cost_predictions: bool = False
    provider_model_map: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    hardware_thresholds: Optional[Dict[str, Dict[str, int]]] = None
    allow_local_override: bool = False

    @field_validator("global_budget_usd")
    @classmethod
    def validate_budget(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("global_budget_usd must be >= 0")
        return v

    @field_validator("alert_thresholds")
    @classmethod
    def validate_alerts(cls, v: List[int]) -> List[int]:
        for t in v:
            if not (0 <= t <= 100):
                raise ValueError("Alert thresholds must be percentages between 0 and 100")
        return sorted(set(v), reverse=True)

    @field_validator("cache_ttl_hours")
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v < 0:
            raise ValueError("cache_ttl_hours must be >= 0")
        return v


class PlanAutonomyUpdateRequest(BaseModel):
    level: Literal["manual", "advisory", "guided", "autonomous"]
    node_ids: List[str] = Field(default_factory=list)

class CostEvent(BaseModel):
    id: str
    workflow_id: str
    node_id: str
    model: str
    provider: str
    task_type: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    quality_score: float = 0.0
    cascade_level: int = 0
    cache_hit: bool = False
    duration_ms: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class BudgetForecast(BaseModel):
    scope: str = "global"
    current_spend: float = 0.0
    limit: Optional[float] = None
    remaining: Optional[float] = None
    remaining_pct: Optional[float] = None
    burn_rate_hourly: float = 0.0
    hours_to_exhaustion: Optional[float] = None
    alert_level: Literal["none", "warning", "critical"] = "none"

class NodeEconomyMetrics(BaseModel):
    node_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    roi_score: float = 0.0
    roi_band: int = 1
    yield_optimized: bool = False
    model_used: Optional[str] = None
    provider_used: Optional[str] = None

class PlanEconomySnapshot(BaseModel):
    plan_id: str
    status: str = "draft"
    autonomy_level: Literal["manual", "advisory", "guided", "autonomous"] = "manual"
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_savings_usd: float = 0.0
    nodes_optimized: int = 0
    nodes: List[NodeEconomyMetrics] = Field(default_factory=list)

class CascadeResult(BaseModel):
    final_output: Any
    cascade_chain: List[Dict[str, Any]] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    savings: float = 0.0
    success: bool = True

class CascadeStatsEntry(BaseModel):
    task_type: str
    total_calls: int = 0
    cascaded_calls: int = 0
    avg_cascade_depth: float = 0.0
    total_spent: float = 0.0

class CacheStats(BaseModel):
    total_calls: int = 0
    cache_hits: int = 0
    hit_rate: float = 0.0
    estimated_savings_usd: float = 0.0

class RoiLeaderboardEntry(BaseModel):
    model: str
    task_type: str
    roi_score: float = 0.0
    avg_quality: float = 0.0
    avg_cost: float = 0.0
    sample_count: int = 0

class CostAnalytics(BaseModel):
    daily_costs: List[Dict[str, Any]] = Field(default_factory=list)
    by_model: List[Dict[str, Any]] = Field(default_factory=list)
    by_task_type: List[Dict[str, Any]] = Field(default_factory=list)
    by_provider: List[Dict[str, Any]] = Field(default_factory=list)
    roi_leaderboard: List[Dict[str, Any]] = Field(default_factory=list)
    cascade_stats: List[Dict[str, Any]] = Field(default_factory=list)
    cache_stats: Dict[str, Any] = Field(default_factory=dict)
    total_savings: float = 0.0

class MasteryStatus(BaseModel):
    eco_mode_enabled: bool
    total_savings_usd: float
    efficiency_score: float
    tips: List[str]
