# Context Budget System — Adaptive Token Management

**Fecha**: 2026-04-10
**Autor**: Claude Opus 4.6 + shilo
**Estado**: Implementado en `agentic_loop_service.py`

## Problema

Los providers LLM tienen límites de tokens por request muy distintos:

| Provider | Modelo | Límite real |
|----------|--------|-------------|
| Groq (free tier) | qwen/qwen3-32b | 6,000 tokens/request |
| Cloudflare Workers AI | @cf/qwen/qwen2.5-coder-32b | ~4,096 tokens/request |
| Ollama local | qwen2.5-coder:3b | 4,096 tokens (context window) |
| Ollama local | llama3.2:3b | 8,192 tokens |
| OpenAI | gpt-4o | 128,000 tokens |
| Anthropic | claude-opus-4 | 1,000,000 tokens |

El agentic loop de GIMO envía system prompt (~800 tokens) + tool schemas (~1700 tokens) + historial de mensajes + tool results.  Para modelos grandes esto no es problema, pero para providers con límites bajos el payload excede el límite y el provider rechaza con 413 o devuelve respuestas vacías.

## Decisión de diseño

**El propio agentic loop se adapta** al límite de cada provider.  No se crean abstracciones nuevas ni capas por encima.  El loop detecta, aprende y se ajusta.

Principio clave: **los agentes se auto-descubren**.  En vez de hardcodear límites, los agentes reportan su capacidad real y el loop la usa en futuras ejecuciones.

## Arquitectura

```
┌─────────────────────────────────────────────────────┐
│                  _run_loop()                         │
│                                                     │
│  1. _get_context_budget(model, provider_id)         │
│     ├── Lee model_context_registry.json (agentes)   │
│     ├── Lee model_pricing.json (context_window)     │
│     ├── Heurística por tamaño (1b/3b/7b)           │
│     └── Default: 128K                               │
│                                                     │
│  2. is_constrained = budget <= 8192                  │
│     Si True:                                        │
│     ├── _compact_tools_if_needed() con budget bajo  │
│     ├── _trim_messages_to_budget() antes de cada    │
│     │   llamada LLM                                 │
│     └── Tool results limitados a 1200 chars         │
│                                                     │
│  3. Cada respuesta exitosa:                         │
│     └── Lee x-ratelimit-limit-tokens del header     │
│         y registra si < budget actual                │
│                                                     │
│  4. En error 413:                                   │
│     ├── Estima límite real (80% del payload enviado)│
│     ├── register_model_context_limit() automático   │
│     ├── Reintenta con budget/2                      │
│     └── Si falla → finish_reason=context_too_small  │
│         + context_budget_hint con guía para agentes │
└─────────────────────────────────────────────────────┘
```

## Flujo de auto-descubrimiento

### Path 1: Header de rate limit (automático, sin error)
```
LLM responde OK → headers incluyen x-ratelimit-limit-tokens: 6000
→ loop detecta 6000 < budget actual (128000)
→ register_model_context_limit("groq", "qwen/qwen3-32b", 6000)
→ model_context_registry.json actualizado
→ budget ajustado para el resto de la sesión
→ futuras sesiones leen el registry al arrancar
```

### Path 2: Error 413 (auto-recuperación)
```
LLM rechaza con 413 Payload Too Large
→ loop estima límite real = 80% del payload enviado
→ register_model_context_limit() automático
→ reintenta con budget/2
→ si funciona: continúa la sesión
→ si falla: finish_reason="context_too_small" + hint
```

### Path 3: Agente externo (registro manual)
```
Agente lee la documentación del provider
→ Descubre que el modelo tiene 6000 tokens/request
→ Llama PUT /ops/models/context-limits
   o gimo_register_model_context_limit via MCP
→ model_context_registry.json actualizado
→ Próxima ejecución del loop usa el límite correcto
```

## Model Context Registry

Archivo: `.orch_data/ops/model_context_registry.json`

Formato:
```json
{
  "groq:qwen/qwen3-32b": 6000,
  "cloudflare-workers-ai:@cf/qwen/qwen2.5-coder-32b-instruct": 4096,
  "ollama-local:qwen2.5-coder:3b": 4096,
  "ollama-local:llama3.2:3b": 8192
}
```

Claves: `provider_id:model` → tokens (int).

El loop lee este archivo con cache por mtime (no hay I/O en cada iteración si no cambió).

### Interfaces para registrar límites

| Interfaz | Endpoint / Método |
|----------|-------------------|
| **REST** | `PUT /ops/models/context-limits` con body `{"provider_id", "model", "max_tokens"}` |
| **REST** | `GET /ops/models/context-limits` — lee el registry completo |
| **MCP** | `gimo_register_model_context_limit(provider_id, model, max_tokens)` |
| **MCP** | `gimo_get_model_context_limits()` — lee el registry |
| **Python** | `AgenticLoopService.register_model_context_limit(provider_id, model, max_tokens)` |
| **Auto** | El loop lo hace solo via headers o 413 recovery |

## Estrategias de adaptación (constrained mode)

Cuando `context_budget <= 8192` tokens:

### 1. Tool schema compaction (`_compact_tools_if_needed`)
- **Pase 1**: Trunca descripciones largas a 60 chars
- **Pase 2**: Si sigue excediendo, mantiene solo 6 tools esenciales: `read_file`, `write_file`, `list_files`, `search_replace`, `search_text`, `shell_exec`

### 2. Message trimming (`_trim_messages_to_budget`)
Ejecutado **antes de cada llamada LLM**:
- **Pase 1**: Comprime tool results >500 chars (head 200 + tail 100)
- **Pase 2**: Comprime texto de assistant >300 chars
- **Pase 3**: Sliding window — descarta turns antiguos, mantiene system prompt + turns recientes que quepan

### 3. Tool result cap
- Constrained: 1,200 chars máximo por tool result
- Normal: 8,000 chars (default original)

### 4. Retry con 413
- Primer intento falla → budget se reduce al 50%
- Segundo intento falla → `finish_reason = "context_too_small"` + hint diagnóstico

## Modelos grandes no se ven afectados

La condición `is_constrained = budget <= 8192` garantiza que modelos con ventanas grandes (Claude, GPT-4o, Gemini) nunca activan el constrained mode:

- No hay trim de mensajes
- Tool results mantienen 8,000 chars
- Tool schemas no se compactan (budget de 8,000 chars)
- El retry 413 existe como safety net pero no debería activarse

## Flag de diagnóstico: `context_too_small`

Cuando el loop falla por contexto insuficiente, `AgenticResult` incluye:

```python
result.finish_reason == "context_too_small"
result.usage["context_budget_hint"] == {
    "flag": "context_too_small",
    "provider_id": "groq",
    "model": "qwen/qwen3-32b",
    "context_budget_tokens": 6000,
    "messages_tokens_estimated": 7200,
    "tools_schema_tokens_estimated": 1700,
    "failed_at_iteration": 2,
    "diagnosis": "...",
    "action_required": {
        "step_1_investigate": "Instrucciones para investigar el límite real",
        "step_2_register": "Instrucciones para escribir en el registry",
        "step_3_retry": "Instrucciones para reintentar"
    },
    "how_the_loop_adapts": "Descripción del constrained mode",
    "registry_path": ".orch_data/ops/model_context_registry.json"
}
```

Este hint es auto-contenido: un agente que no conoce el código interno de GIMO puede leerlo, seguir los pasos, y resolver el problema sin asistencia humana.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `services/agentic_loop_service.py` | Context budget detection, trimming, compaction, registry, auto-discovery, hint |
| `providers/openai_compat.py` | Captura `x-ratelimit-limit-tokens` de headers HTTP |
| `routers/ops/config_router.py` | `GET/PUT /ops/models/context-limits` |
| `mcp_bridge/native_tools.py` | `gimo_register_model_context_limit`, `gimo_get_model_context_limits` |
| `data/model_pricing.json` | Añadidos qwen3-32b, qwen2.5-coder-3b, llama3.2-3b |

## Motivación (contexto del usuario)

> "quiero que el propio agent loop permita estas excepciones. no vamos a crear piezas por encima de otras, mejoramos la que tenemos y ya."

> "asi lo podemos diseñar tambien para otros providers, por ejemplo ollama."

> "enseñale que investigue si el modelo usado tiene poca capacidad de tokens, y de ser asi, que escriba en cierto espacio la capacidad de token que tiene su modelo para que agentic loop lo tenga en cuenta"

> "deja tambien el path de que el propio orquestador cree el limite de tokens"
