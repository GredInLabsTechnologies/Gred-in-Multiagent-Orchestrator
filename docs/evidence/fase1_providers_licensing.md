# Evidencia Fase 1 — Providers + Licensing

Fecha: 2026-02-20

## Alcance validado

- Tests HTTP/servicios críticos de providers en backend.
- Tests de licensing guard en backend.
- Verificación de dependencia `jose` en web.
- Verificación de variables en `gimo-web/.env.example`.

## Ejecuciones realizadas

### 1) Providers + Licensing (backend)

Comando:

```bash
python -m pytest tests/services/test_provider_v2_storage_and_catalog_cache.py tests/unit/test_license_guard.py -q
```

Resultado:

- `41 passed` (exit code 0)
- Sin fallos

### 2) Validación cruzada con OPS routing (providers en endpoints)

Comando:

```bash
python -m pytest tests/test_ops_v2.py -q
```

Resultado observado dentro de corrida agregada:

- `tests/test_ops_v2.py` en verde (con `xpassed` ya existentes)

### 3) Corrida agregada fase 1+2

Comando:

```bash
python -m pytest tests/services/test_cognitive_gios_bridge.py tests/services/test_provider_v2_storage_and_catalog_cache.py tests/unit/test_license_guard.py tests/test_ops_v2.py -q
```

Resultado:

- `91 passed, 2 xpassed, 3 warnings` (exit code 0)

## Web licensing: dependencia y entorno

### Dependencia

Archivo: `../GIMO WEB/gimo-web/package.json`

- `"jose": "^6.0.8"` presente en `dependencies` ✅

### Entorno

Archivo: `../GIMO WEB/gimo-web/.env.example`

Variables relevantes presentes (entre otras):

- `NEXT_PUBLIC_APP_URL`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`
- `FIREBASE_ADMIN_SERVICE_ACCOUNT`
- `ADMIN_EMAILS`
- `LICENSE_SIGNING_PRIVATE_KEY`

## Estado de tests UI (ProviderSettings)

Comando ejecutado:

```bash
npm --prefix tools/orchestrator_ui exec -- vitest --root tools/orchestrator_ui run --environment jsdom src/components/__tests__/ProviderSettings.test.tsx
```

Resultado actual:

- Vitest reporta `No test suite found` para `ProviderSettings.test.tsx`.
- Se dejó una suite mínima reescrita, pero el runner sigue sin detectarla en este entorno.

## Veredicto Fase 1

- **Backend providers/licensing: OK**
- **Web/licensing config: OK**
- **UI ProviderSettings en Vitest: pendiente de estabilización del runner**

Estado recomendado de Fase 1: **Parcial alto** (bloque pendiente: detección/ejecución suite UI en este entorno).
