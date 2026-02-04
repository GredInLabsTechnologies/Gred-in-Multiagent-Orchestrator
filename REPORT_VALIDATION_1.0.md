# Informe de validación para release 1.0 (handover)

## Contexto
Este informe resume el estado actual y los pasos que **otro agente** debe ejecutar para validar la salida de la versión **1.0** del Repo Orchestrator.

## Estado actual (lo ya validado)
- **Tests unitarios críticos** y de **integridad** ya pasan:
  ```bash
  python -m pytest tests/unit/test_main.py tests/test_integrity_deep.py -v --tb=short
  ```
  Resultado: **11 passed**.
- Se corrigieron errores por `CancelledError` en shutdown/lifespan.
- Se actualizó el `tests/integrity_manifest.json` para reflejar los hashes reales.
- Los reportes adversariales más recientes muestran **0 bypasses** y **0 panics**.

## Archivos/áreas modificadas recientemente
- `tools/repo_orchestrator/main.py`
- `tools/repo_orchestrator/tasks.py`
- `tests/unit/test_main.py`
- `tests/integrity_manifest.json`
- `tests/llm/lm_studio_client.py` (parsing tolerante a JSON truncado)

## Validación pendiente para 1.0 (pasos exactos)

### 1) Verificar LM Studio (Qwen) y ejecutar suite adversarial
**Requisito:** LM Studio con Qwen 3 cargado (localhost:1234)

```bash
pytest tests/adversarial/test_exhaustive_adversarial.py -v --tb=short
```

**Esperado:**
- Todos los tests pasan o hacen skip si LM Studio no está disponible.
- Se generan:
  - `tests/metrics/adversarial_exhaustive_<timestamp>.json`
  - `tests/metrics/adversarial_summary_latest.json`

### 2) Revisar métricas finales
Abrir y verificar los JSON:

```bash
type tests\metrics\adversarial_summary_latest.json
type tests\metrics\adversarial_exhaustive_*.json
type tests\metrics\payload_guided_report.json
type tests\metrics\adaptive_attack_report.json
```

**Esperado:**
- `bypass_count = 0`
- `panic_count = 0`

### 3) Ejecutar suite completa (recomendado antes de 1.0)
```bash
python -m pytest -v --tb=short
```

**Esperado:**
- Sin errores de teardown.
- Sin fallos de integridad.

### 4) Validación de integridad (si hay cambios de último minuto)
Si se modifica cualquier archivo crítico, actualizar el manifiesto:

```bash
python -c "import json, hashlib; from pathlib import Path; base=Path('.'); manifest=base/'tests/integrity_manifest.json'; data=json.loads(manifest.read_text()); target='tools/repo_orchestrator/main.py'; sha=hashlib.sha256((base/target).read_bytes().replace(b'\\r\\n', b'\\n')).hexdigest(); data[target]=sha; manifest.write_text(json.dumps(data, indent=4)); print(sha)"
```

## Checklist de release 1.0
- [ ] Suite completa de pytest (sin errores)
- [ ] Tests adversariales ejecutados con Qwen
- [ ] `bypass_count = 0` y `panic_count = 0` en métricas
- [ ] `tests/test_integrity_deep.py` pasa
- [ ] Validación en entorno limpio (Docker/CI) si aplica

## Nota de riesgos conocidos
- Errores previos de `CancelledError` estaban ligados a shutdown/lifespan. Ya se corrigieron, pero se recomienda verificar con la suite completa.
- Cualquier cambio en archivos críticos requiere actualizar el manifiesto de integridad.

---

**Siguiente paso recomendado:** ejecutar el suite completo + adversarial con LM Studio y archivar los JSON de métricas como evidencia de release.