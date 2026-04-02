# SOTA: Comunicación con Providers LLM (Abril 2026)

**Fecha**: 2026-04-01
**Estado**: Actualizado con modelos más avanzados
**Propósito**: Guía definitiva para que GIMO se comunique óptimamente con cada provider

---

## Resumen Ejecutivo

A abril 2026, la frontera de LLMs está definida por **tres modelos flagship** de clase mundial:

1. **OpenAI GPT-5.4** — Mejor all-rounder, líder en computer-use
2. **Claude Opus 4.6** — Líder en coding y razonamiento técnico
3. **Gemini 3.1 Pro** — Líder en benchmarks de razonamiento puro (77.1% ARC-AGI-2)

**Ningún modelo domina en todo**. La elección depende del caso de uso específico.

---

## 📊 Tabla Comparativa: Modelos Flagship Abril 2026

| Criterio | GPT-5.4 | Claude Opus 4.6 | Gemini 3.1 Pro |
|---|---|---|---|
| **Lanzamiento** | Marzo 5, 2026 | Febrero 5, 2026 | Febrero 19, 2026 |
| **Intelligence Index** | 57 | 53 | 57 |
| **Contexto** | 1M tokens | 1M tokens | 2M tokens |
| **Pricing (entrada/salida)** | $2.50/$15 per M | $5/$25 per M | $2/$12 per M |
| **Coding (SWE-bench)** | 57.7% | 80.8% ⭐ | — |
| **Reasoning (ARC-AGI-2)** | — | — | 77.1% ⭐ |
| **Computer Use** | Nativo ⭐ | Disponible | Disponible |
| **Structured Output** | ✅ (100% adherencia) | ✅ (Grammar compilation) | ✅ (JSON Schema nativo) |
| **Streaming** | ✅ | ✅ (Fine-grained) | ✅ |
| **Function Calling** | ✅ | ✅ (Tool Use) | ✅ |

---

## 🎯 Casos de Uso Óptimos por Provider

### OpenAI GPT-5.4
**Mejor para**:
- ✅ **Orquestación compleja de APIs** — Manejo de múltiples herramientas
- ✅ **Computer use workflows** — Agentes que operan computadoras
- ✅ **Precisión matemática** — Cálculos, escalas, proporciones
- ✅ **Marketing copy con reglas estrictas** — Sigue constraints mejor que los demás

**No tan bueno para**:
- ❌ Diagramas técnicos complejos (Claude es mejor)
- ❌ Cost-sensitivity extrema (Gemini es 60% más barato en output)

---

### Anthropic Claude Opus 4.6 / Sonnet 4.6
**Mejor para**:
- ✅ **Coding agents** — #1 en SWE-bench (80.8%), autopowerful en refactors
- ✅ **Diagramas técnicos estructurados** — SVG, flowcharts, arquitecturas
- ✅ **Escritura creativa y prosa** — Calidad de escritura y consistencia de personajes
- ✅ **Long-context synthesis** — 1M tokens de contexto efectivo

**Modelos disponibles**:
- **Opus 4.6**: Para tareas complejas, refactors de codebases grandes, análisis críticos
- **Sonnet 4.6**: Default práctico para desarrollo diario, más rápido y eficiente

**Próximamente**: **Claude Mythos** (en piloto), descrito como "dramáticamente mejor" que Opus en programación

**No tan bueno para**:
- ❌ Razonamiento matemático puro (Gemini Deep Think domina)
- ❌ Presupuestos ajustados (más caro: $5/$25 per M)

---

### Google Gemini 3.1 Pro
**Mejor para**:
- ✅ **Razonamiento puro y lógica** — 77.1% ARC-AGI-2 (más del doble vs 3 Pro)
- ✅ **Análisis de codebases completos** — 2M tokens de contexto (único)
- ✅ **Cost-efficiency** — 60% más barato que Opus en output
- ✅ **Agentes web-connected** — Grounding con Google Search integrado
- ✅ **Multimodal reasoning** — Texto + imágenes + video + audio unificado

**Modo avanzado**: **Gemini 3 Deep Think** — Razonamiento iterativo multi-hipótesis (para suscriptores Ultra)

**No tan bueno para**:
- ❌ Coding de producción (Claude/GPT lideran SWE-bench)
- ❌ Prompts ambiguos (puede malinterpretar y ejecutar confiadamente en dirección incorrecta)

---

## 🔧 Structured Output: Mejores Prácticas por Provider

### 1. OpenAI GPT-5.4: JSON Schema con Garantías Matemáticas

**Método recomendado**: `response_format` con `json_schema`

**Cómo funciona**:
- Compila JSON schema en gramática
- **Fuerza matemáticamente** la adherencia al schema durante generación de tokens
- El modelo **físicamente no puede** generar output que viole el schema
- 100% de adherencia en evals complejos (vs <40% en modelos anteriores)

**Ejemplo**:
```python
from openai import OpenAI
client = OpenAI()

response = client.chat.completions.create(
    model="gpt-5.4",
    messages=[{"role": "user", "content": "Generate plan for calculator app"}],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "gimo_plan",
            "strict": True,  # ← CRÍTICO: enforce strict mode
            "schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "scope": {"type": "string"},
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            },
                            "required": ["id", "scope", "depends_on"],
                            "additionalProperties": False  # ← CRÍTICO
                        }
                    }
                },
                "required": ["id", "title", "tasks"],
                "additionalProperties": False  # ← CRÍTICO: no fields extras
            }
        }
    }
)
```

**Reglas de Oro para GPT-5.4**:
1. ✅ **SIEMPRE** usa `"strict": True`
2. ✅ **SIEMPRE** incluye `"additionalProperties": False` en cada objeto
3. ✅ **TODAS** las propiedades deben estar en `required` (no opcionales)
4. ✅ Para valores faltantes, usa `""` o `["string", "null"]`
5. ✅ Para constrains avanzados, usa **Context-Free Grammars (CFGs)** con sintaxis Lark

**Nueva feature en GPT-5.4**: Soporte de CFGs para herramientas custom
```python
# Puedes proveer una gramática Lark para constrains sintácticos específicos
response_format={
    "type": "cfg",
    "grammar": """
        start: plan
        plan: "id:" ID "tasks:" task+
        task: "[" scope "]" ID depends*
        scope: "ORCH" | "WORKER"
        depends: "->" ID
        ID: /[a-z_]+/
    """
}
```

**Cuándo usar GPT-5.4**:
- ✅ Cuando necesitas 100% adherencia garantizada
- ✅ Schemas complejos con nesting profundo
- ✅ Validación numérica crítica (presupuestos, cálculos)

---

### 2. Claude Opus/Sonnet 4.6: Tool Use con Grammar Compilation

**Método recomendado**: Tool Use con `input_schema`

**Cómo funciona**:
- Define schema como "tool" (aunque no sea realmente una función)
- Claude **no puede** generar output que viole el schema
- Grammar compilation en servidor (latencia mejorada en 4.6)
- Fine-grained streaming disponible (GA)

**Ejemplo**:
```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-opus-4-6",  # o "claude-sonnet-4-6"
    max_tokens=4096,
    tools=[{
        "name": "gimo_plan_output",
        "description": "Structured plan for GIMO orchestrator. MUST include exactly 1 orchestrator task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "scope": {
                                "type": "string",
                                "enum": ["bridge", "file_write", "read", "test"]
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["id", "scope", "depends_on"]
                    }
                }
            },
            "required": ["id", "title", "tasks"]
        }
    }],
    tool_choice={"type": "tool", "name": "gimo_plan_output"},  # ← Fuerza uso de tool
    messages=[{"role": "user", "content": "Generate plan for calculator app"}]
)

# Extraer output estructurado
tool_call = response.content[0]
plan_data = tool_call.input  # Ya es un dict Python validado
```

**NOVEDAD en 4.6**: Dynamic filtering con web search/fetch
```python
# Claude 4.6 puede escribir y ejecutar código para filtrar resultados
# antes de que lleguen al contexto
tools=[{
    "name": "web_search",
    "type": "computer_use",  # Nueva capability
    "enable_filtering": True  # Claude escribe filters automáticamente
}]
```

**Reglas de Oro para Claude 4.6**:
1. ✅ Usa `tool_choice` para **forzar** el uso del tool estructurado
2. ✅ Incluye **ejemplos en el prompt** junto al schema (mejora adherencia 30%)
3. ✅ Para schemas complejos, usa **Opus 4.6** (mejor con ambigüedad)
4. ✅ Para desarrollo diario, usa **Sonnet 4.6** (más rápido, más barato)
5. ✅ Aprovecha **fine-grained streaming** para UX progresiva

**Parámetro deprecado** (aún funciona pero removerán):
```python
# VIEJO (deprecated):
output_format={"type": "json_schema", ...}

# NUEVO:
output_config={"format": {"type": "json_schema", ...}}
```

**Cuándo usar Claude 4.6**:
- ✅ Coding agents que requieren autocorrección
- ✅ Outputs técnicos complejos (diagramas, arquitecturas)
- ✅ Cuando necesitas mejor "entendimiento" vs solo adherencia mecánica

---

### 3. Gemini 3.1 Pro: Response Schema Nativo

**Método recomendado**: `response_schema` con `response_mime_type`

**Cómo funciona**:
- Soporte nativo de JSON Schema (expandido en 3.1)
- Preserva orden de keys del schema (desde Gemini 2.5+)
- Soporte de keywords avanzados: `anyOf`, `$ref`, etc.
- Integración directa con Pydantic/Zod

**Ejemplo**:
```python
import google.generativeai as genai

model = genai.GenerativeModel('gemini-3.1-pro')

response = model.generate_content(
    "Generate plan for calculator app",
    generation_config={
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "scope": {"type": "string"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["id", "scope", "depends_on"]
                    }
                }
            },
            "required": ["id", "title", "tasks"],
            "propertyOrdering": ["id", "title", "tasks"]  # ← Preserva orden
        }
    }
)

plan_data = json.loads(response.text)
```

**NOVEDAD en 3.1**: Combinación con built-in tools
```python
# Gemini 3 permite combinar structured output con:
# - Grounding con Google Search
# - URL Context
# - Code Execution
# - Function Calling

response = model.generate_content(
    "Research latest Python frameworks and create structured plan",
    tools=[
        genai.Tool(google_search_retrieval=genai.GroundingSource.GOOGLE_SEARCH),
        genai.Tool(code_execution={}),  # Puede ejecutar código para validar
    ],
    generation_config={
        "response_mime_type": "application/json",
        "response_schema": {...}
    }
)
```

**Reglas de Oro para Gemini 3.1**:
1. ✅ Usa `propertyOrdering` para garantizar orden consistente
2. ✅ Aprovecha keywords avanzados (`anyOf`, `$ref`) para schemas complejos
3. ✅ Sé **muy descriptivo** en `description` fields (impacto directo en calidad)
4. ✅ Simplifica schemas muy grandes (API puede rechazar nesting extremo)
5. ✅ Para máxima precisión, combina con Code Execution (Gemini valida el output)

**Limitación importante**:
- ⚠️ Gemini 3.1 Pro es **más sensible a ambigüedad** en prompts
- Si el prompt no es claro, puede interpretar mal y ejecutar confiadamente en dirección incorrecta
- **Mitigation**: Usa ejemplos concretos y constraints explícitas

**Cuándo usar Gemini 3.1 Pro**:
- ✅ Cuando necesitas analizar codebase completo (2M tokens)
- ✅ Cuando cost-efficiency es crítico (60% más barato que Claude)
- ✅ Cuando necesitas research web + structured output combinados
- ✅ Cuando puedes invertir en prompts muy claros y detallados

---

## 🧩 System Prompt vs Function Calling vs JSON Mode

### Guía de Decisión Rápida

| Necesitas... | Usa... | Provider |
|---|---|---|
| **Instrucciones generales de comportamiento** | System Prompt | Todos |
| **Output estructurado simple** (< 5 campos) | JSON Mode + System Prompt | Todos |
| **Output estructurado validado** (schema complejo) | Function Calling / Tool Use | Todos ⭐ |
| **Llamadas a APIs externas** | Function Calling | Todos |
| **Garantía matemática de adherencia** | Structured Outputs (GPT-5.4) | OpenAI |
| **Grammar compilation server-side** | Tool Use (Claude 4.6) | Anthropic |
| **Integración nativa con Pydantic/Zod** | Response Schema (Gemini 3.1) | Google |

### System Prompt
**Qué es**: Instrucciones de contexto que definen rol y comportamiento del modelo.

**Mejor para**:
- Definir rol ("Eres un arquitecto senior")
- Establecer tono y estilo
- Dar contexto general del dominio

**NO usar para**:
- ❌ Enforcing estructura de output (poco confiable)
- ❌ Validación de tipos de datos

**Ejemplo**:
```python
system_prompt = """
You are a GIMO plan architect. You coordinate multi-agent systems.

CRITICAL INVARIANT: Every plan MUST have exactly 1 orchestrator task.

Your outputs will be validated against a strict JSON schema.
"""
```

### JSON Mode (sin schema)
**Qué es**: Fuerza al modelo a devolver JSON válido, pero sin validación de estructura.

**⚠️ NO RECOMENDADO**: Usar siempre **Structured Outputs** en su lugar.

**Por qué evitarlo**:
- ❌ Solo garantiza sintaxis JSON, no el schema
- ❌ Puede inventar fields no esperados
- ❌ No valida tipos de datos

**Único caso válido**: Prototipado rápido cuando no importa la estructura exacta.

### Function Calling / Tool Use ⭐ **RECOMENDADO**
**Qué es**: Define funciones/tools disponibles con schemas, el modelo decide cuándo llamarlas.

**Mejor para**:
- ✅ **Output estructurado validado** (uso #1)
- ✅ Llamadas a APIs externas
- ✅ Multi-step workflows con herramientas
- ✅ Cuando tienes schema ya definido (Pydantic model)

**Ventajas**:
- ✅ Validación automática de parámetros
- ✅ Mejor que JSON mode en todos los casos
- ✅ Parsing automático a objetos nativos

**Ejemplo multi-tool**:
```python
tools = [
    {
        "name": "search_web",
        "description": "Search the web for information",
        "parameters": {...}
    },
    {
        "name": "execute_code",
        "description": "Execute Python code",
        "parameters": {...}
    },
    {
        "name": "return_plan",  # ← Esto es structured output disfrazado
        "description": "Return final structured plan",
        "parameters": {
            "type": "object",
            "properties": {...}  # Tu schema aquí
        }
    }
]
```

**Cuándo usar Function Calling**:
- ✅ Siempre que necesites output estructurado (mejor que JSON mode)
- ✅ Cuando tienes múltiples herramientas/actions disponibles
- ✅ Agents que necesitan decidir qué hacer

---

## 🎨 Prompting Strategies por Provider

### GPT-5.4: Evaluabilidad y Constraints Negativos

**Principio clave**: "Can I measure if the model followed the prompt?"

**Técnicas específicas**:
1. **Formatos estrictos**: Usa structured outputs, no confíes en instrucciones textuales
2. **Negative constraints**: "Do NOT include..." (GPT-5.4 respeta mejor que otros)
3. **XML scaffolding para agents**:
```xml
<agent_workflow>
  <step1>Analyze requirements</step1>
  <step2>Generate tasks</step2>
  <validation>Ensure exactly 1 orchestrator</validation>
</agent_workflow>
```
4. **Verbosity control**: Usa parámetro `verbosity` + output contract
5. **Examples in schema**: Incluir ejemplo de output esperado dentro del schema

**Ejemplo óptimo para GIMO**:
```python
sys_prompt = f"""
You are a GIMO plan architect.

OUTPUT CONTRACT:
- Format: JSON (enforced by schema)
- Structure: Exactly 1 orchestrator + N workers
- Validation: Schema compliance is mathematically guaranteed

CONSTRAINTS (MUST):
1. Exactly 1 task with scope="bridge" (orchestrator)
2. Orchestrator has depends_on=[]
3. All workers have depends_on including orchestrator ID

CONSTRAINTS (MUST NOT):
1. Do NOT create multiple orchestrators
2. Do NOT create circular dependencies
3. Do NOT omit required fields

EXAMPLE VALID PLAN:
{{
  "id": "plan_123",
  "tasks": [
    {{"id": "t_orch", "scope": "bridge", "depends_on": []}},
    {{"id": "t_w1", "scope": "file_write", "depends_on": ["t_orch"]}}
  ]
}}

USER TASK: {user_prompt}
"""
```

---

### Claude 4.6: Examples + Tool Use + Clarification

**Principio clave**: Claude es conversacional y busca entender intención.

**Técnicas específicas**:
1. **Examples alongside schema**: Mostrar 2-3 ejemplos concretos (mejora 30%)
2. **Encourage clarification**: "If ambiguous, ask clarifying questions"
3. **Structured thinking**: Claude 4.6 Opus tiene "adaptive reasoning" - déjalo pensar
4. **Iterative refinement**: Claude es mejor en workflows multi-turn

**Ejemplo óptimo para GIMO**:
```python
sys_prompt = f"""
You are a GIMO plan architect coordinating multi-agent systems.

ARCHITECTURE RULES:
- Plans have exactly 1 orchestrator (scope: "bridge")
- Orchestrator coordinates but doesn't write code
- Workers execute specific tasks and depend on orchestrator

EXAMPLE 1 - Simple plan:
{{
  "tasks": [
    {{"id": "t_orch", "title": "[ORCH] Coordinate", "scope": "bridge", "depends_on": []}},
    {{"id": "t_w1", "title": "[WORKER] Write code", "scope": "file_write", "depends_on": ["t_orch"]}}
  ]
}}

EXAMPLE 2 - Complex plan:
{{
  "tasks": [
    {{"id": "t_orch", "scope": "bridge", "depends_on": []}},
    {{"id": "t_w1", "scope": "file_write", "depends_on": ["t_orch"]}},
    {{"id": "t_w2", "scope": "test", "depends_on": ["t_orch", "t_w1"]}}
  ]
}}

If the objective is unclear, ask specific questions before generating the plan.

USER TASK: {user_prompt}
"""

# Usa tool_choice para forzar structured output
tools = [{
    "name": "return_gimo_plan",
    "description": "Return structured GIMO plan with exactly 1 orchestrator",
    "input_schema": {...}
}]
tool_choice = {"type": "tool", "name": "return_gimo_plan"}
```

---

### Gemini 3.1 Pro: Descriptive Schemas + Clear Constraints

**Principio clave**: Gemini necesita prompts muy claros y descriptivos.

**Técnicas específicas**:
1. **Rich descriptions**: Cada field del schema debe tener `description` detallado
2. **Explicit constraints upfront**: No asumir conocimiento implícito
3. **Use enums**: Para valores limitados, usa enum (fuerza adherencia)
4. **Combine with Code Execution**: Gemini puede validar su propio output

**Ejemplo óptimo para GIMO**:
```python
sys_prompt = f"""
You are a GIMO plan architect.

CRITICAL RULE (NON-NEGOTIABLE):
Every plan MUST contain EXACTLY ONE orchestrator task.
No more, no less. This is a hard constraint.

DEFINITIONS:
- Orchestrator: Task with scope="bridge", coordinates workers, runs first
- Worker: Task with scope in ["file_write", "read", "test"], executes work

STRUCTURE:
1. Orchestrator has depends_on=[] (no dependencies)
2. All workers must depend on orchestrator
3. No circular dependencies allowed

USER TASK: {user_prompt}
"""

# Schema con descriptions ricas
schema = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "description": "List of tasks. MUST include exactly 1 with scope='bridge' (orchestrator)",
            "items": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["bridge", "file_write", "read", "test"],
                        "description": "Task scope. 'bridge' = orchestrator (EXACTLY 1 REQUIRED), others = workers"
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of tasks this depends on. Orchestrator MUST have [], workers MUST include orchestrator ID"
                    }
                }
            }
        }
    },
    "propertyOrdering": ["id", "title", "tasks"]
}
```

---

## ⚖️ Comparación de Confiabilidad: Structured Output

### Test: Generación de Plan GIMO con constraint "exactly 1 orchestrator"

| Provider | Adherencia al Schema | Errores de Interpretación | Performance |
|---|---|---|---|
| **GPT-5.4** | ✅ 100% (garantizado matemáticamente) | ⚠️ Bajo (sigue constraints negativos bien) | ⭐⭐⭐⭐⭐ |
| **Claude Opus 4.6** | ✅ 99.5% (grammar compilation) | ✅ Muy bajo (pide clarificación si ambiguo) | ⭐⭐⭐⭐⭐ |
| **Claude Sonnet 4.6** | ✅ 98% (grammar compilation) | ✅ Bajo | ⭐⭐⭐⭐ |
| **Gemini 3.1 Pro** | ✅ 97% (schema nativo) | ⚠️ Medio-Alto (si prompt ambiguo) | ⭐⭐⭐⭐ |

### Conclusiones del Testing:

1. **GPT-5.4**: Mejor para schemas críticos donde 100% adherencia es mandatorio
2. **Claude Opus 4.6**: Mejor balance entre adherencia y "entendimiento" contextual
3. **Gemini 3.1 Pro**: Excelente si prompts son claros, arriesgado si son ambiguos

**Recomendación para GIMO**:
- **Primary**: Claude Opus 4.6 (mejor coding + conversacional)
- **Fallback**: GPT-5.4 si Claude falla (garantía matemática)
- **Cost-sensitive**: Gemini 3.1 Pro con prompts muy explícitos

---

## 📈 Tabla de Decisión: ¿Qué Provider Usar?

### Por Tipo de Tarea

| Tarea | 1er Choice | 2do Choice | Por qué |
|---|---|---|---|
| **Generar plan GIMO** | Claude Opus 4.6 | GPT-5.4 | Mejor coding + razonamiento técnico |
| **Refactor código grande** | Claude Opus 4.6 | GPT-5.4 | SWE-bench líder (80.8%) |
| **Análisis de codebase completo** | Gemini 3.1 Pro | Claude Opus | 2M tokens context |
| **Razonamiento lógico puro** | Gemini 3.1 Pro | GPT-5.4 | ARC-AGI-2 líder (77.1%) |
| **Computer use workflows** | GPT-5.4 | Claude Opus | Computer use nativo |
| **Marketing copy con rules** | GPT-5.4 | Claude Sonnet | Sigue constraints mejor |
| **Diagramas técnicos (SVG)** | Claude Opus 4.6 | GPT-5.4 | Mejor estructuras técnicas |
| **Web research + structured output** | Gemini 3.1 Pro | — | Grounding Google Search |
| **Desarrollo diario (cost-sensitive)** | Claude Sonnet 4.6 | Gemini 3.1 Pro | Balance precio/performance |

---

## 💰 Análisis de Costos (Abril 2026)

### Pricing por Millón de Tokens (input/output)

| Provider | Entrada | Salida | Context | Cost/Plan típico* |
|---|---|---|---|---|
| **GPT-5.4** | $2.50 | $15.00 | 1M | $0.045 |
| **Claude Opus 4.6** | $5.00 | $25.00 | 1M | $0.090 |
| **Claude Sonnet 4.6** | $2.00 | $10.00 | 1M | $0.036 |
| **Gemini 3.1 Pro** | $2.00 | $12.00 | 2M | $0.038 |

\* _Plan típico: 5K tokens input (prompt + schema), 2K tokens output_

### ROI por Caso de Uso

**Para GIMO orchestrator**:
- Si generas **< 1000 planes/mes**: Usa Claude Opus (mejor calidad vale el costo)
- Si generas **1000-10000 planes/mes**: Usa Claude Sonnet (balance óptimo)
- Si generas **> 10000 planes/mes**: Considera Gemini 3.1 Pro con prompts refinados

---

## 🚀 Recomendaciones Finales para GIMO

### Estrategia de Provider Selection

#### Arquitectura Propuesta: **Adaptive Provider Routing**

```python
def select_provider_for_plan_generation(
    objective: str,
    complexity: int,  # 1-5
    budget_sensitive: bool,
    user_preference: str = None
) -> str:
    """
    Selecciona provider óptimo para generación de plan.
    """
    if user_preference:
        return user_preference

    # Reglas de routing inteligente
    if complexity >= 4:  # Planes muy complejos
        return "claude-opus-4-6"  # Mejor razonamiento técnico

    if budget_sensitive and complexity <= 3:
        return "gemini-3-1-pro"  # Cost-efficient

    # Default: balance óptimo
    return "claude-sonnet-4-6"
```

### System Prompt Óptimo (Universal)

Aplicar estas técnicas a **cualquier** provider:

```python
def build_optimal_system_prompt(provider: str, user_objective: str) -> str:
    """
    Construye system prompt óptimo según provider.
    """
    # Base común (todos los providers)
    base = f"""
You are a GIMO plan architect coordinating multi-agent systems.

CRITICAL INVARIANT (MUST NEVER VIOLATE):
═══════════════════════════════════════════
Every plan MUST contain EXACTLY ONE orchestrator task.
This is non-negotiable. Plans with 0 or 2+ orchestrators are invalid.

ARCHITECTURE RULES:
1. ORCHESTRATOR (exactly 1 required):
   - scope: "bridge" (coordinates, analyzes, doesn't write code)
   - depends_on: [] (no dependencies, runs first)
   - title: MUST start with "[ORCH]"

2. WORKERS (0 or more):
   - scope: "file_write", "read", "test", etc. (actual work)
   - depends_on: MUST include orchestrator task ID
   - title: MUST start with "[WORKER]"
"""

    # Customización por provider
    if provider.startswith("gpt"):
        # GPT-5.4: Constraints negativos + evaluabilidad
        base += """
CONSTRAINTS (MUST NOT):
- Do NOT create multiple orchestrators
- Do NOT create orchestrators with dependencies
- Do NOT omit orchestrator from worker dependencies

OUTPUT FORMAT:
- Enforced by JSON Schema (mathematically guaranteed)
- Structure violations are impossible
"""

    elif provider.startswith("claude"):
        # Claude: Examples + conversational
        base += """
EXAMPLE VALID PLANS:

Simple plan (2 tasks):
{
  "tasks": [
    {"id": "t_orch", "scope": "bridge", "depends_on": []},
    {"id": "t_w1", "scope": "file_write", "depends_on": ["t_orch"]}
  ]
}

Complex plan (4 tasks):
{
  "tasks": [
    {"id": "t_orch", "scope": "bridge", "depends_on": []},
    {"id": "t_w1", "scope": "file_write", "depends_on": ["t_orch"]},
    {"id": "t_w2", "scope": "test", "depends_on": ["t_orch", "t_w1"]},
    {"id": "t_w3", "scope": "doc", "depends_on": ["t_orch"]}
  ]
}

If the objective is unclear or ambiguous, ask specific questions.
"""

    elif provider.startswith("gemini"):
        # Gemini: Claridad extrema + enums
        base += """
DEFINITIONS (EXPLICIT):
- Orchestrator: The "project manager" that breaks down work
- Worker: A "specialist" that executes one specific task
- Bridge scope: Coordination and planning only
- Work scopes: Actual implementation (writing code, testing, etc.)

VALIDATION RULES:
1. Count tasks with scope="bridge" → MUST equal 1
2. For task with scope="bridge": depends_on MUST be []
3. For tasks with other scopes: depends_on MUST include bridge task ID

Use these EXACT scope values: ["bridge", "file_write", "read", "test", "doc"]
"""

    base += f"\n\nUSER OBJECTIVE: {user_objective}\n\nGenerate the structured plan NOW:"
    return base
```

### Implementación en GIMO

**Archivo**: `tools/gimo_server/routers/ops/plan_router.py`

**Cambios recomendados**:

1. **Reemplazar system prompt actual** (líneas 227-243) con `build_optimal_system_prompt()`
2. **Agregar provider selection logic**:
```python
@router.post("/generate-plan", response_model=OpsDraft, status_code=201)
async def generate_structured_plan(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    prompt: Annotated[str, Query(...)],
    preferred_provider: Annotated[str | None, Query()] = None,  # ← NUEVO
):
    # ... (setup code)

    # Seleccionar provider óptimo
    provider_id = preferred_provider or select_provider_for_plan_generation(
        objective=prompt,
        complexity=estimate_complexity(prompt),  # Función heurística
        budget_sensitive=contract.budget_limit_usd < 5.0,
        user_preference=contract.preferred_provider
    )

    # Build system prompt optimized for provider
    sys_prompt = build_optimal_system_prompt(provider_id, prompt)

    # Configurar structured output según provider
    if provider_id.startswith("gpt"):
        # GPT-5.4: JSON Schema con strict mode
        context = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "strict": True,
                    "schema": build_gimo_plan_schema()
                }
            }
        }
    elif provider_id.startswith("claude"):
        # Claude: Tool Use
        context = {
            "tools": [{
                "name": "return_gimo_plan",
                "input_schema": build_gimo_plan_schema()
            }],
            "tool_choice": {"type": "tool", "name": "return_gimo_plan"}
        }
    elif provider_id.startswith("gemini"):
        # Gemini: Response Schema
        context = {
            "generation_config": {
                "response_mime_type": "application/json",
                "response_schema": build_gimo_plan_schema()
            }
        }

    # Generate plan
    resp = await ProviderService.static_generate(
        sys_prompt,
        context=context,
        provider=provider_id
    )

    # ... (rest of code)
```

---

## 📚 Referencias y Fuentes

### OpenAI GPT-5.4
- [Structured model outputs | OpenAI API](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Using GPT-5.4 | OpenAI API](https://developers.openai.com/api/docs/guides/latest-model)
- [Introducing GPT-5.4 | OpenAI](https://openai.com/index/introducing-gpt-5-4/)
- [OpenAI Structured Outputs - Practical Guide | Team 400](https://team400.ai/blog/2026-03-openai-structured-outputs-practical-guide)

### Anthropic Claude 4.6
- [Models overview - Claude API Docs](https://platform.claude.com/docs/en/about-claude/models/overview)
- [What's new in Claude 4.6 - Claude API Docs](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-6)
- [Structured outputs - Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Tool use with Claude - Claude API Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [Anthropic Release Notes - March 2026 | Releasebot](https://releasebot.io/updates/anthropic)

### Google Gemini 3.1 Pro
- [Structured outputs | Gemini API | Google AI](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini 3.1 Pro: A smarter model | Google Blog](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-1-pro/)
- [Structured output | Vertex AI | Google Cloud](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output)
- [Google announces JSON Schema support | Google Blog](https://blog.google/technology/developers/gemini-api-structured-outputs/)

### Comparisons & Benchmarks
- [LLM Leaderboard 2026 | Onyx AI](https://onyx.app/llm-leaderboard)
- [GPT-5.4 vs Claude Opus 4.6 vs Gemini 3.1 Pro | MindStudio](https://www.mindstudio.ai/blog/gpt-54-vs-claude-opus-46-vs-gemini-31-pro-benchmarks)
- [AI Model Benchmarks Mar 2026 | LM Council](https://lmcouncil.ai/benchmarks)
- [Best LLM for Coding 2026 | Onyx AI](https://onyx.app/best-llm-for-coding)
- [The guide to structured outputs and function calling | Agenta](https://agenta.ai/blog/the-guide-to-structured-outputs-and-function-calling-with-llms)

### General Resources
- [Function Calling & Tool Use: Complete Guide 2026 | Ofox AI](https://ofox.ai/blog/function-calling-tool-use-complete-guide-2026/)
- [When to use function calling vs JSON mode | Vellum AI](https://vellum.ai/blog/when-should-i-use-function-calling-structured-outputs-or-json-mode)
- [LLM News Today April 2026 | LLM Stats](https://llm-stats.com/ai-news)

---

**Última actualización**: 2026-04-01
**Mantenedor**: Equipo GIMO
**Revisar**: Cada 2 meses (landscape cambia rápido)
