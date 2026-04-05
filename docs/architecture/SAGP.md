# SAGP — Surface-Agnostic Governance Protocol

**Status**: AUTHORITATIVE (Source of Truth)
**Created**: 2026-04-05
**Last verified**: 2026-04-05

---

## 0) Qué es SAGP y por qué existe

### El problema

El 4 de abril de 2026, Anthropic bloqueó el uso de tokens OAuth de suscripción Claude en harnesses de terceros. GIMO usaba `CliAccountAdapter` (`claude -p` subprocess) como provider por defecto — esto **viola directamente la nueva política**.

Sin embargo, los MCP servers llamados DESDE Claude App/Code son explícitamente first-party y están **permitidos**.

### La transformación

SAGP transforma GIMO de **"orquestador que consume LLMs"** a **"autoridad de governance que cualquier LLM consume"**.

La idea central: GIMO no necesita ser el cerebro — necesita ser la **autoridad de governance** que cualquier cerebro (Claude, GPT, Gemini, local) respeta.

### Por qué no otras soluciones

| Alternativa considerada | Por qué se descartó |
|---|---|
| **Solo migrar a API key** | Resuelve compliance pero no aprovecha la oportunidad. GIMO seguiría siendo un orquestador que consume LLMs, limitado a un paradigma que Anthropic puede volver a restringir. |
| **Crear un proxy OAuth** | Viola el espíritu de la política. Anthropic podría bloquear proxies en cualquier momento. Además, acopla GIMO a un mecanismo de autenticación específico. |
| **Abandonar Claude** | Inaceptable. Claude es el modelo más capaz para muchos workflows de GIMO. |
| **Solo usar MCP sin governance** | Funciona técnicamente, pero pierde la oportunidad de hacer que GIMO sea **útil desde cualquier superficie**, no solo Claude. |

SAGP es la única solución que:
1. Cumple compliance (GIMO es MCP server, no consumer)
2. Hace a GIMO más valioso (governance universal)
3. Es future-proof (no depende de políticas de un vendor)

---

## 1) Filosofía técnica

### 1.1 Principio de inversión de control

Antes de SAGP:
```
Claude App → GIMO (orchestrator) → Claude API (consumer)
                                  → OpenAI API
                                  → Ollama
```

Después de SAGP:
```
Claude App ←── GIMO (governance authority via MCP) ──→ Anthropic API
VS Code    ←── GIMO (governance authority via MCP) ──→ OpenAI API
Cursor     ←── GIMO (governance authority via MCP) ──→ Ollama
CLI        ←── GIMO (governance authority via CLI)
Web        ←── GIMO (governance authority via REST)
```

La flecha se invierte: GIMO ya no "llama a Claude" — Claude (y cualquier otra superficie) **consulta a GIMO** antes de actuar.

### 1.2 Governance como servicio, no como barrera

SAGP no es un sistema de permisos estático. Es un **protocolo de evaluación en tiempo real** que combina:

- **Política de ejecución** — qué está permitido (6 niveles de restricción)
- **Confianza empírica** — qué tan fiable es cada provider/modelo (scores + circuit breakers)
- **Economía** — cuánto cuesta y cuánto queda de presupuesto
- **Trazabilidad** — prueba criptográfica de cada acción (SHA256 proof chain)
- **Contexto de superficie** — qué puede hacer esta superficie específica

### 1.3 Thin clients, fat governance

Todas las superficies son **clientes delgados**. Ninguna superficie computa su propia governance. Todas atraviesan el mismo gateway:

```
Surface → SagpGateway.evaluate_action() → GovernanceVerdict → Surface actúa (o no)
```

Esto garantiza **paridad**: un `write_file` evaluado desde Claude App pasa por exactamente la misma lógica que un `write_file` desde VS Code o desde la CLI.

### 1.4 Composición sobre duplicación

SAGP **no reimplementa** lógica existente. Orquesta servicios que ya existen:

| Responsabilidad | Servicio existente | SAGP lo usa como |
|---|---|---|
| Política de ejecución | `ExecutionPolicyService` | Resuelve qué política aplica y qué tools están permitidos |
| Nivel de riesgo | `chat_tools_schema.get_tool_risk_level()` | Clasifica cada acción en LOW/MEDIUM/HIGH |
| Confianza | `TrustEngine` | Scores por dimensión + estado del circuit breaker |
| Costos | `CostService` | Estimación de costo por acción |
| Presupuesto | `BudgetForecastService` | Verifica si hay presupuesto disponible |
| Prueba de ejecución | `ExecutionProofChain` | Genera proof criptográfico por acción |
| Telemetría | `GicsService` | Fiabilidad de modelos, anomalías, métricas |

---

## 2) Componentes de SAGP

### 2.1 SurfaceIdentity — Quién llama

**Archivo**: `tools/gimo_server/models/surface.py`

Identifica de manera inequívoca qué superficie está haciendo una petición.

```python
@dataclass(frozen=True)
class SurfaceIdentity:
    surface_type: SurfaceType       # "claude_app" | "vscode" | "cursor" | "cli" | ...
    surface_name: str               # "Claude Code 1.2.3" | "gimo-cli" | ...
    capabilities: frozenset[str]    # {"streaming", "mcp_apps", "hitl_dialog", ...}
    session_id: str                 # UUID único por sesión
    created_at: datetime            # Timestamp de creación
```

**Tipos de superficie soportados**:

| Tipo | Descripción | Capabilities clave |
|---|---|---|
| `claude_app` | Claude Desktop / Claude Code | streaming, mcp_apps, hitl_dialog, agent_teams, sub_agents |
| `vscode` | VS Code con extensión MCP | streaming, mcp_apps, hitl_dialog |
| `cursor` | Cursor IDE | streaming, hitl_dialog |
| `cli` | GIMO CLI (`gimo` command) | streaming, hitl_inline, ansi_colors |
| `tui` | GIMO TUI (text UI) | streaming, hitl_inline, ansi_colors, panels |
| `web` | GIMO Web dashboard | streaming, hitl_dialog, websocket |
| `chatgpt_app` | ChatGPT Apps vía MCP | mcp_apps, hitl_dialog |
| `mcp_generic` | Cualquier MCP client desconocido | (mínimo) |
| `agent_sdk` | Claude Agent SDK | streaming, sub_agents, hooks |

**Propiedades de consulta rápida**:
- `supports_streaming` — ¿puede recibir SSE?
- `supports_mcp_apps` — ¿puede renderizar `ui://` resources?
- `supports_hitl` — ¿puede pedir confirmación al usuario?
- `supports_agent_teams` — ¿puede coordinar equipos de agentes?

### 2.2 GovernanceVerdict — La decisión

**Archivo**: `tools/gimo_server/models/governance.py`

Resultado inmutable de evaluar cualquier acción. Es la respuesta central de SAGP.

```python
@dataclass(frozen=True)
class GovernanceVerdict:
    allowed: bool                   # ¿Puede ejecutarse?
    policy_name: str                # Política que aplica ("workspace_safe", etc.)
    risk_band: str                  # "low" | "medium" | "high"
    trust_score: float              # 0.0-1.0 (confianza empírica)
    estimated_cost_usd: float       # Costo estimado en USD
    requires_approval: bool         # ¿Necesita HITL?
    circuit_breaker_state: str      # "closed" | "open" | "half_open"
    proof_id: str                   # ID del proof criptográfico generado
    reasoning: str                  # Explicación legible
    constraints: tuple[str, ...]    # Restricciones aplicadas (e.g., "fs:sandbox", "hitl_required")
```

**Semántica de decisión**:
- `allowed=True` + `requires_approval=False` → ejecutar directamente
- `allowed=True` + `requires_approval=True` → pedir confirmación HITL primero
- `allowed=False` → NO ejecutar, mostrar `reasoning` al usuario

### 2.3 GovernanceSnapshot — Estado completo

Agregado de todo el estado de governance en un momento dado. Útil para dashboards y diagnóstico.

```python
@dataclass(frozen=True)
class GovernanceSnapshot:
    surface_type: str
    surface_name: str
    active_policy: str
    trust_profile: dict             # Scores por dimensión
    budget_status: dict             # Presupuesto restante, burn rate
    gics_health: dict               # Daemon alive, entry count
    proof_chain_length: int         # Longitud de la cadena de pruebas
```

### 2.4 SagpGateway — El punto de entrada

**Archivo**: `tools/gimo_server/services/sagp_gateway.py`

El gateway central que todas las superficies deben atravesar. **Orquesta** servicios existentes; **no duplica** lógica.

#### `evaluate_action()` — Evaluación pre-acción

Flujo interno:

```
1. Resolver política → ExecutionPolicyService
2. Verificar tool permitido → policy.assert_tool_allowed()
3. Obtener banda de riesgo → get_tool_risk_level()
4. Consultar trust score → TrustEngine.query_dimension()
5. Estado del circuit breaker → TrustEngine (provider dimension)
6. Estimar costo → CostService.calculate_cost()
7. Verificar presupuesto → lightweight check
8. ¿Requiere HITL? → policy.requires_confirmation + risk_band
9. Decisión final → allowed = tool_ok AND circuit_ok AND budget_ok
10. Generar proof → UUID hex
11. Construir reasoning → explicación de cada factor
12. Retornar GovernanceVerdict
```

#### `get_snapshot()` — Estado agregado

Consulta todas las dimensiones de governance y devuelve un `GovernanceSnapshot`.

#### `get_gics_insight()` — Telemetría read-only

Lectura segura de entradas GICS por prefijo, con límite configurable.

#### `verify_proof_chain()` — Verificación de integridad

Delega a `ExecutionProofChain.verify()` para validar la cadena SHA256 de un thread.

### 2.5 SurfaceNegotiationService — Detección automática

**Archivo**: `tools/gimo_server/services/surface_negotiation_service.py`

Detecta automáticamente qué superficie está llamando y construye su `SurfaceIdentity`.

**Métodos de detección** (en orden de prioridad):

1. **Header explícito**: `X-Gimo-Surface: claude_app`
2. **User-Agent**: patrones conocidos (`Claude/`, `VSCode/`, `Cursor/`, etc.)
3. **Transporte**: `stdio` → MCP client, `sse` → web/app
4. **Default**: `mcp_generic` (capabilities mínimas)

### 2.6 SurfaceResponseService — Respuesta adaptativa

**Archivo**: `tools/gimo_server/services/surface_response_service.py`

Formatea las respuestas de governance según las capabilities de la superficie:

| Capabilities | Formato | Ejemplo |
|---|---|---|
| `mcp_apps` | Rich markdown con UI links | "✅ Allowed — [Open Dashboard](ui://gimo-dashboard)" |
| `ansi_colors` | ANSI terminal con colores Rich | `[green]ALLOWED[/green] policy=workspace_safe` |
| (default) | JSON estructurado | `{"allowed": true, "policy_name": "workspace_safe"}` |

---

## 3) MCP Governance Tools

**Archivo**: `tools/gimo_server/mcp_bridge/governance_tools.py`

8 tools de governance registrados como MCP tools de primera clase:

| Tool | Propósito | Parámetros clave |
|---|---|---|
| `gimo_evaluate_action` | Evaluar si una acción está permitida | tool_name, tool_args_json, thread_id |
| `gimo_estimate_cost` | Estimar costo de una operación | model, input_tokens, output_tokens |
| `gimo_get_trust_profile` | Obtener scores de confianza | dimension_key (provider/model/tool) |
| `gimo_get_governance_snapshot` | Estado completo de governance | thread_id |
| `gimo_get_gics_insight` | Telemetría y métricas GICS | prefix, limit |
| `gimo_verify_proof_chain` | Verificar cadena de pruebas | thread_id |
| `gimo_get_execution_policy` | Obtener perfil de política | policy_name |
| `gimo_get_budget_status` | Estado de presupuesto | scope |

### Ejemplo de uso desde Claude Code

```
User: "Evalúa si puedo escribir en production.config"

Claude llama: gimo_evaluate_action(
    tool_name="write_file",
    tool_args_json='{"path": "production.config"}',
    thread_id="abc123"
)

Resultado:
{
    "allowed": true,
    "policy_name": "workspace_safe",
    "risk_band": "high",
    "trust_score": 0.92,
    "estimated_cost_usd": 0.003,
    "requires_approval": true,
    "reasoning": "Action permitted under policy 'workspace_safe'",
    "constraints": ["fs:sandbox", "hitl_required"]
}
```

---

## 4) MCP Resources de governance

**Archivo**: `tools/gimo_server/mcp_bridge/resources.py`

3 resources adicionales:

| URI | Contenido |
|---|---|
| `governance://snapshot` | GovernanceSnapshot completo en JSON |
| `governance://policies` | Todas las políticas de ejecución disponibles |
| `gics://health` | Salud del daemon GICS + conteo de entradas |

---

## 5) MCP Prompts de governance

**Archivo**: `tools/gimo_server/mcp_bridge/prompts.py`

2 prompts adicionales:

| Nombre | Uso |
|---|---|
| `governance_check` | Workflow de evaluación pre-acción paso a paso |
| `multi_agent_plan` | Creación de plan multi-agente con selección de provider por worker |

---

## 6) MCP App Dashboard

**Archivos**: `mcp_bridge/mcp_app_dashboard.py`, `mcp_bridge/dashboard_template.html`

Dashboard interactivo que se renderiza como MCP App (iframe en Claude Desktop).

### Componentes visuales

| Componente | Datos |
|---|---|
| **Trust Heatmap** | Colores por dimensión (provider, model, tool) |
| **Budget Gauge** | Barra de consumo con alertas de nivel |
| **GICS Health** | Estado del daemon, conteo de entradas |
| **Policy Grid** | 6 políticas con estado actual |
| **Action Log** | Últimas acciones evaluadas |

### Comunicación bidireccional

El dashboard usa `window.parent.postMessage` + listener para comunicarse con Claude Desktop siguiendo la spec de MCP Apps:

```javascript
// Dashboard → Claude (invocar tool)
window.parent.postMessage({
    jsonrpc: "2.0",
    method: "tools/call",
    params: { name: "gimo_get_governance_snapshot" }
}, "*");

// Claude → Dashboard (resultado)
window.addEventListener("message", (event) => {
    // Actualizar UI con datos de governance
});
```

---

## 7) Agent Broker — Spawn multi-provider gobernado

**Archivo**: `tools/gimo_server/services/agent_broker_service.py`

Servicio que selecciona automáticamente el mejor provider/modelo para una tarea y spawna agentes con governance completa.

### Flujo

```
1. Describir tarea (complejidad, tipo, presupuesto)
2. ModelRouterService.choose_model() → ranking de candidatos
3. TrustEngine → filtrar circuit-broken
4. CostService → verificar presupuesto
5. SagpGateway.evaluate_action() → governance check
6. SubAgentManager.create_sub_agent() → spawn real
7. Retornar agente + verdict
```

### `gimo_spawn_subagent` mejorado

El tool MCP existente ahora acepta parámetros opcionales:

```python
@mcp.tool()
async def gimo_spawn_subagent(
    name: str,
    task: str,
    role: str = "worker",
    provider: str = "auto",          # NUEVO: "anthropic", "openai", "ollama", "auto"
    model: str = "auto",              # NUEVO: modelo específico o "auto"
    execution_policy: str = "workspace_safe",  # NUEVO: política por worker
) -> str:
```

---

## 8) Agent Teams — Integración con Claude Code

**Archivo**: `tools/gimo_server/services/agent_teams_service.py`

Genera configuraciones de Claude Code Agent Teams a partir de planes GIMO.

### Flujo

```
Plan GIMO → generate_team_config() → Config de teammates → Claude Code Agent Teams
```

Cada teammate recibe:
- GIMO MCP server cargado
- Política de ejecución específica
- System prompt con constraints de governance

### MCP Tool

```python
@mcp.tool()
async def gimo_generate_team_config(plan_id: str) -> str:
    """Generate Claude Code Agent Teams config from a GIMO plan."""
```

---

## 9) Surface Auto-Discovery — `gimo surface`

**Archivo**: `gimo_cli/commands/surface.py`

Sistema de auto-descubrimiento que configura cualquier superficie MCP sin rutas hardcodeadas.

### Comandos

| Comando | Acción |
|---|---|
| `gimo surface connect <surface>` | Auto-configurar superficie |
| `gimo surface disconnect <surface>` | Desconectar superficie |
| `gimo surface list` | Listar todas las superficies y su estado |
| `gimo surface config` | Mostrar configuración MCP para setup manual |

Valores válidos para `<surface>`: `claude_desktop`, `claude_code`, `vscode`, `cursor`, `all`.

### Auto-descubrimiento

El sistema descubre automáticamente:

1. **Repo root**: `ORCH_REPO_ROOT` env → walk up desde `__file__` → CWD
2. **Python**: `.venv/Scripts/python.exe` → `venv/` → `env/` → `sys.executable`
3. **Config paths**: Rutas por OS (Windows/Darwin/Linux) para cada superficie

### Portabilidad: PYTHONPATH en vez de cwd

**Decisión crítica**: Claude Desktop **no soporta** el campo `cwd` en configuración MCP. La solución:

```json
{
    "command": "C:\\repo\\.venv\\Scripts\\python.exe",
    "args": ["-m", "tools.gimo_server.mcp_bridge.server"],
    "env": {
        "PYTHONPATH": "C:\\repo",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "ORCH_REPO_ROOT": "C:\\repo"
    }
}
```

`PYTHONPATH` permite que `python -m tools.gimo_server.mcp_bridge.server` encuentre el módulo desde cualquier working directory. `ORCH_REPO_ROOT` proporciona la ruta del repo a los servicios internos.

---

## 10) Compliance: Bloqueo de CliAccountAdapter

### Cambios en adapter_registry.py

Para `canonical_type == "claude"` con `auth_mode == "account"`:

1. Buscar `ANTHROPIC_API_KEY` en env
2. Si existe → crear `AnthropicAdapter` con API key (pay-as-you-go, permitido)
3. Si NO existe → `ValueError` con instrucciones claras de migración

Para `canonical_type == "codex"`:
- Sin cambios. OpenAI no ha restringido su CLI.

### Cambios en service_impl.py

Nueva prioridad de `ensure_default_config()`:

```
ANTHROPIC_API_KEY env → codex CLI → ollama local → vacío (con instrucciones)
```

Claude CLI ya **NO** se auto-provisiona. Se muestra warning SAGP con instrucciones.

### Cambios en topology_service.py

`inject_cli_account_providers()` ya **NO** incluye `claude-account` en la lista de specs. Solo inyecta `codex-account` (si codex CLI está disponible).

Sin este cambio, `_normalize_config()` re-inyectaría `claude-account` en cada carga de configuración, deshaciendo la compliance.

---

## 11) Actualizaciones de datos

### model_pricing.json

Context windows actualizados a 1M tokens para todos los modelos Claude 4.x:
- `claude-opus-4`, `claude-opus-4-5`, `claude-opus-4-6`
- `claude-sonnet-4-5`, `claude-sonnet-4-6`

### cost_service.py — Model mappings

Nuevos aliases para modelos 4.6:

```python
"opus-4.5":         "claude-opus-4-5",
"claude-opus-4-5":  "claude-opus-4-5",
"opus-4.6":         "claude-opus-4-6",
"claude-opus-4-6":  "claude-opus-4-6",
"sonnet-4.6":       "claude-sonnet-4-6",
"claude-sonnet-4-6": "claude-sonnet-4-6",
```

---

## 12) Manifest expansion

**Archivo**: `tools/gimo_server/mcp_bridge/manifest.py`

33 nuevos endpoints añadidos para alcanzar ~85% de cobertura MCP:

| Grupo | Endpoints | Cantidad |
|---|---|---|
| Inference | devices, status, models, load, unload, run, register, metrics | 8 |
| App Sessions | create, get, select_repo, recon_list, recon_read, recon_search | 6 |
| Threads extended | config, proofs, usage, fork | 4 |
| Checkpoints | list, get, resume, stats | 4 |
| HITL Action Drafts | list, get, approve, reject, batch_approve | 5 |
| Observability | rate_limits, alerts | 2 |
| Child Runs | spawn, children, pause | 3 |
| GICS native | model_reliability, anomaly_report | 2 |

---

## 13) Integración en Contract

**Archivo**: `tools/gimo_server/models/contract.py`

El `GimoContract` canónico ahora incluye un campo opcional de superficie:

```python
surface: SurfaceIdentity | None = None  # None para callers legacy
```

**Archivo**: `tools/gimo_server/services/contract_factory.py`

Detección automática de superficie desde headers HTTP:

```python
surface_type = request.headers.get("X-Gimo-Surface", "mcp_generic")
```

Backward-compatible: si no hay header, `surface` queda como `None`.

---

## 14) Diagrama de arquitectura

```
┌──────────────────────────────────────────────────────────────────────┐
│                    CUALQUIER SUPERFICIE                              │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │Claude App│ │ VS Code  │ │  Cursor  │ │   CLI    │ │   Web    │  │
│  │Agent Team│ │ Copilot  │ │          │ │   TUI    │ │Dashboard │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │
│       │             │            │             │            │        │
│       └─────────────┴─────┬──────┴─────────────┴────────────┘        │
│                           │                                          │
│                    ┌──────▼──────┐                                    │
│                    │ SAGP Gateway│  ← Autoridad de Governance         │
│                    │             │                                    │
│                    │ • Contract  │  (frozen, inmutable)               │
│                    │ • Policy    │  (6 políticas de ejecución)        │
│                    │ • Trust     │  (scores + circuit breakers)       │
│                    │ • Cost      │  (estimación + presupuesto)        │
│                    │ • Proofs    │  (cadena SHA256)                   │
│                    │ • GICS      │  (telemetría + fiabilidad)         │
│                    └──────┬──────┘                                    │
│                           │                                          │
│              ┌────────────┼────────────┐                             │
│              │            │            │                             │
│        ┌─────▼─────┐ ┌───▼───┐ ┌──────▼──────┐                     │
│        │MCP Tools  │ │  API  │ │ MCP App     │                     │
│        │(142+38    │ │/ops/* │ │ Dashboard   │                     │
│        │governance)│ │       │ │ (ui://)     │                     │
│        └─────┬─────┘ └───┬───┘ └─────────────┘                     │
│              │            │                                          │
│        ┌─────▼────────────▼────────────────────┐                    │
│        │         GIMO Backend (FastAPI)         │                    │
│        │                                        │                    │
│        │  AgenticLoop ──► Agent Broker ──► Provider Adapters        │
│        │                                   │    │    │              │
│        │                              Anthropic OpenAI Ollama       │
│        │                              (API key) (API)  (local)      │
│        └────────────────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 15) Archivos creados/modificados

### Archivos nuevos (10)

| Archivo | Propósito |
|---|---|
| `tools/gimo_server/models/surface.py` | SurfaceIdentity frozen dataclass |
| `tools/gimo_server/models/governance.py` | GovernanceVerdict, GovernanceSnapshot |
| `tools/gimo_server/services/sagp_gateway.py` | Gateway central de governance |
| `tools/gimo_server/services/surface_negotiation_service.py` | Detección + capabilities |
| `tools/gimo_server/services/surface_response_service.py` | Formateo adaptativo |
| `tools/gimo_server/services/agent_broker_service.py` | Spawn multi-provider gobernado |
| `tools/gimo_server/services/agent_teams_service.py` | Config generator para Agent Teams |
| `tools/gimo_server/mcp_bridge/governance_tools.py` | 8 MCP tools de governance |
| `tools/gimo_server/mcp_bridge/mcp_app_dashboard.py` | MCP App dashboard |
| `tools/gimo_server/mcp_bridge/dashboard_template.html` | HTML interactivo |

### Archivos modificados (12)

| Archivo | Cambio |
|---|---|
| `services/providers/adapter_registry.py` | Bloqueo de CliAccountAdapter para Claude |
| `services/providers/service_impl.py` | Nueva prioridad sin claude-account |
| `services/providers/topology_service.py` | Eliminado claude-account de inyección |
| `data/model_pricing.json` | Context windows 1M |
| `services/economy/cost_service.py` | Model 4.6 mappings |
| `models/contract.py` | Campo optional surface |
| `services/contract_factory.py` | Detección de surface desde headers |
| `models/__init__.py` | Exports de nuevos modelos |
| `mcp_bridge/server.py` | Registro de governance + dashboard tools |
| `mcp_bridge/native_tools.py` | Enhanced spawn + GICS + team config tools |
| `mcp_bridge/resources.py` | Governance + GICS resources |
| `mcp_bridge/prompts.py` | Governance check + multi-agent prompts |
| `mcp_bridge/manifest.py` | +33 endpoints |

---

## 16) Testing

### Tests nuevos (3 archivos, ~36 tests)

| Archivo | Qué valida |
|---|---|
| `tests/unit/test_sagp_gateway.py` | GovernanceVerdict, evaluate_action, get_snapshot, get_gics_insight |
| `tests/unit/test_surface_negotiation.py` | negotiate, infer_surface, capabilities |
| `tests/unit/test_compliance.py` | Claude adapter bloqueado, Codex permitido, API key ok, modelos importables |

### Tests modificados

| Archivo | Cambio |
|---|---|
| `tests/unit/test_provider_topology_service.py` | claude-account NO en providers inyectados |
| `tests/unit/test_account_mode_e2e_min.py` | claude-account NO inyectado |

### Resultado final

```
1377 passed, 0 failed
```

---

## 17) Cómo usar SAGP

### Desde Claude Code (MCP)

1. Conectar: `gimo surface connect claude_code`
2. Las tools `gimo_evaluate_action`, `gimo_get_governance_snapshot`, etc. aparecen automáticamente
3. Antes de cualquier acción de riesgo, Claude puede (y debería) llamar a `gimo_evaluate_action`

### Desde Claude Desktop (MCP)

1. Conectar: `gimo surface connect claude_desktop`
2. Reiniciar Claude Desktop
3. El dashboard está disponible via `gimo_dashboard()`

### Desde VS Code / Cursor

1. Conectar: `gimo surface connect vscode` (o `cursor`)
2. Las tools GIMO aparecen en el panel MCP del IDE

### Desde CLI

```bash
gimo surface list              # Ver estado de todas las superficies
gimo surface connect all       # Conectar todas las detectadas
gimo surface config            # Ver config MCP para setup manual
```

### Desde código (Python)

```python
from tools.gimo_server.services.sagp_gateway import SagpGateway
from tools.gimo_server.services.surface_negotiation_service import SurfaceNegotiationService

surface = SurfaceNegotiationService.negotiate("cli")
verdict = SagpGateway.evaluate_action(
    surface=surface,
    tool_name="write_file",
    tool_args={"path": "config.yaml"},
    thread_id="t-abc123",
)

if verdict.allowed and not verdict.requires_approval:
    # Ejecutar
    pass
elif verdict.allowed and verdict.requires_approval:
    # Pedir confirmación HITL
    pass
else:
    print(f"Denegado: {verdict.reasoning}")
```
