# Uso de tokens en el orquestador (tests y runtime)

## Objetivo
Documentar cómo se gestionan los tokens de autenticación en el orquestador y las pruebas, evitando tokens hardcodeados y manteniendo escenarios de seguridad.

## Tokens de runtime
Los tokens principales se cargan o generan desde `tools/repo_orchestrator/config.py`:

- `ORCH_TOKEN`
  - Token principal del orquestador.
  - Si no existe en entorno, se lee de `ORCH_TOKEN_FILE` o se genera automáticamente.
- `ORCH_ACTIONS_TOKEN`
  - Token para acciones automatizadas.
  - Si no existe en entorno, se lee de `ORCH_ACTIONS_TOKEN_FILE` o se genera automáticamente.

**Buenas prácticas:**
- Nunca commitear tokens reales en el repositorio.
- Para entornos de CI/CD usar variables de entorno seguras.
- En producción, usar permisos restrictivos para los archivos `.orch_token` y `.orch_actions_token`.

## Tokens en tests
Los tests centralizan tokens/actores en `tests/conftest.py`:

- `ORCH_TEST_TOKEN` (recomendado para tests):
  - Si existe, se usa como `DEFAULT_TEST_TOKEN`.
  - Si no existe, se usa `ORCH_TOKEN` y se aplica un fallback de prueba.
- `ORCH_TEST_ACTOR`:
  - Nombre de actor estándar para overrides de autenticación.
- `ORCH_LLM_TEST_ACTOR`:
  - Actor específico para escenarios de LLM (prompt injection, exfiltración, etc.).

**Fixtures disponibles:**
- `valid_token`: token válido para requests autenticadas.
- `test_actor`: actor base para overrides.

## Casos especiales (tokens inválidos)
Algunos tests contienen tokens inválidos intencionalmente para validar rechazos:

- `invalid-token-1234567890`
- `token123\x00admin`
- `token123\nX-Admin: true`
- cadenas de longitud extrema o con formatos malformados

**Nota:** estos tokens se mantienen explícitos para cubrir pruebas de seguridad, no deben reemplazarse por tokens válidos.

## Cómo configurar en local
Ejemplo (PowerShell):

```powershell
$env:ORCH_TEST_TOKEN="token-local-seguro"
$env:ORCH_TEST_ACTOR="tester"
$env:ORCH_LLM_TEST_ACTOR="llm_tester"
```

Ejemplo (bash):

```bash
export ORCH_TEST_TOKEN="token-local-seguro"
export ORCH_TEST_ACTOR="tester"
export ORCH_LLM_TEST_ACTOR="llm_tester"
```

## Verificación rápida
- Usa `valid_token` y `test_actor` en tests.
- Evita añadir tokens reales en código.
- Conserva tokens inválidos solo en tests de validación/seguridad.
