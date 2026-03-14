# GIMO Server — Refactor Architecture Plan

> Estado: BORRADOR — Generado 2026-03-14
> Urgencia: Producción HOY

---

## Diagnóstico en una frase

70+ servicios, 6 rutas de ejecución independientes, 3 sistemas de decisión duplicados, y regex frágil para detectar archivos. Todo para hacer una sola cosa: **tomar un prompt, ejecutarlo de forma segura, producir artefactos.**

---

## 1. Problemas Estructurales Confirmados

### 6 Rutas de Ejecución (todas distintas, sin contrato compartido)

| # | Ruta | Archivo principal |
|---|------|-------------------|
| 1 | MergeGate → Git pipeline (high-risk) | `merge_gate_service.py` |
| 2 | RunWorker → `_execute_structured_plan` (JSON plan) | `run_worker.py` |
| 3 | RunWorker → `_execute_file_task` (regex + LLM) | `run_worker.py` |
| 4 | RunWorker → `_handle_legacy_execution` (LLM + critic) | `run_worker.py` |
| 5 | CustomPlanService → DAG topológico | `custom_plan_service.py` |
| 6 | Slice0Orchestrator → LangGraph-style pipeline | `slice0_orchestrator.py` |
| + | GraphEngine → workflow execution | `graph_engine.py` |

### 3 Sistemas de Decisión Duplicados

- `IntentClassificationService.evaluate()` — en creación de draft
- `RuntimePolicyService.evaluate_draft_policy()` — en creación de draft
- `MergeGateService._validate_risk()` + `._validate_policy()` — re-evalúa lo mismo en ejecución

### Otros problemas críticos

- `ops_models.py` — 1073 líneas mezclando 7 dominios no relacionados
- `ops_service.py` — 848 líneas: storage + locking + GICS bridge + telemetry + lifecycle
- `run_worker.py` — 519 líneas con extracción de paths por regex de 5 prioridades
- Dual storage sin conflict resolution: local JSON + GICS (fallo silencioso)
- Event sourcing sin snapshots: `run_events.jsonl` crece sin límite
- Lock único `.ops.lock` para TODAS las operaciones → contención

---

## 2. Lo que Nadie Tiene (y GIMO sí tendrá)

| Capacidad | LangGraph | CrewAI | AutoGen | OpenAI Assistants | **GIMO** |
|---|---|---|---|---|---|
| Pipeline con replay determinista | No | No | No | No | **Sí** |
| Tool-calling para artefactos con policy enforcement | No | No | No | Parcial | **Sí** |
| Self-healing con fallback automático entre stages | No | No | No | No | **Sí** |
| Risk calibration adaptativo (aprende de outcomes) | No | No | No | No | **Sí** |
| Journal con snapshot compaction | No | No | No | No | **Sí** |
| Rollback determinista stage-by-stage | No | No | No | No | **Sí** |

---

## 3. Arquitectura Target

### Estructura de directorios nueva

```
tools/gimo_server/
├── models/                         # NUEVO — split de ops_models.py
│   ├── __init__.py                 # Re-exporta todo (backwards compat)
│   ├── core.py                     # OpsDraft, OpsApproved, OpsRun, OpsConfig, OpsPlan
│   ├── provider.py                 # ProviderEntry, ProviderConfig, NormalizedModelInfo
│   ├── workflow.py                 # WorkflowGraph, WorkflowNode, WorkflowState
│   ├── policy.py                   # RuntimePolicyConfig, BaselineManifest, PolicyDecision
│   ├── economy.py                  # CostEvent, BudgetForecast, CascadeConfig
│   ├── agent.py                    # AgentProfile, AgentActionEvent, ActionDraft
│   ├── eval.py                     # EvalDataset, EvalRunRequest, EvalRunReport
│   ├── graph_state.py              # GraphState, StrictContract, Delegation (Jules-style)
│   └── conversation.py             # GimoItem, GimoTurn, GimoThread
│
├── engine/                         # NUEVO — motor de ejecución unificado
│   ├── __init__.py
│   ├── contracts.py                # ExecutionStage protocol, StageInput, StageOutput
│   ├── pipeline.py                 # Pipeline runner: compose, replay, self-heal
│   ├── journal.py                  # RunJournal con snapshot compaction
│   ├── replay.py                   # Deterministic replay desde journal
│   ├── risk_calibrator.py          # Adaptive risk thresholds (Bayesian)
│   ├── worker.py                   # RunWorker delgado (~100 líneas) → Pipeline.run()
│   ├── stages/
│   │   ├── __init__.py
│   │   ├── policy_gate.py          # Unifica IntentClassification + RuntimePolicy
│   │   ├── risk_gate.py            # Risk scoring con thresholds calibrados
│   │   ├── plan_stage.py           # DAG execution (absorbe CustomPlanService)
│   │   ├── llm_execute.py          # LLM call con model routing
│   │   ├── file_write.py           # Tool-calling primero, regex fallback
│   │   ├── critic.py               # CriticService como stage
│   │   ├── git_pipeline.py         # MergeGate: worktree→tests→lint→merge
│   │   └── qa_gate.py              # QA gate para Slice0-style pipelines
│   └── tools/
│       ├── __init__.py
│       ├── artifact_tools.py       # Schemas: write_file, create_dir, patch_file
│       └── executor.py             # Tool call executor con sandbox + policy check
│
└── services/                       # EXISTENTE — se consolida gradualmente
    ├── ops_store.py                # NUEVO: ops_service.py sin GICS bridge ni telemetry
    ├── workspace.py                # NUEVO: file_service + git_service + repo_service
    ├── providers/                  # NUEVO: consolida 9 provider_* services
    │   ├── connector.py
    │   ├── catalog.py
    │   └── router.py
    ├── economy.py                  # NUEVO: cost_service + budget_forecast + cascade
    ├── trust.py                    # NUEVO: trust_engine + trust_event_buffer
    └── observability.py            # NUEVO: agent_telemetry + agent_insight + observability
```

---

## 4. El Contrato Central (Pipeline Engine)

```python
# engine/contracts.py

class StageInput(BaseModel):
    run_id: str
    context: dict[str, Any]
    artifacts: dict[str, Any]  # Outputs de stages previos

class StageOutput(BaseModel):
    status: Literal["continue", "halt", "retry", "fail"]
    artifacts: dict[str, Any]
    journal_entry: JournalEntry  # Serializable para replay

class ExecutionStage(Protocol):
    name: str
    async def execute(self, input: StageInput) -> StageOutput: ...
    async def rollback(self, input: StageInput) -> None: ...
```

### Cómo se mapean las 6 rutas actuales

| Ruta actual | Composición de stages nueva |
|---|---|
| MergeGate high-risk | `[PolicyGate, RiskGate, GitPipeline]` |
| RunWorker structured plan | `[PolicyGate, RiskGate, PlanStage, LlmExecute]` |
| RunWorker file task | `[PolicyGate, RiskGate, FileWrite]` |
| RunWorker legacy | `[PolicyGate, RiskGate, LlmExecute, Critic]` |
| CustomPlan DAG | `[PolicyGate, RiskGate, PlanStage]` |
| Slice0 | `[PolicyGate, RiskGate, PlanStage, LlmExecute, QaGate]` |

---

## 5. Innovación: Tool-Calling para Artefactos

En vez de regex para extraer paths de archivos, el LLM recibe herramientas estructuradas:

```python
ARTIFACT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file at the specified path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    # create_dir, patch_file, run_command...
]
```

El executor valida paths contra `RuntimePolicyConfig.allowed_paths` **antes de escribir**. Si el proveedor no soporta function calling, cae al regex actual como degraded path.

---

## 6. Innovación: Journal con Replay Determinista

```python
# engine/journal.py

class JournalEntry(BaseModel):
    step_id: str
    stage_name: str
    started_at: datetime
    finished_at: datetime
    input_hash: str       # SHA-256 de StageInput serializado
    output_hash: str      # SHA-256 de StageOutput serializado
    input_snapshot: dict  # StageInput completo para replay
    output_snapshot: dict # StageOutput completo para replay
    status: Literal["completed", "failed", "retried", "rolled_back"]

class RunJournal:
    def append(self, entry: JournalEntry) -> None: ...
    def snapshot(self) -> None: ...  # Compacta entradas > N en snapshot file
    def replay_from(self, step_id: str) -> list[JournalEntry]: ...
```

Nuevo endpoint: `POST /ops/runs/{run_id}/replay?from_step={step_id}`

---

## 7. Innovación: Risk Calibrator Adaptativo

```python
# engine/risk_calibrator.py

class RiskCalibrator:
    """Ajusta thresholds de riesgo basándose en éxito histórico por intent class."""

    def calibrated_thresholds(self, intent_class: str) -> RiskThresholds:
        events = self._storage.list_trust_events_by_dimension(f"intent|{intent_class}")
        success_rate = self._compute_success_rate(events)
        adjustment = (success_rate - 0.8) * 20  # +/-20 pts alrededor del 80% baseline
        return RiskThresholds(
            auto_run_max=clamp(30.0 + adjustment, 10.0, 50.0),
            review_max=clamp(60.0 + adjustment, 40.0, 80.0),
        )
```

Habilitado via flag: `OpsConfig.economy.adaptive_risk: bool = False`

---

## 8. Innovación: Self-Healing Pipeline

Cada stage declara estrategias alternativas:

```python
class StageConfig(BaseModel):
    stage: ExecutionStage
    alternatives: list[ExecutionStage] = []  # Fallbacks si primary falla
    max_retries: int = 1
    retry_delay_seconds: float = 2.0
```

El pipeline runner, en fallo de un stage:
1. Reintentos con exponential backoff
2. Si se agotan, prueba alternatives[0]
3. Si se agotan todas, rollback determinista en orden inverso
4. Registra el healing attempt en el journal

---

## 9. Plan de Implementación (Orden de Prioridad)

```
Fase 1: models/ split (0 riesgo, ~30 min)
  └─ ops_models.py → re-export shim
     models/core.py, policy.py, workflow.py, agent.py, eval.py...

Fase 2: engine/contracts.py + engine/pipeline.py (2h)
  └─ El contrato central que todo lo demás usa

Fase 3: engine/stages/policy_gate.py (45 min)
  └─ Unifica IntentClassification + RuntimePolicy → un solo gate

Fase 4: engine/tools/ + engine/stages/file_write.py (1h)
  └─ Tool-calling para artefactos + fallback regex

Fase 5: engine/journal.py + engine/replay.py (1h)
  └─ Journal con snapshot + endpoint /replay

Fase 6: engine/risk_calibrator.py (30 min)
  └─ Adaptive thresholds (detrás de feature flag)

Fase 7: Self-healing en pipeline.py (30 min)
  └─ alternatives[] por stage

Fase 8: Consolidación de servicios (incremental, varios días)
  └─ 70 servicios → 20 módulos cohesivos
```

### Principios de compatibilidad

- **Feature flags** para cada innovación en `OpsConfig` — nunca romper lo que funciona
- **Re-export shims** para todos los imports existentes — `from ..ops_models import X` sigue funcionando
- **Fallback paths** en cada stage nuevo — si falla, usa el código viejo

---

## 10. Consolidación de Servicios (Fase 8 detallada)

| Services actuales | Módulo target | LOC estimadas |
|---|---|---|
| `run_worker.py` (519) | `engine/worker.py` | ~80 |
| `merge_gate_service.py` (280) | `engine/stages/git_pipeline.py` | ~200 |
| `custom_plan_service.py` (649) | `engine/stages/plan_stage.py` + `services/plan_store.py` | ~300 + ~150 |
| `ops_service.py` (848) | `services/ops_store.py` | ~500 |
| `intent_classification_service.py` + `runtime_policy_service.py` | `engine/stages/policy_gate.py` | ~150 |
| `critic_service.py` | `engine/stages/critic.py` | ~60 |
| `provider_service_impl.py` + 8 provider_* services | `services/providers/*.py` (4 archivos) | ~600 total |
| `model_router_service.py` + `model_inventory_service.py` | `services/providers/router.py` | ~200 |
| `cost_service.py` + `cost_predictor.py` + `budget_forecast_service.py` + `cascade_service.py` | `services/economy.py` | ~300 |
| `trust_engine.py` + `trust_event_buffer.py` | `services/trust.py` | ~200 |
| `agent_telemetry_service.py` + `agent_insight_service.py` + `observability_service.py` | `services/observability.py` | ~350 |
| `file_service.py` + `git_service.py` + `repo_service.py` + `repo_override_service.py` | `services/workspace.py` | ~400 |

**Reducción estimada: ~8000 LOC → ~4500 LOC con mejor cobertura funcional.**

---

## 11. Archivos Críticos para Implementación Inmediata

1. `tools/gimo_server/engine/contracts.py` — el contrato que todo usa
2. `tools/gimo_server/engine/pipeline.py` — el runner
3. `tools/gimo_server/engine/stages/policy_gate.py` — unificación de decisiones
4. `tools/gimo_server/engine/stages/file_write.py` — tool-calling para artefactos
5. `tools/gimo_server/engine/tools/artifact_tools.py` — schemas de herramientas
6. `tools/gimo_server/engine/journal.py` — journal con snapshot compaction
7. `tools/gimo_server/models/__init__.py` — re-export shim
