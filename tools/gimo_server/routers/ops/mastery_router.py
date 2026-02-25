from typing import Annotated, Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from ...ops_models import WorkflowNode, UserEconomyConfig, MasteryStatus, BudgetForecast, CostAnalytics
from ...services.model_router_service import ModelRouterService
from ...services.budget_forecast_service import BudgetForecastService

router = APIRouter(prefix="/mastery", tags=["ops", "mastery"])

@router.get("/config/economy", response_model=UserEconomyConfig)
async def get_economy_config(auth: Annotated[AuthContext, Depends(verify_token)]):
    """Get current economy configuration."""
    from ...services.ops_service import OpsService
    config = OpsService.get_config()
    return config.economy


@router.post("/config/economy", response_model=UserEconomyConfig)
async def update_economy_config(
    economy_config: UserEconomyConfig,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Update economy configuration."""
    from ...services.ops_service import OpsService
    
    # Get current config
    current_ops_config = OpsService.get_config()
    
    # Update economy section
    current_ops_config.economy = economy_config
    
    # Save full config
    OpsService.save_config(current_ops_config)
    
    return current_ops_config.economy


@router.post("/recommend", response_model=Dict[str, Any])
async def get_model_recommendations(
    node: WorkflowNode,
    state: Dict[str, Any],
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Returns Best vs Eco model recommendations for a node."""
    router_service = ModelRouterService()
    return router_service.promote_eco_mode(node, state)

@router.get("/status", response_model=MasteryStatus)
async def get_mastery_status(auth: Annotated[AuthContext, Depends(verify_token)]):
    """Returns general token mastery metrics with real data."""
    from ...services.ops_service import OpsService
    from ...services.storage_service import StorageService
    
    config = OpsService.get_config()
    storage = StorageService()
    
    # Use new economy config for eco_mode status (check if not 'off')
    eco_mode_active = config.economy.eco_mode.mode != "off"
    
    # Real savings calculation
    savings = storage.cost.get_total_savings(days=30)
    spend = storage.cost.get_total_spend(days=30)
    
    # Efficiency calculation: savings / (spend + savings)
    efficiency = 0.0
    if (spend + savings) > 0:
        efficiency = round(savings / (spend + savings), 2)
    elif eco_mode_active:
        efficiency = 1.0 # Everything was free/cached
    
    # Budget Alerts
    alerts = []
    if config.economy.global_budget_usd:
        alerts = storage.cost.check_budget_alerts(
            config.economy.global_budget_usd, 
            config.economy.alert_thresholds
        )
    
    # Dynamic tips based on actual data
    tips = []
    for alert in alerts:
        tips.append(f"ALERTA: Has alcanzado el {alert['percentage']}% de tu presupuesto global.")
        
    if spend > 50:
         tips.append("Tu gasto global este mes es elevado (> $50). Revisa tus limites de provider.")
    
    if eco_mode_active:
        tips.extend([
            "Eco-Mode está activo: GIMO está priorizando modelos económicos.",
            "Tus workflows actuales están optimizados para el ahorro.",
            "Recuerda que los modelos locales no consumen créditos de nube."
        ])
    else:
        tips.extend([
            "Considera activar Eco-Mode para reducir costes hasta un 80% en tareas simples.",
            "GIMO sugiere modelos Haiku para tareas de clasificación para mayor eficiencia."
        ])
        
    if not config.economy.allow_roi_routing:
        tips.append("Activa 'allow_roi_routing' para permitir que GIMO elija modelos por rendimiento real.")

    return {
        "eco_mode_enabled": eco_mode_active,
        "total_savings_usd": savings,
        "efficiency_score": efficiency,
        "tips": tips[:5]
    }


@router.get("/recommendations", response_model=Dict[str, Any])
async def get_mastery_recommendations(
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Returns optimization suggestions based on learned ROI."""
    from ...services.storage_service import StorageService
    storage = StorageService()
    
    leaderboard = storage.cost.get_roi_leaderboard(days=30)
    
    recommendations = []
    # Identify task types where a cheaper model has high quality
    task_types = {r["task_type"] for r in leaderboard}
    
    for tt in task_types:
        entries = [r for r in leaderboard if r["task_type"] == tt and r["sample_count"] >= 10]
        if len(entries) < 2:
            continue
            
        # Best ROI vs Worst ROI (or simply high ROI cheap model)
        top_roi = entries[0]
        if top_roi["avg_quality"] >= 85 and top_roi["avg_cost"] < 0.01:
             recommendations.append({
                 "task_type": tt,
                 "suggested_model": top_roi["model"],
                 "reason": f"Logra {round(top_roi['avg_quality'], 1)}% calidad a un coste ínfimo (${round(top_roi['avg_cost'], 4)})."
             })

    return {
        "recommendations": recommendations,
        "learned_count": len(leaderboard)
    }


@router.post("/predict", response_model=Dict[str, Any])
async def predict_workflow_cost(
    request: Dict[str, Any],
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Predicts cost for a proposed workflow."""
    from ...services.ops_service import OpsService
    from ...services.cost_predictor import CostPredictor
    from ...ops_models import WorkflowNode

    nodes_data = request.get("nodes", [])
    state = request.get("initial_state", {})

    try:
        nodes = [WorkflowNode(**n) for n in nodes_data]
    except (ValidationError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid workflow node data: {str(exc)[:200]}")

    config = OpsService.get_config()
    if not config.economy.show_cost_predictions:
        raise HTTPException(status_code=403, detail="Cost predictions are disabled in economy settings.")

    predictor = CostPredictor()

    prediction = predictor.predict_workflow_cost(nodes, state, config.economy)
    return prediction


@router.get("/analytics", response_model=CostAnalytics)
async def get_mastery_analytics(
    auth: Annotated[AuthContext, Depends(verify_token)],
    days: int = Query(30, ge=1, le=365)
):
    """Returns detailed analytics for the dashboard."""
    from ...services.storage_service import StorageService
    storage = StorageService()

    return CostAnalytics(
        daily_costs=storage.cost.get_daily_costs(days),
        by_model=storage.cost.aggregate_by_model(days),
        by_task_type=storage.cost.aggregate_by_task_type(days),
        by_provider=storage.cost.aggregate_by_provider(days),
        roi_leaderboard=storage.cost.get_roi_leaderboard(days),
        cascade_stats=storage.cost.get_cascade_stats(days),
        cache_stats=storage.cost.get_cache_stats(days),
        total_savings=storage.cost.get_total_savings(days),
    )


@router.get("/forecast", response_model=List[BudgetForecast])
async def get_budget_forecast(auth: Annotated[AuthContext, Depends(verify_token)]):
    """Returns budget forecast global + per-provider."""
    from ...services.ops_service import OpsService
    from ...services.storage_service import StorageService
    
    config = OpsService.get_config()
    storage = StorageService()
    
    forecaster = BudgetForecastService(storage)
    return forecaster.forecast(config.economy)
