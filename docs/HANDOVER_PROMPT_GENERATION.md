# HANDOVER: System Prompts Generation
**Fecha**: 2026-02-01
**De**: Orchestrator Agent
**Para**: Prompt Generation Agent
**Proyecto**: LLM Integration Security Framework
**Prioridad**: CRÍTICA

---

## MISIÓN

Generar 4 system prompts militares para agentes especializados que implementarán el framework de seguridad LLM en 4 fases paralelas.

---

## CONTEXTO DEL PROYECTO

**Sistema**: Gred-Repo-Orchestrator
**Framework**: LLM Integration Security (7 capas de defensa)
**Nivel de seguridad**: Aerospace/Government Grade
**Principio**: Defense in Depth con Fail-Safe

**Documento de referencia**: `docs/LLM_INTEGRATION_SECURITY.md`
**Plan de implementación**: `docs/LLM_IMPLEMENTATION_PLAN.md`

---

## ESTRUCTURA DE 4 FASES

### WAVE 1: PARALLEL (2 agentes simultáneos)

**FASE-1: CRITICAL SECURITY**
- Agente: `agent-critical-security`
- Layers: 1 (Input Sanitization) + 5 (Output Validation)
- Archivos:
  - `tools/llm_security/layers/input_sanitization.py`
  - `tools/llm_security/layers/output_validation.py`
  - `tools/llm_security/layers/__init__.py`

**FASE-2: LLM PIPELINE**
- Agente: `agent-llm-pipeline`
- Layers: 2 (Scope Limiter) + 3 (Prompt Hardening) + 4 (Deterministic Client)
- Archivos:
  - `tools/llm_security/layers/scope_limiter.py`
  - `tools/llm_security/prompts/hardened_prompts.py`
  - `tools/llm_security/prompts/__init__.py`
  - `tools/llm_security/client/deterministic_llm.py`
  - `tools/llm_security/client/__init__.py`

### WAVE 2: SEQUENTIAL (1 agente)

**FASE-3: OBSERVABILITY & INTEGRATION**
- Agente: `agent-observability`
- Layers: 6 (Anomaly Detection) + 7 (Audit Logger) + 8 (Integration)
- Archivos:
  - `tools/llm_security/layers/anomaly_detection.py`
  - `tools/llm_security/audit/audit_logger.py`
  - `tools/llm_security/audit/metrics.py`
  - `tools/llm_security/audit/__init__.py`
  - `tools/llm_security/client/secure_client.py`
  - `tools/llm_security/cache/response_cache.py`
  - `tools/llm_security/cache/__init__.py`

### WAVE 3: FINAL (1 agente)

**FASE-4: DEPLOYMENT & VALIDATION**
- Agente: `agent-deployment`
- Componentes: Testing + CI/CD + Panic Integration + Docs
- Archivos:
  - `tests/llm_security/test_input_sanitization.py`
  - `tests/llm_security/test_scope_limiter.py`
  - `tests/llm_security/test_output_validation.py`
  - `tests/llm_security/test_anomaly_detection.py`
  - `tests/llm_security/test_secure_client.py`
  - `tests/llm_security/test_integration.py`
  - `tests/llm_security/__init__.py`
  - `.github/workflows/secure-ai-review.yml`
  - `scripts/secure_ai_review.py`
  - `tools/llm_security/integrations/panic_mode.py`
  - `tools/llm_security/integrations/__init__.py`
  - `docs/LLM_SECURITY_ARCHITECTURE.md`
  - `docs/LLM_USAGE_GUIDE.md`

---

## PLANTILLA OBLIGATORIA (Formato Militar)

Cada prompt DEBE seguir esta estructura:

```
═══════════════════════════════════════════════════════════════
AGENTE: [NOMBRE_CODIGO_AGENTE]
FASE: [NÚMERO Y NOMBRE]
CLASIFICACIÓN: CRÍTICA | ALTA | MEDIA
═══════════════════════════════════════════════════════════════

## TAREA
[Descripción concisa de la tarea en 1-2 líneas]

## META
[Objetivo final medible en 1 línea]

## CONTEXTO OPERACIONAL
[Información necesaria para entender el problema]
- Documento de referencia: docs/LLM_INTEGRATION_SECURITY.md
- Arquitectura: [descripción breve de qué capa(s) implementa]
- Dependencias: [otras fases o ninguna]

## INSTRUCCIONES DE EJECUCIÓN

### PASO 1: [Nombre del paso]
[Instrucciones detalladas]

### PASO 2: [Nombre del paso]
[Instrucciones detalladas]

### PASO N: [Nombre del paso]
[Instrucciones detalladas]

## ENTREGABLES

### ARCHIVOS A CREAR:
1. `[ruta/archivo1.py]`
   - Contiene: [clases/funciones principales]
   - Criterios: [criterios específicos]

2. `[ruta/archivo2.py]`
   - Contiene: [clases/funciones principales]
   - Criterios: [criterios específicos]

### CRITERIOS DE ACEPTACIÓN:
- ✅ [Criterio medible 1]
- ✅ [Criterio medible 2]
- ✅ [Criterio medible N]

## ESPECIFICACIONES TÉCNICAS

### IMPORTS REQUERIDOS:
```python
[imports necesarios]
```

### CLASES/FUNCIONES PRINCIPALES:
- `ClassName1`: [propósito]
- `ClassName2`: [propósito]
- `function_name()`: [propósito]

### INTERFAZ DE SALIDA:
```python
# Firma de métodos principales que otros componentes usarán
[código de ejemplo]
```

## CÓDIGO DE REFERENCIA
[Extracto relevante de docs/LLM_INTEGRATION_SECURITY.md para esta fase]

## VALIDACIÓN

### TESTS MÍNIMOS:
1. [Test unitario 1]
2. [Test unitario 2]
3. [Test de integración]

### COMANDOS DE VERIFICACIÓN:
```bash
# Ejecutar para validar implementación
[comandos]
```

## NOTAS FINALES
- **Estándar de código**: Seguir estándares del repositorio (Black, MyPy, Ruff)
- **Documentación**: Docstrings en formato Google
- **Seguridad**: NUNCA comprometer fail-safe defaults
- **Performance**: [consideraciones de performance específicas]
- **Punto de sincronización**: [cuándo reportar completitud]

## CANALES DE COMUNICACIÓN
- **Status updates**: `logs/llm_implementation_status.json`
- **Errores críticos**: Log en stderr + archivo `logs/phase_[N]_errors.log`
- **Completitud**: Actualizar status a "COMPLETE" cuando todos los criterios se cumplan

═══════════════════════════════════════════════════════════════
FIN DE INSTRUCCIONES - AGENTE [NOMBRE]
═══════════════════════════════════════════════════════════════
```

---

## ESPECIFICACIONES POR FASE

### FASE-1: CRITICAL SECURITY

**Componentes a implementar**:

1. **SecretsFilter** (en input_sanitization.py)
   - PATTERNS: dict con 8+ tipos de secretos
   - `sanitize(content: str) -> Tuple[str, List[str]]`
   - `validate_clean(content: str) -> bool`

2. **PIIFilter** (en input_sanitization.py)
   - PATTERNS: dict con 5+ tipos de PII
   - `sanitize(content: str) -> str`

3. **PromptInjectionDetector** (en input_sanitization.py)
   - SUSPICIOUS_PATTERNS: lista con 10+ patrones
   - `detect(content: str) -> Tuple[bool, List[str]]`
   - `neutralize(content: str) -> str`

4. **InputSanitizer** (en input_sanitization.py)
   - `sanitize_full(content: str, abort_on_injection: bool) -> Dict`
   - Debe retornar: {'sanitized_content', 'is_safe', 'detected_secrets', 'detected_injections', 'action', 'reason'}

5. **OutputValidator** (en output_validation.py)
   - FORBIDDEN_PATTERNS: dict con categorías (secrets, injection_evidence, pii)
   - EXPECTED_STRUCTURE: lista de markers esperados
   - `validate(output: str) -> Dict`
   - `sanitize_if_needed(output: str) -> str`

**Criterios de aceptación**:
- Detecta y redacta API keys (OpenAI, AWS, etc.)
- Detecta emails, SSN, credit cards, IPs
- Detecta "ignore previous instructions" y variantes
- Retorna action='DENY' si encuentra violaciones
- Validación doble: input Y output

---

### FASE-2: LLM PIPELINE

**Componentes a implementar**:

1. **ScopeLimiter** (en scope_limiter.py)
   - Constantes: MAX_FILES=10, MAX_TOTAL_TOKENS=8000, MAX_LINES_PER_FILE=500
   - ALLOWED_EXTENSIONS: set con extensiones permitidas
   - DENIED_PATHS: set con paths denegados
   - `filter_files(file_paths: List[Path]) -> Tuple[List[Path], List[str]]`
   - `truncate_content(content: str, max_tokens: int) -> str`

2. **HARDENED_SYSTEM_PROMPT** (en hardened_prompts.py)
   - String multilínea con 6 secciones de reglas
   - Incluye: SECRETS, INJECTION PROTECTION, SCOPE LIMITATION, OUTPUT CONSTRAINTS, BEHAVIORAL RULES, AUDIT TRAIL

3. **build_user_prompt()** (en hardened_prompts.py)
   - `build_user_prompt(sanitized_code: str, analysis_type: str) -> str`

4. **DeterministicLLM** (en deterministic_llm.py)
   - `__init__(api_key: str)`
   - `call_with_max_determinism(system_prompt: str, user_prompt: str, max_tokens: int) -> Dict`
   - Configuración: temperature=0, seed determinístico (SHA256 de input)
   - Retorna: {'response', 'usage', 'fingerprint', 'seed', 'model'}

**Criterios de aceptación**:
- Bloquea archivos .env, secrets.yaml, .ssh/
- Limita a 10 archivos máximo
- Trunca contenido a 8000 tokens
- LLM siempre con temperature=0
- Seed determinístico basado en input

---

### FASE-3: OBSERVABILITY & INTEGRATION

**Componentes a implementar**:

1. **AnomalyDetector** (en anomaly_detection.py)
   - `__init__()` con history=[]
   - `add_interaction(interaction: Dict)`
   - `detect_anomalies(current: Dict) -> List[str]`
   - `get_stats() -> Dict`
   - Detección por z-score (>3σ), fingerprint changes, violation spikes

2. **LLMAuditLogger** (en audit_logger.py)
   - `__init__(log_file: Path)`
   - `log_interaction(interaction_id, phase, data, action, reason)`
   - `log_alert(severity, message, details)`
   - Logs en JSON estructurado, append-only

3. **LLMMetrics** (en metrics.py)
   - METRICS: dict con contadores
   - `calculate_cost(usage: dict, model: str) -> float`
   - Precios actualizados de GPT-4

4. **SecureLLMClient** (en secure_client.py)
   - `__init__(api_key, audit_log_path, abort_on_injection, abort_on_anomaly)`
   - `analyze_code(code_files: List[Path], analysis_type: str) -> Dict`
   - Orquesta las 7 capas en orden
   - `_abort_response()` helper
   - Retorna: {'success', 'result', 'interaction_id', 'layers_passed', 'layers_failed', 'audit_trail', 'metadata'}

5. **LLMResponseCache** (en response_cache.py)
   - `__init__(cache_dir: Path)`
   - `get_cache_key(code: str, analysis_type: str) -> str`
   - `get(code, analysis_type) -> Optional[dict]`
   - `set(code, analysis_type, result: dict)`
   - Cache basado en SHA256

**Criterios de aceptación**:
- Pipeline completo ejecuta 7 capas en orden
- Cualquier fallo de capa → ABORT
- Audit trail completo en JSON
- Caché solo para éxitos
- Anomaly detection con historial de 100 interacciones

---

### FASE-4: DEPLOYMENT & VALIDATION

**Componentes a implementar**:

1. **Tests unitarios** (6 archivos test_*.py)
   - `test_layer1_secrets_removal()`
   - `test_layer1_injection_detection()`
   - `test_layer2_scope_limiter()`
   - `test_layer5_output_validation()`
   - `test_layer6_anomaly_detection()`
   - `test_secure_client_integration()`
   - Cobertura >90%

2. **GitHub Actions** (.github/workflows/secure-ai-review.yml)
   - Trigger: pull_request (opened, synchronize)
   - Steps: checkout, setup python, install deps, run script
   - Upload audit logs como artifacts
   - Comment en PR con resultados

3. **CLI Script** (scripts/secure_ai_review.py)
   - Args: --files, --analysis-type, --audit-log, --abort-on-injection, --abort-on-anomaly
   - Usa SecureLLMClient
   - Output a ai_review_result.md

4. **Panic Integration** (integrations/panic_mode.py)
   - `integrate_with_panic_mode(llm_result: dict)`
   - Trigger panic en violaciones LAYER_1 y LAYER_5
   - Actualiza security_db con eventos

5. **Documentación** (3 archivos .md)
   - LLM_SECURITY_ARCHITECTURE.md: Diagramas + arquitectura
   - LLM_USAGE_GUIDE.md: Ejemplos de uso
   - (Compliance checklist puede ir en ARCHITECTURE.md)

**Criterios de aceptación**:
- Tests pasan con >90% cobertura
- CI/CD ejecuta en PRs automáticamente
- Panic mode se activa en violaciones críticas
- Documentación completa y clara

---

## CÓDIGO DE REFERENCIA

El agente DEBE extraer el código relevante de `docs/LLM_INTEGRATION_SECURITY.md` para cada fase:

- **FASE-1**: Secciones 3 (Layer 1) y 7 (Layer 5) del documento
- **FASE-2**: Secciones 4 (Layer 2), 5 (Layer 3), 6 (Layer 4)
- **FASE-3**: Secciones 8 (Layer 6), 9 (Layer 7), 10 (Integrated Client), 16 (Caching)
- **FASE-4**: Secciones 12 (GitHub Actions), 14 (Panic Mode), 15 (Testing)

---

## INSTRUCCIONES PARA EL AGENTE GENERADOR DE PROMPTS

1. **LEER**: `docs/LLM_INTEGRATION_SECURITY.md` completo
2. **LEER**: `docs/LLM_IMPLEMENTATION_PLAN.md` completo
3. **GENERAR**: 4 prompts siguiendo la PLANTILLA OBLIGATORIA
4. **GUARDAR**: En archivo `docs/SYSTEM_PROMPTS_LLM_PHASES.md`
5. **FORMATO**: Markdown con separadores claros entre prompts
6. **VALIDAR**: Cada prompt tiene todas las secciones de la plantilla
7. **EXTRAER**: Código de referencia exacto del documento LLM_INTEGRATION_SECURITY.md

### Estructura del archivo de salida:

```markdown
# System Prompts - LLM Integration Security
**Generado**: 2026-02-01
**Fases**: 4
**Proyecto**: Gred-Repo-Orchestrator

---

## PROMPT FASE-1: CRITICAL SECURITY
[Prompt completo con plantilla]

---

## PROMPT FASE-2: LLM PIPELINE
[Prompt completo con plantilla]

---

## PROMPT FASE-3: OBSERVABILITY & INTEGRATION
[Prompt completo con plantilla]

---

## PROMPT FASE-4: DEPLOYMENT & VALIDATION
[Prompt completo con plantilla]
```

---

## CRITERIOS DE ACEPTACIÓN DEL HANDOVER

El agente que reciba este handover debe poder:
- ✅ Generar los 4 prompts SIN preguntar nada adicional
- ✅ Incluir TODO el código de referencia necesario
- ✅ Seguir la plantilla militar exactamente
- ✅ Especificar imports, clases, funciones y firmas
- ✅ Incluir criterios de aceptación medibles
- ✅ Definir comandos de validación

---

## ARCHIVO DE SALIDA

**Ruta**: `docs/SYSTEM_PROMPTS_LLM_PHASES.md`
**Formato**: Markdown
**Longitud estimada**: ~8000-12000 líneas (incluyendo código de referencia)

---

## PUNTO DE SINCRONIZACIÓN

Una vez generados los prompts, actualizar:
```json
// logs/llm_implementation_status.json
{
  "prompt_generation": {
    "status": "COMPLETE",
    "timestamp": "2026-02-01T...",
    "output_file": "docs/SYSTEM_PROMPTS_LLM_PHASES.md",
    "prompts_generated": 4
  }
}
```

---

**ESTADO**: 🟢 HANDOVER READY
**ACCIÓN REQUERIDA**: Asignar a agente de generación de prompts
**PRIORIDAD**: CRÍTICA
**DEADLINE**: ASAP

═══════════════════════════════════════════════════════════════
FIN DE HANDOVER
═══════════════════════════════════════════════════════════════
