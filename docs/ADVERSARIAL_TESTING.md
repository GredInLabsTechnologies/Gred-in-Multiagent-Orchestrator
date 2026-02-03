# Guía de Tests Adversariales con LLM

## Requisitos

### 1. LM Studio
- Descargar de: https://lmstudio.ai/
- Modelo recomendado: **Qwen 3 8B** (o Qwen 2.5 7B Instruct)
- Puerto por defecto: `localhost:1234`

### 2. Configuración de LM Studio
1. Abrir LM Studio
2. Descargar modelo Qwen 3 8B desde la pestaña "Discover"
3. Cargar el modelo en la pestaña "Local Server"
4. Iniciar el servidor (botón "Start Server")
5. Verificar que responde: `curl http://localhost:1234/v1/models`

## Ejecución

### Tests Rápidos (solo fallback payloads, sin LLM)
```bash
pytest tests/test_qwen_payload_guided.py -v
```

### Tests Completos con LLM
```bash
# 1. Asegurar que LM Studio está corriendo
curl http://localhost:1234/v1/models

# 2. Ejecutar suite adversarial completa
pytest tests/adversarial/ -v --tb=short

# 3. Ver reporte
cat tests/metrics/adversarial_summary_latest.json
```

### Tests de Integración (requiere servidor)
```bash
# Terminal 1: Levantar servidor
python -m tools.repo_orchestrator.main

# Terminal 2: Ejecutar tests
ORCH_TEST_TOKEN=tu-token pytest tests/test_adaptive_attack_vectors.py tests/test_load_chaos_resilience.py -v
```

## Vectores de Ataque Cubiertos

| Categoría | Subcategorías | Payloads Esperados |
|-----------|---------------|-------------------|
| Path Traversal | basic, encoded, null_byte, windows, filter_bypass | ~75 |
| Auth Bypass | empty, length, format, encoding, timing | ~50 |
| Injection | command, sql, ldap, xpath, ssti | ~40 |
| Special Chars | unicode, control_chars | ~25 |
| **Total** | | **~190 payloads** |

## Criterio de Éxito

```
✅ PASS: 0 bypasses detectados
⚠️  WARN: Cualquier bypass es un fallo crítico de seguridad
```

## Reportes Generados

- `tests/metrics/adversarial_exhaustive_YYYYMMDD_HHMMSS.json` - Reporte completo
- `tests/metrics/adversarial_summary_latest.json` - Resumen rápido
- `tests/metrics/adaptive_attack_report.json` - Tests adaptativos
- `tests/metrics/chaos_resilience_report.json` - Tests de caos

## Troubleshooting

### LM Studio no responde
```bash
# Verificar que el servidor está corriendo
curl http://localhost:1234/v1/models

# Si falla, reiniciar LM Studio y cargar el modelo
```

### Tests skipped
```bash
# Verificar disponibilidad
python -c "from tests.llm.lm_studio_client import is_lm_studio_available; print(is_lm_studio_available())"
```

### Error de memoria en LM Studio
- Cerrar otras aplicaciones
- Usar modelo más pequeño (Qwen 2.5 3B)
- Reducir context length en settings
