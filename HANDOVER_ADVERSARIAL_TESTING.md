# 🔒 Handover: Pruebas Adversariales con LLM

**Fecha**: 2026-02-03
**Agente anterior**: Claude Opus 4.5
**Estado**: Suite preparada, pendiente ejecución con LLM

---

## 📋 RESUMEN EJECUTIVO

Se ha preparado una suite exhaustiva de tests adversariales para validar la seguridad del Gred Repo Orchestrator. La suite está diseñada para usar un LLM (Qwen 3 8B via LM Studio) para generar payloads de ataque de forma procedural.

**Objetivo**: Validar que el sistema tiene **0 bypasses** contra ~190 vectores de ataque generados por LLM.

---

## ✅ COMPLETADO (Fase 0 + Preparación Fase 1)

### Fase 0 - Estabilización
- [x] 248 tests pasando, 0 warnings
- [x] Fix de `conftest.py` para limpiar `recent_events` entre tests
- [x] Fix de `pytest_ignore_collect` para pytest 9+
- [x] Commit: `796d9cc`

### Preparación Fase 1 - Suite Adversarial
- [x] Creado `tests/adversarial/prompts_exhaustive.py` - 20+ categorías de ataque
- [x] Creado `tests/adversarial/test_exhaustive_adversarial.py` - Tests parametrizados
- [x] Creado `docs/ADVERSARIAL_TESTING.md` - Documentación
- [x] Módulos LLM security en `tools/llm_security/`

---

## ⏳ PENDIENTE (Tu Tarea)

### 1. Configurar LM Studio
```bash
# Descargar LM Studio: https://lmstudio.ai/
# Modelo recomendado: Qwen 3 8B (o Qwen 2.5 7B Instruct)

# En LM Studio:
# 1. Ir a "Discover" → Buscar "Qwen 3 8B"
# 2. Descargar el modelo
# 3. Ir a "Local Server" → Cargar modelo
# 4. Click "Start Server"

# Verificar que responde:
curl http://localhost:1234/v1/models
```

### 2. Ejecutar Suite Adversarial
```bash
cd c:\Users\shilo\Documents\GitHub\Gred-Repo-Orchestrator

# Ejecutar todos los tests adversariales
pytest tests/adversarial/ -v --tb=short

# O ejecutar por categoría:
pytest tests/adversarial/test_exhaustive_adversarial.py::TestPathTraversalExhaustive -v
pytest tests/adversarial/test_exhaustive_adversarial.py::TestAuthBypassExhaustive -v
pytest tests/adversarial/test_exhaustive_adversarial.py::TestInjectionExhaustive -v
pytest tests/adversarial/test_exhaustive_adversarial.py::TestSpecialCharsExhaustive -v
```

### 3. Validar Resultados
```bash
# Ver reporte generado
cat tests/metrics/adversarial_summary_latest.json

# Criterio de éxito:
# - bypasses: 0
# - Todos los tests pasan
```

---

## 🗂️ ESTRUCTURA DE ARCHIVOS

```
tests/
├── adversarial/
│   ├── __init__.py
│   ├── prompts_exhaustive.py      # 20+ categorías de prompts para LLM
│   └── test_exhaustive_adversarial.py  # Suite de tests parametrizados
├── llm/
│   ├── lm_studio_client.py        # Cliente para LM Studio API
│   └── prompt_templates.py        # Templates de prompts legacy
├── llm_security/                  # Tests de módulos LLM security
│   └── test_*.py
└── metrics/
    ├── runtime_metrics.py         # Collector de métricas
    └── *.json                     # Reportes generados
```

---

## 🎯 VECTORES DE ATAQUE CUBIERTOS

| Categoría | Subcategorías | Payloads Esperados |
|-----------|---------------|-------------------|
| **Path Traversal** | basic, encoded, null_byte, windows, filter_bypass | ~75 |
| **Auth Bypass** | empty, length, format, encoding, timing | ~50 |
| **Injection** | command, sql, ldap, xpath, ssti | ~40 |
| **Special Chars** | unicode, control_chars | ~25 |
| **Total** | | **~190 payloads** |

### Detalle de Prompts (en `prompts_exhaustive.py`)

```python
ATTACK_VECTORS = {
    # Path Traversal
    "path_traversal_basic": "../, ....//",
    "path_traversal_encoded": "%2e%2e%2f, %252e%252e%252f",
    "path_traversal_null_byte": "%00 injections",
    "path_traversal_windows": "C:/, UNC paths, ADS",
    "path_traversal_filter_bypass": "nested, whitespace, comments",

    # Auth Bypass
    "auth_empty_variations": "null, whitespace, zero-width",
    "auth_length_boundary": "15 chars, 10000+ chars",
    "auth_format_attacks": "printf, template injection",
    "auth_encoding_attacks": "base64, hex, unicode",
    "auth_timing_attacks": "slow comparison",

    # Injection
    "injection_command": "; whoami, | dir, $()",
    "injection_sql": "' OR 1=1--, UNION SELECT",
    "injection_ssti": "{{7*7}}, ${config}",

    # Special
    "special_unicode": "RTL, zero-width, homoglyphs",
    "special_control_chars": "\\x00-\\x1f",
}
```

---

## 🔧 CONFIGURACIÓN

### Variables de Entorno
```bash
# Opcional - el código tiene defaults
export LM_STUDIO_HOST="http://localhost:1234/v1"
export ORCH_TEST_TOKEN="test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"
```

### Modelo LLM Recomendado
- **Nombre**: Qwen 3 8B o Qwen 2.5 7B Instruct
- **Temperatura**: 0.1 (configurado en código)
- **Response Format**: JSON Schema (structured output)

---

## 📊 FORMATO DE RESPUESTA DEL LLM

El LLM debe responder con este JSON schema:

```json
{
    "thought_process": "Brief analysis of attack strategy",
    "payloads": ["payload1", "payload2", "..."],
    "attack_category": "path_traversal|auth_bypass|injection|etc",
    "severity_estimate": "critical|high|medium|low"
}
```

---

## ⚠️ CRITERIO DE ÉXITO

```
✅ PASS:
   - 0 bypasses detectados
   - Todos los payloads generados por LLM
   - Reporte guardado en tests/metrics/

❌ FAIL:
   - Cualquier bypass = fallo crítico de seguridad
   - LLM no genera payloads = revisar conexión/modelo
```

---

## 🚨 SI ENCUENTRAS BYPASSES

1. **NO hacer commit** del código vulnerable
2. Documentar el bypass:
   - Payload exacto
   - Endpoint afectado
   - Response status y body
3. Crear fix en el módulo de seguridad correspondiente:
   - `tools/repo_orchestrator/security/validation.py` - Path validation
   - `tools/repo_orchestrator/security/auth.py` - Auth validation
4. Re-ejecutar suite completa
5. Commit solo cuando 0 bypasses

---

## 📞 CONTEXTO ADICIONAL

### Arquitectura de Seguridad
- **Auth**: Bearer token, mínimo 16 chars, constant-time comparison
- **Rate Limit**: 60 req/min por IP
- **Panic Mode**: Fail-closed después de 5 auth failures
- **Path Validation**: Allowlist + denylist + extension filter + symlink detection

### Tests Existentes (ya pasan)
- 248 tests unitarios + integración
- Fuzzing básico con fallback payloads
- LLM security modules validation

### Commits Relevantes
- `796d9cc` - feat: add exhaustive adversarial LLM security test suite
- `b1bd9a0` - docs: update refactor log, add forensic report

---

## 🎮 COMANDO RÁPIDO

```bash
# Todo en uno (asumiendo LM Studio ya corre):
cd c:\Users\shilo\Documents\GitHub\Gred-Repo-Orchestrator
pytest tests/adversarial/ -v --tb=short 2>&1 | tee adversarial_results.txt
cat tests/metrics/adversarial_summary_latest.json
```

---

**Buena suerte con las pruebas. El objetivo es 0 bypasses.** 🔒
