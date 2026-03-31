from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError, Field
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from ...ops_models import (
    WorkflowNode,
    UserEconomyConfig,
    MasteryStatus,
    BudgetForecast,
    CostAnalytics,
    PlanEconomySnapshot,
    PlanAutonomyUpdateRequest,
)
from ...services.model_router_service import ModelRouterService
from ...services.budget_forecast_service import BudgetForecastService


# F8.3: User feedback model
class UserFeedbackRequest(BaseModel):
    """Request model for user feedback."""
    score: float = Field(..., ge=1.0, le=5.0, description="User rating (1-5 stars)")
    comment: Optional[str] = Field(None, max_length=500, description="Optional user comment")

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
    OpsService.set_config(current_ops_config)
    
    return current_ops_config.economy


@router.get("/plans/{plan_id}/economy", response_model=PlanEconomySnapshot)
async def get_plan_economy_snapshot(
    plan_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
):
    """Return economy snapshot for a specific custom plan."""
    from ...services.storage_service import StorageService
    from ...services.custom_plan_service import CustomPlanService
    from ...services.ops_service import OpsService

    plan = CustomPlanService.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    cfg = OpsService.get_config()
    storage = StorageService(OpsService._gics)
    return storage.cost.get_plan_snapshot(
        plan_id=plan_id,
        status=plan.status,
        autonomy_level=cfg.economy.autonomy_level,
        days=days,
    )


@router.post("/plans/{plan_id}/autonomy", response_model=PlanEconomySnapshot)
async def update_plan_autonomy(
    plan_id: str,
    body: PlanAutonomyUpdateRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """Update autonomy level globally and optionally annotate selected node configs."""
    from ...services.custom_plan_service import CustomPlanService
    from ...services.ops_service import OpsService
    from ...services.storage_service import StorageService

    plan = CustomPlanService.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    cfg = OpsService.get_config()
    cfg.economy.autonomy_level = body.level
    OpsService.set_config(cfg)

    if body.node_ids:
        node_ids = set(body.node_ids)
        for node in plan.nodes:
            if node.id in node_ids:
                node.config = dict(node.config or {})
                node.config["autonomy_level"] = body.level
        plan.updated_at = datetime.now(timezone.utc)
        CustomPlanService._save(plan)

    storage = StorageService(OpsService._gics)
    return storage.cost.get_plan_snapshot(
        plan_id=plan_id,
        status=plan.status,
        autonomy_level=cfg.economy.autonomy_level,
        days=30,
    )


@router.post("/recommend", response_model=Dict[str, Any])
async def get_model_recommendations(
    node: WorkflowNode,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Returns Best vs Eco model recommendations for a node."""
    router_service = ModelRouterService()
    return router_service.promote_eco_mode(node)

@router.get("/hardware", response_model=Dict[str, Any])
async def get_hardware_status(auth: Annotated[AuthContext, Depends(verify_token)]):
    """Returns current hardware state and available model count."""
    from ...services.hardware_monitor_service import HardwareMonitorService
    from ...services.model_inventory_service import ModelInventoryService
    hw = HardwareMonitorService.get_instance()
    state = hw.get_current_state()
    models = ModelInventoryService.get_available_models()
    state["available_models"] = len(models)
    state["local_models"] = len([m for m in models if m.is_local])
    state["remote_models"] = len([m for m in models if not m.is_local])
    state["local_safe"] = hw.is_local_safe()
    return state


@router.get("/status", response_model=MasteryStatus)
async def get_mastery_status(auth: Annotated[AuthContext, Depends(verify_token)]):
    """Returns general token mastery metrics with real data."""
    import logging
    from ...services.ops_service import OpsService
    from ...services.storage_service import StorageService
    from ...services.hardware_monitor_service import HardwareMonitorService

    logger = logging.getLogger("orchestrator.mastery")
    config = OpsService.get_config()
    hw = HardwareMonitorService.get_instance()

    eco_mode_active = config.economy.eco_mode.mode != "off"
    savings, spend = 0.0, 0.0
    try:
        storage = StorageService()
        savings = storage.cost.get_total_savings(days=30)
        spend = storage.cost.get_total_spend(days=30)
    except Exception:
        logger.warning("StorageService unavailable for mastery status")

    efficiency = 0.0
    if (spend + savings) > 0:
        efficiency = round(savings / (spend + savings), 2)
    elif eco_mode_active:
        efficiency = 1.0

    alerts = []
    if config.economy.global_budget_usd:
        try:
            storage = StorageService()
            alerts = storage.cost.check_budget_alerts(
                config.economy.global_budget_usd,
                config.economy.alert_thresholds
            )
        except Exception:
            logger.warning("Budget alerts unavailable")

    tips = []
    for alert in alerts:
        tips.append(f"ALERTA: Has alcanzado el {alert['percentage']}% de tu presupuesto global.")

    if spend > 50:
         tips.append("Tu gasto global este mes es elevado (> $50). Revisa tus limites de provider.")

    hw_state = hw.get_load_level()
    if hw_state == "critical":
        tips.insert(0, "CARGA CRITICA: El sistema esta bajo mucha carga. Solo se usaran modelos remotos.")
    elif hw_state == "caution":
        tips.insert(0, "Carga elevada: GIMO esta limitando el uso de modelos locales grandes.")

    if eco_mode_active:
        tips.extend([
            "Eco-Mode esta activo: GIMO esta priorizando modelos economicos.",
            "Tus workflows actuales estan optimizados para el ahorro.",
            "Recuerda que los modelos locales no consumen creditos de nube."
        ])
    else:
        tips.extend([
            "Considera activar Eco-Mode para reducir costes hasta un 80% en tareas simples.",
            "GIMO sugiere modelos economicos para tareas de clasificacion."
        ])

    if not config.economy.allow_roi_routing:
        tips.append("Activa 'allow_roi_routing' para permitir que GIMO elija modelos por rendimiento real.")

    return {
        "eco_mode_enabled": eco_mode_active,
        "total_savings_usd": savings,
        "efficiency_score": efficiency,
        "hardware_state": hw_state,
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


@router.post("/predict", response_model=Dict[str, Any], responses={400: {"description": "Bad Request"}, 403: {"description": "Forbidden"}})
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
    days: Annotated[int, Query(ge=1, le=365)] = 30
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
    import logging
    from ...services.ops_service import OpsService
    from ...services.storage_service import StorageService

    logger = logging.getLogger("orchestrator.mastery")
    config = OpsService.get_config()

    try:
        storage = StorageService()
        forecaster = BudgetForecastService(storage)
        return forecaster.forecast(config.economy)
    except Exception:
        logger.warning("Forecast unavailable", exc_info=True)
        return []


# F8.3: User Feedback Endpoints


@router.post("/feedback/{workflow_id}/{node_id}", response_model=Dict[str, Any])
async def submit_feedback(
    workflow_id: str,
    node_id: str,
    feedback: UserFeedbackRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """Permite al usuario evaluar la calidad de un nodo ejecutado.

    El score se normaliza de 1-5 estrellas a 0-100 para consistencia interna.

    Args:
        workflow_id: ID del workflow/plan
        node_id: ID del nodo ejecutado
        feedback: Objeto con score (1-5) y comentario opcional

    Returns:
        Estado de la operación y score normalizado
    """
    from ...services.feedback_collector import FeedbackCollector

    # Convertir 1-5 a 0-100
    score_normalized = (feedback.score - 1) * 25.0  # 1→0, 5→100

    FeedbackCollector.record_user_feedback(
        workflow_id=workflow_id,
        node_id=node_id,
        feedback_score=score_normalized,
        feedback_text=feedback.comment,
    )

    return {
        "status": "recorded",
        "score_normalized": score_normalized,
        "workflow_id": workflow_id,
        "node_id": node_id,
    }


@router.get("/feedback/{workflow_id}/{node_id}", response_model=Dict[str, Any])
async def get_feedback(
    workflow_id: str,
    node_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """Obtiene el feedback del usuario para un nodo específico.

    Args:
        workflow_id: ID del workflow/plan
        node_id: ID del nodo

    Returns:
        Feedback registrado o 404 si no existe
    """
    from ...services.feedback_collector import FeedbackCollector

    feedback = FeedbackCollector.get_user_feedback(workflow_id, node_id)

    if not feedback:
        raise HTTPException(status_code=404, detail="No feedback found for this node")

    return feedback


@router.get("/preset-telemetry/{task_semantic}", response_model=List[Dict[str, Any]])
async def get_preset_telemetry_for_semantic(
    task_semantic: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """Obtiene telemetría de TODOS los presets para un semantic dado.

    Útil para dashboard de observabilidad del sistema de routing adaptativo.

    Args:
        task_semantic: Tipo de tarea semántica ("planning", "research", etc)

    Returns:
        Lista de telemetría de todos los presets para ese semantic
    """
    from ...services.preset_telemetry_service import PresetTelemetryService

    telemetry = PresetTelemetryService.get_all_for_semantic(task_semantic)

    return telemetry


@router.get(
    "/preset-telemetry/{task_semantic}/{preset_name}",
    response_model=Dict[str, Any],
)
async def get_preset_telemetry(
    task_semantic: str,
    preset_name: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """Obtiene telemetría de un preset específico para un semantic.

    Args:
        task_semantic: Tipo de tarea semántica
        preset_name: Nombre del preset

    Returns:
        Telemetría del preset o 404 si no existe
    """
    from ...services.preset_telemetry_service import PresetTelemetryService

    telemetry = PresetTelemetryService.get_telemetry(task_semantic, preset_name)

    if not telemetry:
        raise HTTPException(
            status_code=404,
            detail=f"No telemetry found for semantic={task_semantic}, preset={preset_name}",
        )

    return telemetry


# P9: Anomaly Detection & Auto-Downgrade Endpoints

@router.get("/anomalies")
async def get_anomalies(auth: Annotated[AuthContext, Depends(verify_token)]) -> Dict[str, Any]:
    """Obtiene lista de anomalías detectadas en preset performance.

    Returns:
        {
            "anomalies": [
                {
                    "preset": str,
                    "task_semantic": str,
                    "current_quality": float,
                    "baseline_mean": float,
                    "threshold": float,
                    "gap": float,
                    "severity": str,
                    ...
                },
                ...
            ],
            "count": int
        }
    """
    from ...services.anomaly_detection_service import AnomalyDetectionService

    anomalies = AnomalyDetectionService.detect_anomalies()

    return {
        "anomalies": anomalies,
        "count": len(anomalies),
    }


@router.get("/baselines/{task_semantic}/{preset_name}")
async def get_baseline(
    task_semantic: str,
    preset_name: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
) -> Dict[str, Any]:
    """Obtiene baseline estadístico (μ, σ) de un preset específico.

    Returns:
        {
            "task_semantic": str,
            "preset_name": str,
            "mean": float,
            "stdev": float,
            "samples": int,
            "confidence": str,
            "min_quality": float,
            "max_quality": float,
        }
        O 404 si no hay baseline confiable
    """
    from ...services.anomaly_detection_service import AnomalyDetectionService

    baseline = AnomalyDetectionService.compute_baseline(task_semantic, preset_name)

    if not baseline:
        raise HTTPException(
            status_code=404,
            detail=f"No baseline found for {preset_name} in {task_semantic} (insufficient data)",
        )

    return baseline


@router.get("/downgraded")
async def get_downgraded_presets(auth: Annotated[AuthContext, Depends(verify_token)]) -> Dict[str, Any]:
    """Lista presets actualmente auto-downgraded por failure_streak ≥ 5.

    Returns:
        {
            "downgraded": ["preset1", "preset2", ...],
            "count": int,
            "threshold": int  # failure_streak threshold
        }
    """
    from ...services.anomaly_detection_service import AnomalyDetectionService

    downgraded = AnomalyDetectionService.get_downgrade_list()

    return {
        "downgraded": downgraded,
        "count": len(downgraded),
        "threshold": AnomalyDetectionService.DOWNGRADE_FAILURE_STREAK,
    }
