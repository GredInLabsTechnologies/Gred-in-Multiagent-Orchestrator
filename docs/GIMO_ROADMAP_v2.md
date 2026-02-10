# GIMO — Roadmap Unificado v2
## "The Agent Firewall"

**Fecha:** 2026-02-10T18:00:00Z
**Versión:** 2.0
**Estado:** Propuesta estratégica unificada
**Autores:** Equipo GIMO + Claude Opus 4.6 (asistencia estratégica y técnica)

---

## Visión

GIMO es el **sustrato de gobernanza** donde los agentes de IA operan de forma segura. No compite con Claude, Codex ni Gemini — los orquesta, los audita y los controla.

> **"Usa la potencia de tu suscripción Pro. Pero hazlo a través de GIMO para que tengamos auditoría y control total."**

### Principios rectores

1. **Los agentes son efímeros.** Se spawnean, ejecutan, mueren. GIMO es quien persiste, recuerda y decide.
2. **La confianza se gana con datos, no se asume.** El sistema aprende de cada interacción y ajusta la autonomía automáticamente.
3. **Core propio, sin dependency-lock.** Capacidad equivalente a LangGraph/AutoGen/crewAI pero con seguridad y gobernanza como ciudadanos de primera clase.
4. **BYOT (Bring Your Own Token).** El usuario trae su suscripción. GIMO cobra por gobernanza, no por acceso a modelos.

---

## Diagnóstico: dónde estamos hoy

### Fortalezas (base sólida)

| Pieza | Estado |
|---|---|
| HITL (approval gate) | Funcional: draft → approve → run |
| RBAC 3 roles | Funcional: actions / operator / admin |
| Audit log | Funcional: SHA-256 actor labels, rotating file |
| Provider adapter | Funcional: OpenAI-compatible (Ollama, LM Studio, OpenRouter) |
| Artefactos durables | Funcional: drafts, approved, runs con file-based persistence |
| Rate limit + panic mode | Funcional |
| UI operativa | Funcional: 5 tabs (Plan, Drafts, Approved, Runs, Config) |
| Tests | 26 tests cubriendo roles, workflow, auto_run, security, config |

### Debilidades críticas (para paridad + diferenciación)

| Carencia | Impacto |
|---|---|
| No hay Agent Adapters | Solo llamamos a APIs; no orquestamos CLIs locales (Claude Code, Codex, Gemini) |
| No hay graph engine | Los planes son informativos; OpsTask.depends existe pero no se ejecuta |
| No hay durable execution | Sin checkpoints, sin resume, sin retries por nodo |
| No hay Trust Engine | Las decisiones de auto-approve son manuales, no data-driven |
| No hay contracts (pre/post) | Sin verificación automática de lo que hace el agente |
| No hay institutional memory | El audit log existe pero no se convierte en aprendizaje |
| Multi-agente es accidental | Sin handoff, sin supervisor/workers, sin routing por modelo |
| Observabilidad no es producto | Sin trazas por step, sin cost tracking, sin evals |
| Tool registry no existe | No hay catálogo de tools con riesgo/permisos/policy |
| Persistencia file-based limitada | JSON + FileLock no escala para checkpoints frecuentes |

---

## Arquitectura target

```
┌──────────────────────────────────────────────────────────────────┐
│                          GIMO CORE                               │
│                                                                  │
│  AGENT ADAPTERS                                                  │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ Claude    │  │ Codex     │  │ Gemini    │  │ OpenAI-compat│  │
│  │ (MCP/     │  │ (CLI      │  │ (CLI      │  │ (API fallback│  │
│  │  hooks)   │  │  wrapper)  │  │  wrapper)  │  │  Ollama/OR) │  │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └──────┬───────┘  │
│        └───────────────┼───────────────┼───────────────┘          │
│                        ↓                                         │
│  EXECUTION ENGINE                                                │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  Workflow Graph                                        │      │
│  │  ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐         │      │
│  │  │Node A│───→│Node B│───→│Node C│───→│Node D│         │      │
│  │  │claude│    │HITL  │    │codex │    │eval  │         │      │
│  │  └──────┘    └──────┘    └──────┘    └──────┘         │      │
│  │                                                        │      │
│  │  - Secuencia + branching + loops controlados           │      │
│  │  - Sub-graphs reutilizables                            │      │
│  │  - State tipado y versionado entre nodos               │      │
│  │  - Checkpoint por nodo (SQLite)                        │      │
│  │  - Resume/replay desde cualquier checkpoint            │      │
│  │  - Retries + backoff + timeout por nodo                │      │
│  │  - Budget guards (steps/tokens/coste)                  │      │
│  └────────────────────────────────────────────────────────┘      │
│                        ↓                                         │
│  GOVERNANCE LAYER                                                │
│  ┌────────────────────────────────────────────────────────┐      │
│  │                                                        │      │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │      │
│  │  │ Trust Engine │  │ Contract     │  │ Policy       │  │      │
│  │  │             │  │ Verifier     │  │ Engine       │  │      │
│  │  │ - trust por │  │              │  │              │  │      │
│  │  │   dimensión │  │ - pre/post   │  │ - por tool   │  │      │
│  │  │   (tool+    │  │   conditions │  │ - por agente │  │      │
│  │  │   context+  │  │ - rollback   │  │ - por context│  │      │
│  │  │   model+    │  │   automático │  │ - allow/deny │  │      │
│  │  │   task)     │  │ - blast      │  │   /review    │  │      │
│  │  │ - circuit   │  │   radius     │  │              │  │      │
│  │  │   breaker   │  │              │  │              │  │      │
│  │  └─────────────┘  └──────────────┘  └──────────────┘  │      │
│  │                                                        │      │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │      │
│  │  │ HITL Gate   │  │ Tool         │  │ Model        │  │      │
│  │  │             │  │ Registry     │  │ Router       │  │      │
│  │  │ - pausa     │  │              │  │              │  │      │
│  │  │ - estado    │  │ - nombre     │  │ - por nodo   │  │      │
│  │  │   editable  │  │ - riesgo     │  │ - por coste  │  │      │
│  │  │ - fork      │  │ - permisos   │  │ - por calidad│  │      │
│  │  │ - anotacion │  │ - HITL flag  │  │ - fallback   │  │      │
│  │  └─────────────┘  └──────────────┘  └──────────────┘  │      │
│  └────────────────────────────────────────────────────────┘      │
│                        ↓                                         │
│  MEMORY & AUDIT                                                  │
│  ┌────────────────────────────────────────────────────────┐      │
│  │                                                        │      │
│  │  HOT (memoria)     WARM (GICS activo)   COLD (GICS    │      │
│  │  ┌────────────┐    ┌───────────────┐    archivos)     │      │
│  │  │PolicyCache │    │trust_active   │    ┌───────────┐ │      │
│  │  │            │←──→│.gics          │←──→│trust_2025 │ │      │
│  │  │score,count │    │               │    │.gics      │ │      │
│  │  │auto_approve│    │segmento/semana│    │           │ │      │
│  │  │circuit_st  │    │query(itemId)  │    │verify()   │ │      │
│  │  └────────────┘    └───────────────┘    │cifrado    │ │      │
│  │                                         └───────────┘ │      │
│  │  SQLite (checkpoints, state, operational data)        │      │
│  │  Audit log (SHA-256 chain, tamper-evident)            │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Roadmap por fases

---

### FASE 1: Foundations (semanas 1–4)
**Objetivo:** Sentar las bases técnicas para todo lo que viene después.

#### 1.1 Agent Adapter — Claude Code (prioridad máxima)

**Qué:** Wrapper que permite a GIMO orquestar Claude Code como agente efímero.

**Por qué primero:** Claude Code ya tiene MCP servers y hooks. Es el agente con mejor integración posible. Demuestra el modelo BYOT desde el día 1.

**Entregables:**
- `adapters/base.py`: interfaz `AgentAdapter` abstracta
  ```
  spawn(task, context, policy) → AgentSession
  capture_proposal() → ProposedAction[]
  allow(action_id) / deny(action_id)
  get_result() → AgentResult
  kill()
  ```
- `adapters/claude_code.py`: implementación via MCP server + hooks
  - GIMO se registra como MCP server de Claude Code
  - Intercepta tool calls via hooks (pre-tool, post-tool)
  - Captura propuestas antes de ejecución
  - Aplica policy gate (allow/deny/require_review)
  - Captura resultado + métricas (tokens, duración)
- `adapters/generic_cli.py`: wrapper genérico para CLIs via stdin/stdout
  - Base para Codex y Gemini CLI (implementación concreta en Fase 3)
- Tests: spawn → capture → allow → result round-trip

#### 1.2 Graph Engine MVP

**Qué:** Motor de ejecución de workflows como grafos.

**Entregables:**
- Modelo de datos:
  ```
  WorkflowGraph { id, nodes: Node[], edges: Edge[], state_schema }
  Node { id, type, config, agent?, timeout?, retries? }
    types: llm_call | tool_call | human_review | eval | transform | sub_graph
  Edge { from, to, condition? }
  State { version, data: Dict, checkpoints: Checkpoint[] }
  ```
- Ejecución:
  - Secuencia lineal (A → B → C)
  - Branching condicional (if/else por estado)
  - Loop controlado (con límite duro de iteraciones)
- Cada nodo recibe estado, produce estado modificado
- Logging estructurado por step (step_id, status, duration, agent_used)

#### 1.3 SQLite como persistence layer

**Qué:** Migrar de JSON files a SQLite para datos operativos.

**Por qué:** Los checkpoints por nodo generan escrituras frecuentes. JSON + FileLock no escala.

**Entregables:**
- SQLite con WAL mode para transacciones atómicas
- Tablas: `workflows`, `nodes`, `edges`, `checkpoints`, `trust_events`, `audit_entries`
- Migración: los JSON files actuales (drafts/, approved/, runs/) se importan a SQLite
- Retrocompatibilidad: los endpoints existentes siguen funcionando
- FileLock se mantiene solo para el archivo SQLite (en vez de por JSON)

#### 1.4 Trust Event schema

**Qué:** Definir la estructura de eventos que alimentará el Trust Engine.

**Entregables:**
- Modelo:
  ```
  TrustEvent {
    timestamp: datetime
    dimension_key: str        # "tool|path|model|task_type"
    tool: str                 # "file_write", "shell_exec", "llm_call"
    context: str              # "src/auth.py", "tests/", "*"
    model: str                # "claude-sonnet", "codex", "*"
    task_type: str            # "add_endpoint", "refactor", "review"
    outcome: enum             # approved | rejected | error | timeout | auto_approved
    actor: str                # role:hash (existing format)
    post_check_passed: bool   # contract post-condition result
    duration_ms: int
    tokens_used: int
    cost_usd: float
  }
  ```
- Buffer en memoria: eventos se acumulan, flush a SQLite cada N eventos o M segundos
- Fuente: se genera automáticamente en cada tool call interceptada por el Agent Adapter

#### 1.5 Contract definitions (pre/post conditions)

**Qué:** Estructura para definir contratos verificables por nodo.

**Entregables:**
- Modelo:
  ```
  Contract {
    pre_conditions: Check[]
    post_conditions: Check[]
    rollback: Action[]
    blast_radius: low | medium | high | critical
  }
  Check {
    type: file_exists | tests_pass | function_exists | no_new_vulnerabilities | custom
    params: Dict
  }
  ```
- Ejecución: nodo especial `contract_check` que corre antes/después de nodos de acción
- Si post-condition falla: ejecuta rollback, escribe TrustEvent con outcome=error, escala a HITL

**Resultado Fase 1:** GIMO puede orquestar Claude Code como agente efímero dentro de un workflow graph con checkpoints, trust events se capturan en cada acción, contracts se definen y verifican por nodo.

---

### FASE 2: Governance Core (semanas 5–10)
**Objetivo:** El corazón diferenciador — trust engine, policies, HITL avanzado.

#### 2.1 Trust Engine

**Qué:** Sistema que calcula trust scores por dimensión y decide auto-approve/review/block.

**Cómo funciona:**
```
Cada dimensión = combinación de (tool + context + model + task_type)

trust_record {
  dimension_key: str
  approvals: int
  rejections: int
  failures: int          # post-condition failures
  auto_approvals: int
  streak: int            # racha consecutiva de éxitos
  score: float           # 0.0 → 1.0, calculado por fórmula
  policy: auto_approve | require_review | blocked
  circuit_state: closed | open | half_open
  last_updated: datetime
}

Score formula (ajustable):
  base = approvals / (approvals + rejections + failures + 1)
  recency_weight = decay factor por antigüedad de eventos
  streak_bonus = min(streak * 0.01, 0.1)
  score = base * recency_weight + streak_bonus

Policy thresholds (configurable):
  score >= 0.90 AND approvals >= 20  → auto_approve
  score >= 0.50                       → require_review
  score < 0.50 OR failures >= 5      → blocked
  blast_radius == critical            → SIEMPRE require_review (override)
```

**Entregables:**
- `services/trust_engine.py`: cálculo de scores, policy decisions
- `TrustRecord` en SQLite (tier HOT)
- API: `POST /trust/query` (consulta), `GET /trust/dashboard` (overview)
- Integración con Agent Adapter: cada tool call pasa por Trust Engine antes de ejecutar
- UI: pestaña nueva "Trust" en OpsIsland con vista de dimensiones y scores

#### 2.2 Circuit Breaker automático

**Qué:** Degradación automática de trust cuando un patrón falla repetidamente.

**Entregables:**
- Configuración por dimensión:
  ```
  circuit_breaker {
    window: int              # últimas N ejecuciones a evaluar
    failure_threshold: int   # fallos para abrir el circuito
    recovery_probes: int     # ejecuciones supervisadas antes de cerrar
    cooldown_seconds: int    # tiempo mínimo en estado open
  }
  ```
- Estados: `closed` (normal) → `open` (bloqueado) → `half_open` (probando con HITL)
- Transiciones automáticas basadas en trust events
- Notificación al operator/admin cuando un circuito se abre
- Log entry en audit trail

#### 2.3 HITL como nodo del grafo (avanzado)

**Qué:** Evolucionar el HITL binario actual a un nodo interactivo.

**Entregables:**
- Nodo `human_review`:
  - Pausa la ejecución del grafo
  - Expone estado actual editable en UI
  - El humano puede: aprobar, rechazar, editar estado, tomar control del nodo
  - Fork: ejecutar 2 opciones en paralelo, humano elige cuál queda
  - Anotaciones: el humano deja notas en el nodo (alimentan institutional memory)
- Reanudación: el grafo continúa con el estado (posiblemente editado) por el humano
- Timeout configurable: si el humano no responde en X tiempo, acción por defecto (block)

#### 2.4 Durable Execution

**Qué:** Checkpoints, retries, resume, budget guards.

**Entregables:**
- Checkpoint tras cada nodo: estado completo + output + metadata en SQLite
- Resume: `POST /workflows/{id}/resume?from_checkpoint={checkpoint_id}`
- Retries por nodo: configurable con backoff exponencial y límite
- Timeout por nodo + timeout global de workflow
- Idempotency keys para tool calls de escritura
- Budget guards:
  ```
  budget {
    max_steps: int
    max_tokens: int
    max_cost_usd: float
    max_duration_seconds: int
  }
  ```
  Si se excede cualquier límite → pausa → HITL o abort según config

#### 2.5 Tool Registry

**Qué:** Catálogo de tools con metadata de riesgo y permisos.

**Entregables:**
- Modelo:
  ```
  ToolEntry {
    name: str
    description: str
    inputs: JsonSchema
    outputs: JsonSchema
    risk: read | write | destructive
    estimated_cost: float
    requires_hitl: bool
    allowed_roles: list[str]
  }
  ```
- Registro estático (config) + dinámico (tools que reportan los Agent Adapters)
- Lookup en cada tool call interceptada
- Si tool no está en registry → blocked por defecto (allowlist, no blocklist)

**Resultado Fase 2:** GIMO tiene gobernanza data-driven. Las decisiones de auto-approve/block se basan en historial real. HITL es interactivo, no binario. Las ejecuciones son durables y resumibles.

---

### FASE 3: Multi-Agent & Routing (semanas 11–16)
**Objetivo:** Múltiples agentes colaborando en un mismo workflow con routing inteligente.

#### 3.1 Agent Adapters adicionales

**Entregables:**
- `adapters/codex.py`: wrapper para OpenAI Codex CLI
  - Spawn proceso, feed tarea, capture stdout/proposals
  - Integración con approval gate de GIMO
- `adapters/gemini.py`: wrapper para Gemini CLI
  - Google ID auth bridge
  - Capture proposals
- Cada adapter implementa la misma interfaz `AgentAdapter`
- Tests de integración por adapter

#### 3.2 Patrones multi-agente

**Qué:** Patrones de coordinación entre agentes, construidos sobre el graph engine.

**Entregables:**
- **Supervisor/Workers:**
  ```
  Supervisor (GIMO) asigna tareas a agentes
  → Claude: "haz security review de auth.py"
  → Codex: "implementa el endpoint logout"
  → Gemini: "genera tests para el endpoint"
  Cada uno opera en su nodo, GIMO coordina secuencia y dependencias
  ```
- **Reviewer/Critic loop:**
  ```
  Agente A genera código
  → Agente B revisa (diferente modelo para diversidad)
  → Si B rechaza: A reintenta con feedback de B
  → Límite duro de iteraciones (configurable, default 3)
  ```
- **Handoff explícito:**
  ```
  Agente A termina su parte
  → Empaqueta contexto relevante (no todo el context window)
  → GIMO inyecta ese contexto al Agente B en el siguiente nodo
  → El agente B es un spawn fresco con contexto curado
  ```
- Cada patrón es un sub-graph reutilizable (template)

#### 3.3 Model Router inteligente

**Qué:** Asignación automática de modelo por nodo basada en coste/calidad.

**Entregables:**
- Routing policy por nodo:
  ```
  routing_policy {
    classification:     → haiku / flash (barato, rápido)
    code_generation:    → sonnet / codex (buena relación coste/calidad)
    security_review:    → opus (máxima calidad, coste justificado)
    formatting:         → local / ollama (gratis)
    default:            → sonnet (balanceado)
  }
  ```
- Cost tracking real por nodo: tokens in/out, precio por modelo, coste acumulado
- Sugerencias automáticas: "este nodo usa opus pero sonnet da el mismo resultado el 95% de las veces"
- Budget-aware routing: si el presupuesto restante es bajo, degrada a modelo más barato
- UI: vista de coste por nodo y por workflow

#### 3.4 Onboarding multi-provider

**Qué:** Flujo guiado para conectar agentes.

**Entregables:**
- Panel "Conectores" en UI:
  ```
  ┌─────────────────────────────────────────────┐
  │  Agentes conectados                         │
  │                                             │
  │  [x] Claude Code    via MCP    (Pro plan)   │
  │  [ ] OpenAI Codex   no config              │
  │  [x] Ollama local   via API    (qwen2.5)   │
  │  [ ] Gemini         no config              │
  │                                             │
  │  [+ Añadir conector]                        │
  └─────────────────────────────────────────────┘
  ```
- Detección automática de CLIs instalados
- Validación de conexión (health check por adapter)
- OpenRouter como opción "todo en uno" (ya funciona con openai_compat.py)

**Resultado Fase 3:** GIMO orquesta múltiples agentes de diferentes proveedores en un mismo workflow. Cada agente usa la suscripción del usuario. El routing optimiza coste/calidad por nodo.

---

### FASE 4: Institutional Memory & Observability (semanas 17–26)
**Objetivo:** GIMO aprende de cada interacción y ofrece observabilidad de producción.

#### 4.1 Integración GICS para Trust Store

**Qué:** Usar GICS (con Schema Profiles v1.4) como storage comprimido, cifrado y verificable para datos históricos de trust.

**Dependencia:** GICS v1.4 con Schema Profiles implementado (plan separado, 10-15 días).

**Schema de trust para GICS:**
```
SchemaProfile {
  id: "gimo_trust_v1"
  itemIdType: "string"
  fields: [
    { name: "score",      type: "numeric",     codecStrategy: "value" }
    { name: "approvals",  type: "numeric",     codecStrategy: "structural" }
    { name: "rejections", type: "numeric",     codecStrategy: "structural" }
    { name: "failures",   type: "numeric",     codecStrategy: "structural" }
    { name: "streak",     type: "numeric",     codecStrategy: "structural" }
    { name: "outcome",    type: "categorical" }
  ]
}
```

**Arquitectura 3-tier:**
- **HOT (SQLite):** trust_records actuales, PolicyCache en memoria, consulta en cada tool call
- **WARM (GICS activo):** últimos N meses, flush periódico desde SQLite, query(dimension_key) para hydrate
- **COLD (GICS archivos):** histórico anual, cifrado AES-256-GCM at-rest, verify() sin descomprimir, solo para auditoría/compliance

**Entregables:**
- `services/trust_store.py`: gestión de los 3 tiers
- Rotación automática: SQLite → GICS warm (semanal), GICS warm → GICS cold (anual)
- GICS verify() integrado en health check del sistema
- Fail-closed: si GICS warm está corrupto, opera desde SQLite (más restrictivo)

#### 4.2 Institutional Memory

**Qué:** El sistema aprende patrones del historial de trust y mejora las policies automáticamente.

**Entregables:**
- Análisis de patrones:
  - "file_write en src/auth.py con sonnet para add_endpoint tiene 98% success rate → sugerir auto_approve"
  - "shell_exec con rm en cualquier contexto tiene 0% approval rate → hardcode blocked"
  - "refactor en src/payments.py falla el 60% de las veces → sugerir require_review + opus"
- Sugerencias automáticas al admin:
  ```
  GIMO sugiere:
  - Promover "file_write|src/auth.py|sonnet|add_endpoint" a auto_approve
    Razón: 47 approvals, 2 rejections, score 0.94
    [Aprobar] [Rechazar] [Revisar historial]
  ```
- Anotaciones humanas (de Fase 2) alimentan el learning:
  - "Este cambio se rechazó porque no tenía tests" → asocia tag "needs_tests" a la dimensión
- Dashboard "Lo que GIMO ha aprendido de tu codebase":
  - Top tools más usadas y sus trust scores
  - Patrones problemáticos detectados
  - Sugerencias pendientes de revisión
  - Coste acumulado por modelo/tarea

#### 4.3 Observabilidad (OpenTelemetry)

**Qué:** Trazas estructuradas por step/tool/LLM call, métricas de coste, timeline visual.

**Entregables:**
- Instrumentación OpenTelemetry (Apache-2.0):
  - Trace ID por workflow execution
  - Span por nodo (start/end/duration/status/agent_used)
  - Span hijo por tool call dentro del nodo
  - Span hijo por LLM call (tokens in/out, modelo, coste)
- Métricas:
  - tokens_total, cost_total por workflow/nodo/agente
  - approval_latency (cuánto tarda el humano en aprobar)
  - trust_score_distribution
  - circuit_breaker_events
- Backend inicial: Jaeger (Apache-2.0) como recomendación, pero GIMO emite OTLP genérico
- UI: timeline visual de ejecución (React Flow para grafo + spans temporales)

#### 4.4 Evals & Regression

**Qué:** Verificación automática de que los workflows siguen funcionando correctamente.

**Entregables:**
- Datasets "golden" por workflow: input esperado → output esperado
- Regression runner: ejecuta N casos offline, genera informe con scoring
- LLM-as-judge opcional: un modelo evalúa la calidad del output (con scoring numérico)
- CI integration: bloquear releases si métricas críticas caen bajo umbral
- Harness propio simple primero; migrar a framework (DeepEval o similar) solo si lo justifica

**Resultado Fase 4:** GIMO tiene memoria institucional comprimida y verificable (GICS), aprende de cada interacción, ofrece observabilidad de producción, y evalúa automáticamente la calidad de los workflows.

---

### FASE 5: Enterprise & UX (meses 6–9)
**Objetivo:** Pulir para producción enterprise y diferenciación UX.

#### 5.1 Policy-as-Code (engine propio → OPA opcional)

**Entregables:**
- Policy engine propio con reglas JSON:
  ```json
  {
    "rules": [
      {
        "match": { "tool": "file_delete", "context": "*" },
        "action": "require_review",
        "override": "never_auto_approve"
      },
      {
        "match": { "tool": "file_write", "context": "src/payments/**" },
        "action": "require_review",
        "min_trust_score": 0.95
      }
    ]
  }
  ```
- Evaluación en cada tool call: `policy_decide(tool, context, trust_score) → allow/deny/review`
- Versionado de policies (git-like: quién cambió qué cuándo)
- Migración opcional a OPA (Apache-2.0) para clientes enterprise que ya lo usan

#### 5.2 Sandbox para tools de alto riesgo

**Entregables:**
- Aislamiento a nivel proceso para tools destructivas
- Permisos mínimos: filesystem read-only excepto paths aprobados
- Timeout forzado por sandbox
- MVP: solo para tools con risk=destructive
- Producción: contenedor efímero (Docker) opcional para máximo aislamiento

#### 5.3 Visualización de grafos (UI)

**Entregables:**
- React Flow (MIT) para visualizar workflow graphs
- Vista en tiempo real: nodos activos, completados, bloqueados
- Click en nodo → detalle: state, checkpoints, trust score, cost, logs
- Vista timeline: secuencia temporal de ejecución con spans de OpenTelemetry
- HITL inline: desde la vista de grafo, aprobar/rechazar/editar nodos

#### 5.4 Compliance & Export

**Entregables:**
- Export de audit trail completo (JSON, CSV)
- GICS cold files como evidencia forense (hash chain verificable independientemente)
- Informe de "quién hizo qué" por periodo (para auditorías)
- Retención configurable (N años, obligatorio para regulados)

---

## Stack tecnológico

| Componente | Tecnología | Licencia |
|---|---|---|
| Backend | FastAPI (Python) | MIT |
| Persistencia operativa | SQLite (WAL mode) | Public domain |
| Persistencia histórica | GICS v1.4 (propio) | Propietario |
| UI | React + TypeScript + Vite | MIT |
| UI grafos | React Flow | MIT |
| Observabilidad | OpenTelemetry | Apache-2.0 |
| Tracing backend | Jaeger (recomendado) | Apache-2.0 |
| Policy engine | Propio (JSON rules) → OPA opcional | Apache-2.0 |
| Cifrado at-rest | GICS (AES-256-GCM) | Propietario |
| Integridad | SHA-256 chain (audit) + GICS (hash chain + CRC32) | — |

**Política de licencias:** Solo MIT / BSD / Apache-2.0 para dependencias core. GPL/AGPL prohibido en código embebido.

---

## Modelo de negocio

```
FREE (Local / Open Core)
├── 1 agente conectado
├── Graph engine completo
├── HITL básico (approve/reject)
├── Audit log local
└── SQLite persistence

PRO (para equipos)
├── Multi-agente (N conectores)
├── Trust Engine + circuit breaker
├── Contracts (pre/post conditions)
├── GICS trust store (warm tier)
├── Model router
├── Cost tracking
└── Evals básicas

ENTERPRISE (para organizaciones reguladas)
├── Policy-as-code (OPA integration)
├── GICS cold storage cifrado + compliance exports
├── Sandbox para tools destructivas
├── SSO / SAML
├── SLA + soporte
└── Retención configurable + forensics
```

**GIMO no cobra por tokens. Cobra por gobernanza.**

---

## Timeline resumen

| Fase | Semanas | Entregable clave |
|---|---|---|
| **1: Foundations** | 1–4 | Agent Adapter (Claude Code) + Graph MVP + SQLite + Trust Events |
| **2: Governance** | 5–10 | Trust Engine + Circuit Breaker + HITL avanzado + Durable Execution + Tool Registry |
| **3: Multi-Agent** | 11–16 | Adapters adicionales + Patrones (supervisor/workers/handoff) + Model Router |
| **4: Memory & Obs** | 17–26 | GICS integration + Institutional Memory + OpenTelemetry + Evals |
| **5: Enterprise** | 27–36 | Policy engine + Sandbox + Graph UI + Compliance |

**Dependencia paralela:** GICS v1.4 (Schema Profiles) se desarrolla en paralelo durante Fase 1-2 (10-15 días). Debe estar listo antes de Fase 4.

---

## Invariantes (no negociables en ninguna fase)

1. **Fail-closed:** ante duda, bloquear. Nunca auto-aprobar si hay error en trust/policy/GICS.
2. **Audit-first:** toda mutación se registra antes de ejecutarse.
3. **Determinismo:** mismo input + misma config → mismo comportamiento.
4. **HITL como override final:** el humano siempre puede intervenir, en cualquier fase, en cualquier nodo.
5. **Retrocompatibilidad:** cada fase preserva los endpoints y datos de las anteriores.
6. **Los agentes son efímeros:** la inteligencia vive en GIMO, no en los agentes.
7. **BYOT:** GIMO nunca almacena credenciales de suscripción del usuario en claro.
