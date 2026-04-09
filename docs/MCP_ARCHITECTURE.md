# MCP Bridge Architecture

**Status**: CURRENT
**Last verified**: 2026-04-10

> Scope: cómo GIMO expone sus capacidades a clientes MCP (Claude Desktop, Cline, Cursor, Antigravity, ChatGPT Apps).

## Principio de diseño

**El LLM que llama es el orquestador. GIMO provee tools, no orquestación.**

GIMO no decide qué hacer — el cliente MCP (Claude, GPT, etc.) decide qué tools invocar y en qué orden. GIMO expone sus capacidades como tools MCP con firmas claras y devuelve resultados estructurados.

## Arquitectura general

```
┌─────────────────────────────────────────────────┐
│  Claude Desktop / Cline / Cursor / Antigravity  │
│  (MCP client — el orquestador)                  │
└────────────────┬────────────────────────────────┘
                 │ stdio (JSON-RPC)
                 ▼
┌─────────────────────────────────────────────────┐
│  mcp_bridge/server.py                           │
│  FastMCP("GIMO") — proceso local stdio          │
│                                                 │
│  ┌──────────────┐ ┌──────────┐ ┌─────────────┐ │
│  │ Dynamic Tools │ │ Native   │ │ Governance  │ │
│  │ (OpenAPI)     │ │ Tools    │ │ Tools       │ │
│  │ ~50 endpoints │ │ 22 tools │ │ 8 tools     │ │
│  └──────┬───────┘ └─────┬────┘ └──────┬──────┘ │
│         │               │              │        │
│  ┌──────┴───────────────┴──────────────┴──────┐ │
│  │         proxy_to_api() → HTTP              │ │
│  │         http://127.0.0.1:9325/ops/*        │ │
│  └────────────────────┬───────────────────────┘ │
│                       │                         │
│  Resources: config, runs, drafts, metrics       │
│  Prompts: plan_creation, debug_run, optimize    │
└───────────────────────┬─────────────────────────┘
                        │ HTTP (Bearer token)
                        ▼
┌─────────────────────────────────────────────────┐
│  FastAPI Backend (port 9325)                    │
│  /ops/* — 27 routers                            │
│                                                 │
│  ┌─────────────────────────────────────────┐    │
│  │ Provider Catalog Service                │    │
│  │  ├─ OpenRouter Discovery (dynamic)      │    │
│  │  ├─ Ollama / LMStudio / sglang (local)  │    │
│  │  └─ OpenAI / Anthropic / Google (cloud)  │    │
│  ├─────────────────────────────────────────┤    │
│  │ Model Router + Benchmark Enrichment     │    │
│  │  ├─ LMArena (336 modelos, 17 categorías)│    │
│  │  ├─ Open LLM Leaderboard (6 benchmarks) │    │
│  │  └─ GICS Trust Engine (priors + learn)   │    │
│  ├─────────────────────────────────────────┤    │
│  │ Agentic Loop Service (multi-turn chat)  │    │
│  │  └─ ToolExecutor (8 tools internos)      │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

## Tres capas de tools

### 1. Dynamic Tools (~50) — OpenAPI auto-sync

Generados automáticamente desde el esquema OpenAPI de FastAPI. Cero drift por construcción.

```python
# server.py — se importa la app FastAPI y se extrae su spec
spec = fastapi_app.openapi()
provider = OpenAPIProvider(spec, client=client, mcp_names=name_map)
mcp.add_provider(provider)
```

- Solo expone rutas `/ops/*` (filtro `_ops_only`)
- Naming: `gimo_` + segmentos del path (ej: `/ops/drafts` → `gimo_drafts`)
- Incluye 3 aliases ergonómicos: `plan_create`, `plan_execute`, `cost_estimate`

### 2. Native Tools (22) — Lógica de puente

Tools con lógica específica del bridge que no son simple proxy HTTP:

| Tool | Qué hace |
|------|----------|
| `gimo_get_status` | Status canónico via `OperatorStatusService` |
| `gimo_start_engine` | Bootstrap del backend (trampoline → canonical launcher) |
| `gimo_stop_engine` | Shutdown via canonical lifecycle |
| `gimo_wake_ollama` | Asegura que Ollama esté corriendo |
| `gimo_chat` | Chat agentic multi-turn (fire-and-return por timeout MCP) |
| `gimo_create_draft` | Crear borrador de plan |
| `gimo_approve_draft` | Aprobar borrador |
| `gimo_approve_plan` | Aprobar plan completo |
| `gimo_reject_plan` | Rechazar plan |
| `gimo_propose_structured_plan` | Plan estructurado con tasks |
| `gimo_run_task` | Ejecutar tarea |
| `gimo_get_task_status` | Estado de tarea |
| `gimo_get_draft` | Leer borrador |
| `gimo_get_plan_graph` | Grafo visual del plan |
| `gimo_list_agents` | Listar agentes disponibles |
| `gimo_spawn_subagent` | Crear sub-agente |
| `gimo_resolve_handover` | Resolver handover entre agentes |
| `gimo_generate_team_config` | Generar config de equipo multi-agente |
| `gimo_web_search` | Búsqueda web federada |
| `gimo_get_server_info` | Introspección del proceso bridge |
| `gimo_gics_anomaly_report` | Reporte de anomalías GICS |
| `gimo_gics_model_reliability` | Fiabilidad de modelo según GICS |

> `gimo_reload_worker` solo aparece si `GIMO_DEV_MODE=1` (tool #23, dev-only).

### 3. Governance Tools (8) — SAGP

Tools de gobernanza que exponen la autoridad del trust engine:

| Tool | Qué hace |
|------|----------|
| `gimo_evaluate_action` | Pre-evaluar si una acción está permitida |
| `gimo_estimate_cost` | Estimar coste de un workflow |
| `gimo_verify_proof_chain` | Verificar cadena de pruebas GICS |
| `gimo_get_gics_insight` | Insight del motor GICS |
| `gimo_get_trust_profile` | Perfil de confianza de un modelo |
| `gimo_get_governance_snapshot` | Snapshot completo de gobernanza |
| `gimo_get_execution_policy` | Política de ejecución activa |
| `gimo_get_budget_status` | Estado de presupuesto |
| `gimo_trust_circuit_breaker_get` | Estado del circuit breaker |
| `gimo_dashboard` | Dashboard consolidado |

## Resources (lectura pasiva)

MCP Resources que el cliente puede leer sin invocar tools:

| URI | Datos |
|-----|-------|
| `config://app` | Configuración global |
| `runs://recent` | Últimas 20 ejecuciones |
| `drafts://recent` | Últimos 20 borradores |
| `metrics://roi` | ROI de sub-agentes |
| `metrics://cascade` | Estadísticas de cascade de modelos |

## Prompts (workflows guiados)

| Prompt | Uso |
|--------|-----|
| `plan_creation` | Workflow guiado para crear un plan multi-agente |
| `debug_run` | Analizar una ejecución fallida |
| `optimize_cost` | Sugerir optimizaciones de coste |

## Flujo de routing a modelos locales

Cuando un cliente MCP pide a GIMO que use un modelo local:

```
1. Cliente invoca gimo_chat(message="...", provider="ollama", model="qwen2.5-coder:7b")
2. Bridge → POST /ops/threads/{id}/chat con provider/model params
3. conversation_router → AgenticLoopService.run(provider="ollama", model="qwen2.5-coder:7b")
4. AgenticLoopService → openai_compat.chat_with_tools(base_url="http://localhost:11434/v1")
5. Ollama sirve el modelo localmente, responde con tool calls
6. AgenticLoopService ejecuta tools y continúa el loop
7. Bridge devuelve polling instruction (fire-and-return pattern)
```

### Descubrimiento dinámico de modelos

El catálogo de providers no es estático. `_openrouter_discovery.py` consulta la API gratuita de OpenRouter para descubrir qué modelos están disponibles para correr en Ollama:

- **Filtro**: ≤80B parámetros (práctico para inferencia local)
- **Deduplicación**: Múltiples providers pueden ofrecer el mismo modelo → dedup por `ollama_tag`
- **Cache**: 10 min (éxito), 1 min (fallo), max 30 modelos recomendados
- **Fallback**: Lista estática `_OLLAMA_FALLBACK` si OpenRouter no responde

### Benchmark Enrichment

GIMO sabe **para qué es bueno cada modelo** gracias a:

1. **Seed file** (`data/model_capabilities.json`): 336 perfiles pre-empaquetados de LMArena con scores en 11 dimensiones (coding, math, reasoning, creative, etc.)
2. **Runtime refresh**: Cada 7 días consulta LMArena + Open LLM Leaderboard via HuggingFace datasets-server API
3. **GICS integration**: Los benchmarks externos alimentan el trust engine como priors (20% peso), que GIMO refina con evidencia operativa (80% peso)

```
Endpoint: GET /ops/models/benchmarks
  ?model_id=qwen2.5-coder  → perfil completo + fortalezas
  ?dimension=coding         → ranking de modelos para esa dimensión
  (sin params)              → resumen del catálogo
```

## Seguridad

- **Auth**: Bearer token via `ORCH_TOKEN` env var o archivo `.orch_token`
- **Token caching**: mtime-based para evitar I/O en cada proxy call
- **Rate limiting**: Heredado del backend (por rol: actions=60/min, operator=200/min)
- **Schema drift guard**: Al arrancar, `assert_no_drift()` valida que las firmas Pydantic de los tools nativos coincidan con lo que FastMCP expone. Si hay drift, el bridge se niega a servir.
- **Governance pre-check**: Los clientes pueden llamar `gimo_evaluate_action` antes de ejecutar cualquier tool para obtener un veredicto de gobernanza.

## Arranque del bridge

```python
# server.py::_startup_and_run()
1. Crear directorios de datos
2. Inicializar subsistema de gobernanza (GICS daemon)
3. Auto-arrancar backend HTTP si no está corriendo
4. Registrar dynamic tools (OpenAPI → FastMCP)
5. Registrar native tools (22 tools)
6. Registrar governance tools (8 tools)
7. assert_no_drift() — schema guard
8. Registrar resources y prompts
9. mcp.run_stdio_async()
```

## Archivos clave

| Archivo | Responsabilidad |
|---------|----------------|
| `server.py` | Entry point, arranque, registro de las 3 capas |
| `bridge.py` | `proxy_to_api()`, token cache, retry logic |
| `native_tools.py` | 22 tools con lógica de bridge |
| `governance_tools.py` | 8 tools SAGP |
| `registrar.py` | Legacy manifest-based registration |
| `resources.py` | 5 MCP resources |
| `prompts.py` | 3 MCP prompts |
| `manifest.py` | Manifest de tools (legacy, backup del OpenAPI path) |
| `native_inputs.py` | Pydantic input models para drift guard |
| `_register.py` | `bind()` + `assert_no_drift()` |
| `mcp_app_dashboard.py` | Dashboard HTML embebido |

## Wiring

Ver [SETUP.md § MCP Integrations](./SETUP.md#mcp-integrations-claudeclinecursorantigravity) para configuración de clientes.
