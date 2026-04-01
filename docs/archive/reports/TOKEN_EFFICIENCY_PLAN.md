# Plan de Eficiencia de Tokens — GIMO

## Objetivo
Reducir consumo de tokens 60-70% en tareas maduras. "Con otros servicios dura 45min, con GIMO dura 2h."

---

## P0 — Exponer GICS Insight Engine (Foundation)

**Archivo**: `tools/gimo_server/services/gics_service.py`
**Qué**: Agregar métodos Python que llamen al Insight Engine via JSON-RPC:
- `track_item(key, fields)` → InsightTracker
- `get_insight(key)` → behavioral data (velocity, entropy, lifecycle, trends)
- `get_recommendations(key)` → PredictiveSignals recommendations
- `record_prediction_outcome(key, predicted, actual)` → ConfidenceTracker
- `get_clusters()` → CorrelationAnalyzer clusters

**Daemon side** (`src/daemon/server.ts`): Exponer handlers JSON-RPC para estos métodos.

**Namespaces de keys**:
```
ops:model:{provider}:{id}    — (ya existe)
ops:task:{type}:{model_hash}  — patrones de tarea
ops:prompt:{hash}             — patrones de prompt
ops:session:{id}              — eficiencia por sesión
```

---

## P1 — Quick Wins (bajo esfuerzo, alto impacto)

### 1.1 Critic Gate Adaptativo (~30% ahorro)
**Archivos**: `run_worker.py`, `critic_service.py`
- `quality_service.score(output)` (determinístico, 0 tokens) SIEMPRE corre primero
- Si quality > 80 Y GICS insight para `ops:task:{type}:{model}` tiene score > 0.9 con samples > 15 → skip critic LLM
- Si no → critic LLM normal
- Registrar outcome en GICS: `record_model_outcome()` con campo `critic_needed: bool`

### 1.2 max_tokens Predictivo (~15-25% ahorro)
**Archivo**: `providers/openai_compat.py`
- Antes de llamar al LLM: `forecast = gics.get_insight(f"ops:task:{task_type}")`
- Si hay datos: `max_tokens = int(avg_output_tokens * 1.3)` en vez de default 4096
- Si no hay datos: default normal
- Post-llamada: trackear tokens reales en GICS

### 1.3 Structured Output Gateway (~5-10% ahorro)
**Archivo**: `providers/openai_compat.py`
- Dict estático de providers que soportan `response_format`:
  ```python
  _JSON_MODE_PROVIDERS = {"openai", "anthropic", "groq", "together", "mistral", "deepseek"}
  ```
- Si provider soporta y el prompt pide JSON → agregar `response_format`, strip instrucciones JSON del prompt
- Sin GICS, puro config.

### 1.4 Semantic Caching (~100% ahorro en tareas repetitivas)
**Archivo**: `services/cache_service.py`
- Antes de procesar un prompt, generar embedding de la petición y buscar en DB vectorial.
- Si la similitud semántica es > 95% con un prompt histórico, retornar el resultado en caché.
- Ahorro total del costo de tokens (0 llamadas al LLM).

### 1.5 Tareas Asíncronas en Batch (~50% ahorro en background)
**Archivo**: `services/background_tasks.py`
- Identificar procesos de evaluación, resúmenes o critic en background que no requieren respuesta inmediata al usuario web.
- Enviar estas tareas usando la API Batch (ej. OpenAI / Anthropic) para un 50% de descuento automático en costos y mayores límites de rate.

---

## P2 — Arquitectura (esfuerzo medio)

### 2.1 Separación System/User Prompt
**Archivo**: `providers/openai_compat.py`
- System prompt aparte del user prompt (ya lo hace parcialmente con `sys_hint`)
- Hacer que system prompts sean reutilizables/cacheables por provider:
  - Anthropic: `cache_control: {"type": "ephemeral"}` en system message
  - OpenAI: automático si system message es idéntico entre calls
- Reducir system prompts inflados (critic usa ~200 tokens de system prompt fijo)

### 2.2 Cascade Skip via GICS Clusters (~20% en tareas cascadeadas)
**Archivo**: `cascade_service.py`
- Antes de cascade: consultar GICS `get_clusters()` y `get_insight()` del task type
- Si GICS sabe que este tipo de tarea necesita tier X → empezar ahí
- Si no hay data → cascade normal (cheap→medium→expensive)

### 2.3 Context Indexer Lean
**Archivo**: `context_indexer.py`
- `extract_file_contents()` lee archivos enteros → truncar a primeras 100 líneas + funciones referenciadas
- Heurística pura, sin GICS. AST-based si es Python/JS/TS, line-count-based si no.

### 2.4 Routing Dinámico de Modelos (Tiering Inteligente)
**Archivo**: `providers/router.py`
- Ampliar los clusters de GICS para seleccionar el modelo adecuado según entropía y tipo de tarea.
- Si el score predictivo indica complejidad baja/rutinaria, derivar la consulta a modelos rápidos y eficientes (ej. Claude 3.5 Haiku, GPT-4o-mini).
- Reservar los modelos pesados (ej. Claude 3.5 Sonnet / GPT-4o) exclusivamente para tareas complejas.

### 2.5 Active Prompt Compression (Semantic Pruning)
**Archivos**: `context_indexer.py`, `prompt_builder.py`
- Agregar etapa de compresión con modelo rápido o algoritmo local (como LLMLingua) previo al request principal.
- Condensar contexto irrelevante o verboso antes de enviarlo al modelo pesado, manteniendo el significado semántico en menos tokens.

---

## P3 — Aprendizaje Profundo (esfuerzo alto, impacto largo plazo)

### 3.1 Prompt Waste Detection
- GICS trackea cada prompt con su output y score
- Behavioral analysis detecta qué partes del prompt no correlacionan con mejores outputs
- PredictiveSignals genera recommendations tipo "demote" para prompt sections ineficientes
- Requiere: fragmentar prompts en sections trackables

### 3.2 GIOS ↔ GICS Loop
- GIOS alimenta intents detectados a GICS
- GICS aprende qué intents se resuelven bien sin LLM
- Cuando confidence > 0.95 por 50+ samples → GIOS auto-expande bypass coverage
- Meta: pasar de 5% bypass a 40%+

---

## P4 — UX

### Token Efficiency Score (visible en UI)
- Panel en dashboard mostrando: tokens usados vs baseline, % ahorrado, trend
- Datos vienen de GICS session tracking
- "GICS ahorró 47% tokens esta sesión (1,240 tokens)"

---

## Resumen de Motores

| Mejora | Motor | GICS? |
|---|---|---|
| Structured output | Config dict | No |
| Semantic Caching | DB Vectorial | Sí (para fallback) |
| Asynchronous Batch | Batch API / Queue | No |
| System/User separation | Código (Prompt Caching) | No |
| Context indexer lean | Heurísticas | No |
| Active Prompt Compression | Modelo rápido / alg | No |
| GIOS intent (actual) | TF-IDF estático | No |
| Critic gate | quality_service + GICS | **Sí** (umbral adaptativo) |
| max_tokens | GICS forecast | **Sí** |
| Cascade skip | GICS clusters | **Sí** |
| Dynamic Routing (Tiering) | Router predictivo | **Sí** |
| Prompt waste | Heurísticas + GICS | **Sí** (detección adaptativa) |
| Efficiency Score | Lee métricas GICS | Solo lectura |

## Orden de Implementación

```
P0 (GICS wiring)  →  P1.3 (structured output, no deps)
                   →  P1.4 (semantic caching, requiere DB vec)
                   →  P1.1 (critic gate, necesita P0)
                   →  P1.5 (batch processing para critic)
                   →  P1.2 (max_tokens, necesita P0)
                   →  P2.1 (system/user & prompt caching, sin deps)
                   →  P2.3 (context lean, sin deps)
                   →  P2.5 (active compression)
                   →  P2.4 (dynamic routing, necesita P0)
                   →  P2.2 (cascade, necesita P0)
                   →  P4 (score UI)
                   →  P3 (largo plazo)
```
