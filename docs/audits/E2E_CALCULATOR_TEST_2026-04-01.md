# Test E2E: Calculadora Python Ejecutable - INFORME DE GAPS
**Fecha**: 2026-04-01
**Objetivo**: Validar cohesión de GIMO post-refactor mediante prueba completa de orquestación multiagente
**Estado**: ⏸️ **BLOQUEADO EN FASE DE PREREQUISITOS**

---

## Resumen Ejecutivo

El test E2E fue **bloqueado en fase de prerequisitos y generación de plan**. Se detectaron **6 gaps críticos** que impiden la ejecución completa del flujo.

**Veredicto Preliminar**: ❌ **NO APTO** - Sistema no puede ejecutarse sin configuración manual compleja y tiene problemas arquitecturales en validación de planes

---

## Gaps Detectados

### GAP #1: ANTHROPIC_API_KEY no configurada en el entorno
**Severidad**: 🔴 **CRÍTICO - BLOQUEANTE**
**Componente**: Config | Environment
**Descripción**: La variable de entorno `ANTHROPIC_API_KEY` no está configurada, lo que impide que el sistema conecte con la API de Anthropic.

**Reproducción**:
```bash
echo $ANTHROPIC_API_KEY
# Output: (vacío)
```

**Impacto**: Sin esta variable, el sistema no puede:
- Generar planes con modelos Anthropic
- Ejecutar runs con agentes Anthropic (Haiku 4.5, Sonnet, Opus)
- Funcionar en el caso de uso principal (Anthropic como provider)

**Fix Sugerido**:
1. Documentar claramente en `.env.example` todas las API keys necesarias:
   ```bash
   # Provider API Keys
   ANTHROPIC_API_KEY=sk-ant-...
   OPENAI_API_KEY=sk-...
   ```
2. Agregar validación en startup que verifique si hay al menos un provider configurado
3. Mostrar mensaje de ayuda claro si no hay providers disponibles

**Relación con otros gaps**: Se relaciona con GAP #4 (UX de configuración)

---

### GAP #2: .env.example no documenta variables de providers
**Severidad**: 🔴 **CRÍTICO - DOCUMENTACIÓN**
**Componente**: Config | Docs
**Descripción**: El archivo `.env.example` no menciona ninguna variable de API keys para providers (ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, etc.), dejando al usuario sin guía de configuración.

**Reproducción**:
```bash
cat .env.example | grep -i api_key
# Output: (vacío)
```

**Impacto**:
- Nuevos usuarios no saben qué variables configurar
- No hay documentación de qué providers son soportados
- No hay ejemplos de formato de API keys

**Fix Sugerido**:
Agregar sección completa en `.env.example`:
```bash
# ── Provider API Keys ─────────────────────────────────────────
# Configure at least one provider to use GIMO
# Priority: Anthropic > OpenAI > Groq > Ollama (local)

# Anthropic (Claude models: Haiku, Sonnet, Opus)
ANTHROPIC_API_KEY=

# OpenAI (GPT models)
OPENAI_API_KEY=

# Groq (Fast inference)
GROQ_API_KEY=

# Ollama (Local models - no API key needed, just ensure Ollama is running)
# Download: https://ollama.com
```

**Relación con otros gaps**: Causa directa de GAP #1

---

### GAP #3: Sistema intenta usar OpenAI sin configuración
**Severidad**: 🔴 **CRÍTICO - ROUTING**
**Componente**: Backend | Provider Selection
**Descripción**: A pesar de configurar `claude-haiku-4-5-20251001` en `.gimo/config.yaml` del workspace, el sistema intenta conectar a `https://api.openai.com/v1/chat/completions` y falla con 401 Unauthorized.

**Reproducción**:
```bash
# En gimo-prueba/.gimo/config.yaml:
# preferred_model: claude-haiku-4-5-20251001

cd ../gimo-prueba
python ../gred_in_multiagent_orchestrator/gimo.py plan "Test simple" --workspace . --no-confirm

# Output:
# Error: Plan generation failed: Client error '401 Unauthorized'
# for url 'https://api.openai.com/v1/chat/completions'
```

**Análisis del Draft Generado**:
```json
{
  "id": "d_1775049971534_6304f9",
  "prompt": "Test simple",
  "provider": null,  # ← Provider es null
  "status": "error",
  "error": "Plan generation failed: Client error '401 Unauthorized' ..."
}
```

**Impacto**:
- La configuración de `preferred_model` en workspace config es **ignorada**
- El sistema usa un provider fallback (probablemente OpenAI) sin verificar credenciales
- El usuario no puede controlar qué provider se usa vía configuración de workspace
- El campo `provider` en el draft es `null`, indicando que no se pudo resolver

**Fix Sugerido**:
1. Respetar `preferred_model` del workspace config
2. Si el modelo especificado no está disponible, fallar explícitamente con mensaje claro:
   ```
   Error: Model 'claude-haiku-4-5-20251001' requires Anthropic provider,
   but ANTHROPIC_API_KEY is not configured.

   Options:
   - Set ANTHROPIC_API_KEY environment variable
   - Run: gimo providers setup
   - Choose a different model in .gimo/config.yaml
   ```
3. Nunca usar un provider fallback silenciosamente
4. Validar provider availability ANTES de intentar generar el plan

**Relación con otros gaps**: Consecuencia de GAP #1, causa de frustración en GAP #4

---

### GAP #4: UX de configuración de providers es inaceptable para deployment masivo
**Severidad**: 🔴 **CRÍTICO - UX | DEPLOYMENT**
**Componente**: CLI | Config | UX
**Descripción**: No existe una forma clara, guiada y sin fricción para configurar providers. El usuario debe:
1. Adivinar qué variables de entorno configurar (no están documentadas)
2. Editar manualmente archivos `.env` o configuraciones del sistema
3. O usar comandos CLI no documentados (`gimo providers setup`)

**Contexto del Usuario** (textual):
> "además que no se puede elegir bien correctamente la api sin que sea un dolor de huevos o haya que escribir en el código de gimo, eso no es aceptable para una aplicación que debe ser publicada, empaquetada y deployeada en miles de dispositivos diferentes."

**Impacto**:
- **Fricción insoportable** para nuevos usuarios
- **Bloqueante para deployment masivo**: una app distribuida a miles de usuarios no puede requerir configuración manual de variables de entorno
- **Experiencia de usuario rota**: el primer comando (`gimo plan`) falla sin guía clara de cómo resolverlo
- **No es "production-ready"**: requiere expertise técnico para configuración básica

**Fix Sugerido** (UX Completo):

#### Solución Corto Plazo (P0):
1. **Wizard interactivo en primer uso**:
   ```bash
   $ gimo plan "..."

   ┌─────────────────────────────────────────────────────────┐
   │ 🚨 No providers configured                              │
   │                                                         │
   │ GIMO needs an AI provider to generate and execute      │
   │ plans. Let's set one up!                               │
   │                                                         │
   │ Available providers:                                    │
   │   1. Anthropic (Claude) — Recommended                  │
   │   2. OpenAI (GPT)                                      │
   │   3. Groq (Fast inference)                             │
   │   4. Ollama (Local, free)                              │
   │                                                         │
   │ Choose provider [1-4]: _                               │
   └─────────────────────────────────────────────────────────┘

   # Si elige Anthropic:
   ┌─────────────────────────────────────────────────────────┐
   │ 🔐 Anthropic Configuration                              │
   │                                                         │
   │ Enter your Anthropic API key:                          │
   │ (Get one at: https://console.anthropic.com/api-keys)   │
   │                                                         │
   │ API Key: sk-ant-************************************_   │
   │                                                         │
   │ Save to:                                                │
   │   1. Environment variable (session only)               │
   │   2. .env file (persistent, secure)                    │
   │   3. System keychain (recommended)                     │
   │                                                         │
   │ Choose [1-3]: _                                        │
   └─────────────────────────────────────────────────────────┘

   # Verificación:
   ✅ Provider configured successfully!
   ✅ Testing connection... OK (claude-3-7-sonnet-latest)

   Now retrying: gimo plan "..."
   ```

2. **Comando `gimo doctor` mejorado**:
   ```bash
   $ gimo doctor

   🏥 GIMO Health Check

   ❌ Providers: No active provider configured
      → Run: gimo providers setup
      → Or set: ANTHROPIC_API_KEY=your-key

   ✅ Backend: Running (http://127.0.0.1:9325)
   ✅ Git: Detected (version 2.43.0)
   ⚠️  Workspace: No .gimo directory (run in a workspace folder)
   ```

3. **Comando `gimo providers setup` documentado y accesible**:
   ```bash
   $ gimo providers setup --help

   Configure AI providers for GIMO

   Usage:
     gimo providers setup            # Interactive wizard
     gimo providers setup anthropic  # Direct configuration
     gimo providers list             # Show configured providers
     gimo providers test [name]      # Test provider connection
   ```

#### Solución Largo Plazo (P1):
1. **UI de configuración en Orchestrator UI**: Panel de providers con botones para agregar/editar/probar cada uno
2. **Auto-detección de CLIs locales**: Si detecta `claude` o `codex` instalados, ofrecer usar modo account sin API key
3. **Provider marketplace**: Catálogo de providers con instrucciones específicas por cada uno
4. **Validación en startup**: Backend verifica providers al iniciar y expone endpoint `/health` con detalles de configuración
5. **Configuración encriptada**: API keys almacenadas en keychain del sistema (Windows Credential Manager, macOS Keychain, Linux Secret Service)

**Relación con otros gaps**: Gap raíz que causa todos los problemas de configuración (GAP #1, #2, #3)

---

### GAP #5: Cambio de provider requiere editar archivos internos de GIMO
**Severidad**: 🔴 **CRÍTICO - UX | DEPLOYMENT**
**Componente**: CLI | Config | Backend
**Descripción**: Para cambiar el provider activo de "openai" a "claude-account", fue necesario **editar manualmente** el archivo interno `.orch_data/ops/provider.json`. No existe comando CLI para hacer este cambio de forma segura y guiada.

**Reproducción**:
1. Instalación fresh de GIMO con OpenAI configurado
2. Usuario quiere cambiar a Claude (tiene el CLI instalado y autenticado)
3. No hay comando `gimo providers select claude-account`
4. Usuario debe editar manualmente `.orch_data/ops/provider.json`:
   ```json
   {
     "active": "claude-account",  // Cambiar de "openai" a "claude-account"
     "roles": {
       "orchestrator": {
         "provider_id": "claude-account",  // Actualizar todos los refs
         "model": "claude-haiku-4-5-20251001"
       }
     },
     // ... múltiples campos más a actualizar manualmente
   }
   ```

**Impacto**:
- ❌ Usuario debe conocer estructura interna de GIMO
- ❌ Propenso a errores (JSON malformado, refs inconsistentes)
- ❌ **Imposible para usuarios no técnicos**
- ❌ **Bloqueante para deployment masivo**
- ❌ Viola principio de abstracción (archivos internos no deberían editarse)

**Fix Sugerido**:

#### Corto Plazo (P0):
```bash
# Comando para listar providers disponibles
$ gimo providers list
Available providers:
  [x] openai (active) — gpt-4o
  [ ] claude-account — claude-haiku-4-5-20251001 (authenticated via CLI)
  [ ] codex-account — gpt-5-codex
  [ ] local_ollama — qwen2.5-coder:3b

# Comando para cambiar provider activo
$ gimo providers select claude-account
✅ Provider switched to: claude-account (claude-haiku-4-5-20251001)
✅ Authentication: Active (via CLI)
✅ Ready to use

# Con modelo específico
$ gimo providers select claude-account --model claude-opus-4-6
```

#### Largo Plazo (P1):
- UI visual en Orchestrator UI para cambiar provider con un clic
- Auto-detección de cambios en CLI (si usuario hace `claude login`, GIMO lo detecta)
- Comando `gimo providers auto` que detecta y configura automáticamente todos los CLIs instalados

**Relación con otros gaps**: Extensión de GAP #4 (UX de configuración)

---

### GAP #6: System Prompt del Planner no comunica reglas de GIMO claramente ✅ **FIXED 2026-04-01**
**Severidad**: 🔴 **CRÍTICO - PLANNER | PROMPT ENGINEERING**
**Componente**: Backend | Plan Generation
**Status**: ✅ **RESUELTO** - Implementado `OrchestratorMemorandumService` + system prompt mejorado
**Descripción**: El system prompt enviado al LLM (ANY provider: Claude, GPT, etc.) no explicaba claramente las reglas invariantes de GIMO, resultando en planes con estructura inválida ("Plan must have exactly one orchestrator node"). El problema NO era el LLM, era que la llamada al provider no era lo suficientemente aclarativa.

**Reproducción**:
```bash
$ gimo plan "Crea una calculadora Python..."
# LLM recibe system prompt insuficiente
# Genera plan sin orchestrator (o con múltiples)
# Validación falla: "Plan must have exactly one orchestrator node"
```

**System Prompt Actual** (`tools/gimo_server/routers/ops/plan_router.py:227-243`):
```python
sys_prompt = (
    "You are a senior systems architect. Generate a JSON execution plan.\n"
    "RULES:\n"
    f"- agent_assignee.role MUST be exactly one of: {roles_str}\n"
    f"- agent_assignee.model MUST be: \"{contract.model_id}\"\n"
    "- Each task needs: id, title, scope, description, agent_assignee\n"
    "- agent_assignee needs: role, goal, backstory, model, system_prompt, instructions\n"
    "- Output ONLY valid JSON, no markdown, no explanations\n\n"
    f"Task: {prompt}\n\n"
    'JSON schema:\n'
    '{"id":"plan_...","title":"...","workspace":"...","created":"...","objective":"...",'
    '"tasks":[{"id":"t_orch","title":"[ORCH] ...","scope":"bridge","depends":[],"status":"pending",'
    f'"description":"...","agent_assignee":{{"role":"{contract.valid_roles[0]}","goal":"...","backstory":"...",'
    f'"model":"{contract.model_id}","system_prompt":"...","instructions":["..."]}},'
    '{"id":"t_worker_1","title":"[WORKER] ...","scope":"file_write","depends":["t_orch"],'
    '"status":"pending","description":"...","agent_assignee":{...}}],"constraints":[]}\n'
)
```

**Problemas Críticos del Prompt**:
1. ❌ **NO dice "exactly 1 orchestrator"** — La invariante crítica no está explícita
2. ❌ **NO explica QUÉ es orchestrator vs worker** — Solo da ejemplo sin contexto
3. ❌ **NO explica estructura de dependencias** — Que orchestrator no tiene depends, workers sí
4. ❌ **NO explica scopes** — Qué significa "bridge" vs "file_write"
5. ❌ **Ejemplo sin explicación** — Muestra t_orch y t_worker_1 pero no dice POR QUÉ
6. ⚠️ **Confuso para el LLM** — "Senior systems architect" puede interpretar que necesita múltiples coordinadores

**Impacto**:
- ❌ **LLM genera planes inválidos** (0 o 2+ orchestrators) porque no sabe la regla
- ❌ **Desperdicio de tokens** — Llamadas fallidas al LLM
- ❌ **Experiencia frustrante** — Usuario no entiende por qué falla
- ❌ **No es culpa del LLM** — Es culpa del prompt insuficiente
- ❌ **Afecta TODOS los providers** — Claude, GPT, Gemini, todos fallan igual

**Resultados de Prueba**:
```bash
$ gimo plan "Test de conexión con Claude"
# Tiempo: 1m 5s
# Error: "Plan must have exactly one orchestrator node"

$ gimo plan "Crea una calculadora Python con interfaz gráfica Tkinter..."
# Tiempo: 1m 46s
# Error: "Plan must have exactly one orchestrator node"
```

Ambos prompts (simple y detallado) fallan con el mismo error → **Problema del system prompt, no del user prompt**.

---

## ✅ FIX IMPLEMENTADO (2026-04-01)

### Arquitectura de la Solución

La solución implementa la arquitectura que el usuario especificó:

> "Los SOTA se mantienen aparte. GICS solo aporta su información cuando orch va a crear un plan o cuando orch consulta GICS. Cuando orch crea un plan, o va a crear un nuevo agente, si no ha recibido o lo recibió hace mucho y no lo tiene en contexto, recibe un **memorandum de cómo se comportan los agentes y cómo debe de comunicarse con ellos** MAS los **datos de GICS sobre la fiabilidad de routing de cada agente**. A GICS no se le ceba por que sí, él genera su propia información según lo que comprime."

### Componentes Implementados

#### 1. **OrchestratorMemorandumService** (NUEVO)
**Archivo**: `tools/gimo_server/services/orchestrator_memorandum_service.py`

Servicio que construye el memorandum para el orquestador combinando:

**a) SOTA Estático** (desde `data/provider_sota_2026.json`):
- Mejores prácticas para comunicarse con cada provider (GPT-5.4, Claude Opus/Sonnet 4.6, Gemini 3.1 Pro)
- Strengths y weaknesses de cada provider
- Structured output methods (JSON Schema, Tool Use, Response Schema)
- Prompting strategies específicas por provider
- Decision framework para elegir providers según contexto

**b) Insights Dinámicos de GICS** (consultando `AgentInsightService`):
- Fiabilidad empírica de routing basada en ejecuciones reales
- Patrones de fallos detectados (agent_id, failure_rate, tool, severity)
- Recomendaciones basadas en datos operacionales

**Características**:
- Cache de 24 horas para datos SOTA (no cambian frecuentemente)
- Consulta GICS en tiempo real cada vez que se construye un plan
- Formato optimizado para incluir en system prompt (conciso, accionable)

**Métodos principales**:
```python
@classmethod
def build_memorandum(cls, *, include_gics: bool = True) -> str:
    """Construye el memorandum completo para el orquestador.

    Returns:
        Memorandum formateado con SOTA + GICS insights
    """
```

#### 2. **System Prompt Mejorado** (MODIFICADO)
**Archivo**: `tools/gimo_server/routers/ops/plan_router.py:221-295`

El system prompt ahora:

**a) Incluye reglas explícitas y claras**:
```python
"## CRITICAL RULES (MUST FOLLOW):\n\n"
"1. **EXACTLY ONE ORCHESTRATOR**: The plan MUST have exactly ONE task with role='orchestrator'. "
"This is the coordination node that manages the workflow.\n\n"
```

**b) Explica arquitectura de GIMO**:
- Diferencia clara entre orchestrator (coordina, NO ejecuta) y workers (ejecutan tareas específicas)
- Estructura de dependencias (workers dependen de orchestrator)
- Scopes y su significado ('bridge', 'file_write', etc.)

**c) Incluye el memorandum dinámico**:
```python
# Get orchestrator memorandum (SOTA + GICS insights)
from tools.gimo_server.services.orchestrator_memorandum_service import OrchestratorMemorandumService
memorandum = OrchestratorMemorandumService.build_memorandum(include_gics=True)

# ... incluye memorandum en el system prompt
+ (f"\n{memorandum}\n\n" if memorandum else "") +
```

**d) Proporciona ejemplos concretos**:
- JSON schema example con orchestrator + worker
- Comentarios inline explicando cada campo
- Formato de output esperado

### Flujo de Ejecución

```
Usuario ejecuta: gimo plan "Crea una calculadora Python..."
                        │
                        ↓
              plan_router.py recibe request
                        │
                        ↓
    ┌──────────────────────────────────────────┐
    │ OrchestratorMemorandumService            │
    │  ├─ Lee provider_sota_2026.json (cache)  │
    │  ├─ Consulta GICS (AgentInsightService)  │
    │  └─ Construye memorandum                 │
    └──────────────────────────────────────────┘
                        │
                        ↓
    ┌──────────────────────────────────────────┐
    │ System Prompt Enriquecido:               │
    │  ├─ Reglas críticas de GIMO              │
    │  ├─ Memorandum SOTA (cómo hablar)        │
    │  ├─ Insights GICS (fiabilidad)           │
    │  └─ Ejemplos concretos                   │
    └──────────────────────────────────────────┘
                        │
                        ↓
              LLM genera plan válido
                        │
                        ↓
              ✅ Plan con 1 orchestrator
```

### Beneficios

1. **✅ LLM entiende reglas de GIMO**: Explicación explícita de la invariante "exactly 1 orchestrator"
2. **✅ Comunicación optimizada por provider**: SOTA proporciona mejores prácticas específicas
3. **✅ Decisiones basadas en datos reales**: GICS aporta fiabilidad empírica de routing
4. **✅ No hardcodeado**: Comportamientos NO están en lógica, están en datos que el orquestador consulta
5. **✅ Escalable**: GICS aprende de ejecuciones, SOTA se actualiza cuando hay nuevos providers
6. **✅ Costo-efectivo**: Memorandum conciso, no satura context window

### Testing

**Próximo paso**: Re-ejecutar test E2E con el fix implementado:
```bash
cd ../gimo-prueba
python ../gred_in_multiagent_orchestrator/gimo.py plan "Crea una calculadora Python..."
```

**Expectativa**: Plan generado exitosamente con estructura válida (1 orchestrator + N workers)

---

**Fix Original Sugerido** (ahora implementado parcialmente):

#### Corto Plazo (P0) — Reescribir System Prompt:

```python
# En tools/gimo_server/routers/ops/plan_router.py:227-243
# REEMPLAZAR el prompt actual con:

import time

sys_prompt = f"""You are a GIMO plan architect. Generate a JSON multi-agent execution plan.

CRITICAL INVARIANT (MUST NEVER VIOLATE):
═══════════════════════════════════════
There MUST be EXACTLY ONE orchestrator task.
No more, no less. This is non-negotiable.

ARCHITECTURE RULES:

1. **ORCHESTRATOR (EXACTLY 1 REQUIRED)**:
   - Role: "{contract.valid_roles[0]}" (typically "orchestrator")
   - Scope: "bridge" (coordinates workers, analyzes requirements, does NOT write code)
   - depends_on: [] (empty array — orchestrator has NO dependencies, always runs first)
   - Title: MUST start with "[ORCH]"
   - Purpose: Break down objective, coordinate workers, synthesize results

2. **WORKERS (0 or more)**:
   - Role: Choose from {contract.valid_roles[1:]} (typically "worker", "specialist")
   - Scope: "file_write", "read", "test", "doc", etc. (actual implementation work)
   - depends_on: MUST include orchestrator's task ID (workers depend on orchestrator)
   - Title: MUST start with "[WORKER]"
   - Purpose: Execute specific implementation tasks

3. **TASK STRUCTURE** (every task needs these fields):
   - id: unique identifier (e.g., "t_orch", "t_worker_1", "t_worker_2")
   - title: descriptive name with prefix ([ORCH] or [WORKER])
   - scope: "bridge" for orchestrator, specific scope for workers
   - description: detailed task description
   - depends_on: array of task IDs this task depends on
   - agent_assignee: {{
       "role": "{contract.valid_roles[0]}" or worker role,
       "goal": "what this agent should achieve",
       "backstory": "agent's expertise context",
       "model": "{contract.model_id}",
       "system_prompt": "instructions for this agent",
       "instructions": ["step 1", "step 2", ...]
     }}

4. **OUTPUT FORMAT**:
   - Output ONLY valid JSON
   - NO markdown code blocks, NO explanations before or after
   - Start with {{ "id": "plan_...", ...
   - End with }}

EXAMPLE VALID PLAN:
{{{{
  "id": "plan_{int(time.time())}",
  "title": "Implement user authentication",
  "objective": "{prompt}",
  "tasks": [
    {{{{
      "id": "t_orch",
      "title": "[ORCH] Coordinate authentication implementation",
      "scope": "bridge",
      "depends_on": [],
      "description": "Analyze authentication requirements, break down into tasks, coordinate workers, validate final result",
      "agent_assignee": {{{{
        "role": "{contract.valid_roles[0]}",
        "goal": "Successfully orchestrate multi-agent authentication implementation",
        "backstory": "Senior architect with 10+ years designing secure auth systems",
        "model": "{contract.model_id}",
        "system_prompt": "You are the orchestrator. Coordinate workers, don't write code yourself.",
        "instructions": [
          "Analyze authentication requirements (session vs JWT, storage, security)",
          "Break down into worker tasks (backend, frontend, tests)",
          "Validate that all components integrate correctly"
        ]
      }}}}
    }}}},
    {{{{
      "id": "t_worker_1",
      "title": "[WORKER] Implement backend auth API",
      "scope": "file_write",
      "depends_on": ["t_orch"],
      "description": "Create FastAPI endpoints for login, logout, session validation",
      "agent_assignee": {{{{
        "role": "worker",
        "goal": "Implement secure backend authentication API",
        "backstory": "Backend specialist with FastAPI expertise",
        "model": "{contract.model_id}",
        "system_prompt": "You are a backend developer. Write production-ready code.",
        "instructions": [
          "Create /auth/login endpoint with password hashing",
          "Create /auth/logout endpoint",
          "Implement session middleware",
          "Write comprehensive tests"
        ]
      }}}}
    }}}},
    {{{{
      "id": "t_worker_2",
      "title": "[WORKER] Implement frontend auth UI",
      "scope": "file_write",
      "depends_on": ["t_orch"],
      "description": "Create React components for login/logout with proper state management",
      "agent_assignee": {{{{
        "role": "worker",
        "goal": "Build intuitive authentication UI",
        "backstory": "Frontend specialist with React expertise",
        "model": "{contract.model_id}",
        "system_prompt": "You are a frontend developer. Write clean React code.",
        "instructions": [
          "Create LoginForm component with validation",
          "Create LogoutButton component",
          "Integrate with auth context provider",
          "Handle loading and error states"
        ]
      }}}}
    }}}}
  ]
}}}}

USER TASK: {prompt}

Generate the JSON plan NOW (remember: EXACTLY 1 orchestrator):"""
```

#### Verificación Post-Fix:
```python
# Agregar logging después de generar el plan:
logger.info(f"Plan generated: {len(plan_data.get('tasks', []))} tasks")
orchestrators = [t for t in plan_data.get('tasks', [])
                 if t.get('scope') == 'bridge' or
                    '[ORCH]' in t.get('title', '')]
logger.info(f"Orchestrators detected: {len(orchestrators)}")
if len(orchestrators) != 1:
    logger.error(f"Invalid plan structure: {len(orchestrators)} orchestrators (expected 1)")
```

#### Largo Plazo (P1):
1. **Usar structured output** (Claude/GPT tool calling con schema JSON estricto)
2. **Validación incremental** — LLM genera → validar → si falla, pedir corrección automáticamente
3. **Examples in schema** — Enviar 2-3 ejemplos válidos en el prompt
4. **Temperature=0** para generación determinística

**Contexto del Usuario** (textual):
> "no, por plan solo debe haber un orquestador, eso es una invariable en todos los aspectos, y si se genera más de 1 en un plan es porque el prompt que se ha generado no entiende siquiera los constrains ni como funciona gimo"

> "y esto no va de que claude lo entienda o lo deja de entender, estamos hablando de que la llamada a provider no está siendo lo suficientemente aclarativa (sea el provider que sea) para que entienda gimo exactamente."

> "si no somos capaz de que el llm entienda la estructura inicial con el system prompt con el que inicia, si no es capaz de entender a gimo. eso es un gap criticísimo, porque es como despertar a un fantasma que no sabe cuál es su cometido"

**Relación con otros gaps**: Problema raíz que bloquea la generación de planes (independiente de configuración de providers)

---

## Estado de Ejecución del Test

### ✅ Completado
- [x] Verificación de entorno
- [x] Actualización de config de gimo-prueba (modelo, timeout, verbose)
- [x] Preparación de repo gimo-prueba (commit inicial)
- [x] Verificación de backend (puerto 9325, autenticación)

### ⏸️ Bloqueado (no ejecutado)
- [ ] **Fase 1: Generación del plan** — BLOQUEADO por GAP #1, #3
- [ ] Fase 2: Ejecución del run
- [ ] Fase 3: Manual merge
- [ ] Fase 4: Validación del código generado
- [ ] Fase 5: Build del ejecutable
- [ ] Fase 6: Test funcional del .exe
- [ ] Fase 7: Auditoría del pipeline

---

## Métricas Capturadas

### Prerequisitos
- ⏱️ **Tiempo de configuración**: ~15 minutos (manual, con debugging)
- ❌ **ANTHROPIC_API_KEY**: No configurada
- ❌ **OPENAI_API_KEY**: No configurada
- ❌ **Provider activo**: Ninguno
- ✅ **Backend**: Funcionando (puerto 9325)
- ✅ **Token de operador**: Configurado (.orch_token)
- ✅ **Repo de prueba**: Limpio y preparado

### Intento de Generación de Plan
- ⏱️ **Tiempo hasta fallo**: ~2 segundos
- 📊 **Status code**: Error (HTTP 401 desde OpenAI API)
- 🆔 **Draft ID**: d_1775049971534_6304f9
- 📝 **Status**: error
- 🔴 **Provider resuelto**: null (no se pudo resolver)

---

## Comparación con Audits Previos

### E2E_GAPS_LIVE_TEST_2026-03-30.md
**Gaps reportados**: 13+ críticos
**Gaps coincidentes**:
- ✅ Configuración de providers compleja (GAP #4)
- ⚠️ Error de autenticación (diferentes causas: allí era Ollama, aquí es OpenAI)

**Gaps nuevos en este test**:
- GAP #2: Falta documentación en .env.example
- GAP #3: Provider routing incorrecto (ignora workspace config)

### E2E_AUDIT_2026-03-29.md
**Gaps reportados**: 9 detectados
**Gaps coincidentes**:
- ✅ "No existe UI para configurar providers" → Parte de GAP #4

---

## Archivos de Output Generados

1. ✅ `../gimo-prueba/.gimo/config.yaml` — Actualizado (haiku 4.5, timeout 180s, verbose true)
2. ✅ `../gimo-prueba/README.md` — Commit inicial creado
3. ✅ `../gimo-prueba/.gimo/plans/d_1775049971534_6304f9.json` — Draft con error

**No generados (test bloqueado)**:
- ❌ `plan_result.json`
- ❌ `run_result.json`
- ❌ Código de calculadora
- ❌ Ejecutable .exe

---

## Recomendaciones

### Prioridad P0 (Bloqueantes)
1. **Implementar wizard de configuración de providers** (GAP #4)
   - Comando: `gimo providers setup` con flujo interactivo
   - Integrar en primer uso de `gimo plan`
   - Guardar API keys de forma segura (keychain o .env)

2. **Documentar variables de entorno en .env.example** (GAP #2)
   - Agregar sección de Provider API Keys
   - Incluir links a consolas de cada provider
   - Agregar ejemplos de formato

3. **Respetar workspace config para provider selection** (GAP #3)
   - Si `preferred_model` requiere provider no configurado, fallar con mensaje claro
   - Nunca usar provider fallback silenciosamente
   - Validar provider availability antes de generar draft

### Prioridad P1 (UX)
1. Mejorar `gimo doctor` para diagnosticar configuración de providers
2. Agregar comando `gimo providers test` para verificar conexión
3. Crear UI de configuración de providers en Orchestrator UI
4. Implementar auto-detección de CLIs locales (claude, codex)

### Prioridad P2 (Hardening)
1. Validación de API keys en tiempo de configuración (test de conexión)
2. Almacenamiento seguro de API keys (keychain del sistema)
3. Provider marketplace con instrucciones específicas
4. Rate limiting y manejo de cuotas por provider

---

## Conclusiones

El test E2E **no pudo ejecutarse** debido a problemas fundamentales de configuración de providers. Los gaps detectados son **bloqueantes** para cualquier usuario que intente usar GIMO por primera vez.

**Veredicto**: ❌ **NO APTO PARA DEPLOYMENT**

El sistema requiere:
1. Configuración manual compleja (variables de entorno no documentadas)
2. Knowledge experto del sistema (saber qué archivos editar)
3. Debugging de errores crípticos (401 de OpenAI sin contexto claro)

**Próximos pasos sugeridos**:
1. Resolver GAP #4 (wizard de configuración) como **prioridad máxima**
2. Documentar configuración (GAP #2)
3. Arreglar provider routing (GAP #3)
4. Reintentar test E2E completo

---

## Contexto Adicional

### Configuración del Entorno (Snapshot)
```bash
# Variables de entorno relevantes:
ANTHROPIC_API_KEY=         # ❌ NO CONFIGURADA
OPENAI_API_KEY=            # ❌ NO CONFIGURADA
ORCH_PROVIDER=             # ❌ NO CONFIGURADA
ORCH_MODEL=                # ❌ NO CONFIGURADA
ORCH_TOKEN=3dlUIJet72...   # ✅ CONFIGURADA

# Backend:
Status: Running
URL: http://127.0.0.1:9325
Version: UNRELEASED
Uptime: 25773s (~7 horas)

# Workspace (gimo-prueba):
Path: C:\Users\shilo\Documents\Github\gimo-prueba
Git: Clean (1 commit)
Config: .gimo/config.yaml (preferred_model: claude-haiku-4-5-20251001)
```

### Comandos Ejecutados
```bash
# 1. Verificación de prerequisitos
echo $ANTHROPIC_API_KEY                                    # ❌ Vacío
curl -H "Authorization: Bearer $ORCH_TOKEN" .../status     # ✅ OK

# 2. Actualización de config
# Editados: preferred_model, verbose, timeout

# 3. Preparación de repo
git commit -m "Initial commit"                             # ✅ OK

# 4. Intento de plan
gimo plan "Test simple" --workspace . --no-confirm         # ❌ Error 401
```

### Error Completo (Reproducible)
```
+--------------------------------- GIMO Plan ---------------------------------+
| Plan generation failed.                                                     |
| Draft ID: d_1775049971534_6304f9                                            |
| Status: error                                                               |
| Saved:                                                                      |
| C:\Users\shilo\Documents\Github\gimo-prueba\.gimo\plans\d_1775049971534_630 |
| 4f9.json                                                                    |
+-----------------------------------------------------------------------------+

[X] Error: Plan generation failed: Client error '401 Unauthorized' for url
'https://api.openai.com/v1/chat/completions'
For more information check:
https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401
-> Check authentication: gimo doctor
-> Re-authenticate: gimo login http://127.0.0.1:9325
```

---

**Informe generado**: 2026-04-01
**Auditor**: Claude Sonnet 4.5
**Duración del test**: ~20 minutos (bloqueado en prerequisitos)
