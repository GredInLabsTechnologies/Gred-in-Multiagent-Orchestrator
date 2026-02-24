# GIMO Repository Master Refactor Plan

> **Status:** ACTIVE — Documento autoritativo para la limpieza y refactor completo del repositorio
> **Fecha:** 2026-02-23
> **Objetivo:** Llevar el repo de 3/10 a 11/10 en salud de ingeniería
> **Principio rector:** Si no se usa, se borra. Si se repite, se unifica. Si confunde, se simplifica.

---

## Diagnóstico Actual

| Métrica | Estado | Target |
|---------|--------|--------|
| Documentación | 67 .md (26 deprecated, 7 history, solo ~10 útiles) | ≤15 docs activos |
| Branches | 20 remote (16 dependabot/stale) | Solo `main` + PRs activos |
| Directorios en `tools/` | 9 (5 legacy muertos) | 2 (`gimo_server/`, `orchestrator_ui/`) |
| Scripts | 50+ archivos (debug, installers, CI) | ≤10 esenciales |
| Archivos basura en root | `lghub_settings_debug.json` (110KB), `last_llm_response.json`, `package-lock.json` vacío | Zero basura |
| `__pycache__` dirs | 54 dirs, 425 .pyc files | Zero (limpieza + gitignore ya OK) |
| Worktrees | 1 stale (`cool-chatterjee`, ya mergeado) | Zero stale |
| Cambios sin commit | 16 archivos modificados | Zero |
| Tests | 648 tests en 84 archivos, 7 subdirs (175 security dispersos, 44 de módulo muerto) | ~400-450 tests en ~35 archivos, 2 subdirs |
| Frontend | 55 componentes, 12 tabs, bugs auth | Ver `UI_IMPROVEMENT_PLAN_2026-02-23.md` |

---

## FASE 0 — Snapshot y Seguridad (ANTES de tocar nada)

### 0.1 Commit del estado actual
```
Acción: Commit de los 16 archivos modificados pendientes
Archivos: ver `git status`
Mensaje: "checkpoint: pre-refactor state with E2E fixes"
```

### 0.2 Tag de seguridad
```
Acción: git tag v0.9-pre-refactor
Motivo: Punto de rollback si algo sale mal
```

### 0.3 Verificar tests
```
Acción: python -m pytest -x -q
Criterio: 100% tests passing antes de empezar
```

---

## FASE 1 — Purga de Basura (0 riesgo, máximo impacto visual)

### 1.1 Eliminar archivos que NUNCA debieron estar en el repo

| Archivo | Razón | Acción |
|---------|-------|--------|
| `lghub_settings_debug.json` (110KB) | Settings de Logitech G Hub. Nada que ver con GIMO | `git rm` |
| `last_llm_response.json` | Debug artifact de una sesión anterior | `git rm` |
| `package-lock.json` (root) | Lock vacío sin package.json real en root | `git rm` |
| `docker-compose.yml` | Si no se usa Docker activamente → verificar y decidir | Revisar; si es stub → `git rm` |

### 1.2 Añadir a .gitignore (prevención)
```gitignore
# Debug artifacts
last_llm_response.json
lghub_*.json
gimo_debug.log

# Root-level accidental files
/package-lock.json
```

### 1.3 Limpiar __pycache__ del workspace
```bash
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null
```
*Nota: Ya están en .gitignore, no se trackean en git. Solo limpieza local.*

### 1.4 Eliminar worktree stale
```bash
git worktree remove .claude/worktrees/cool-chatterjee --force
git branch -d claude/cool-chatterjee  # ya mergeado
```

### 1.5 Eliminar branch local mergeado
```bash
git branch -d integration/fase0-baseline-e2e
```

### 1.6 Limpiar branches remotos stale
```bash
# Dependabot branches (16 de ellos) — cerrar PRs primero si están abiertos
git push origin --delete dependabot/npm_and_yarn/tools/orchestrator_ui/autoprefixer-10.4.24
git push origin --delete dependabot/npm_and_yarn/tools/orchestrator_ui/eslint-10.0.0
# ... (listar todos los 14 dependabot branches)
git push origin --delete codex/set-up-sonar-github-actions-workflow
git push origin --delete integration/fase0-baseline-e2e
```

**Criterio Fase 1:** `git branch -r` muestra solo `origin/main` y `origin/HEAD`

---

## FASE 2 — Consolidar Directorios (Estructura Limpia)

### 2.1 Inventario de `tools/`

| Directorio | LOC | Usado por gimo_server | Veredicto |
|-----------|-----|----------------------|-----------|
| `gimo_server/` | ~19K | — (es el core) | **MANTENER** |
| `orchestrator_ui/` | ~5K src | — (es el frontend) | **MANTENER** |
| `repo_orchestrator/` | ? | Sí: `plan_executor.py` importa models y services | **MIGRAR imports → ELIMINAR** |
| `llm_security/` | ? | Sí: `provider_service.py` importa `NormalizedLLMCache` | **MIGRAR cache → ELIMINAR** |
| `gptactions_gateway/` | ? | No | **ELIMINAR** |
| `patch_validator/` | ? | No | **ELIMINAR** |
| `patch_integrator/` | ? | No | **ELIMINAR** |
| `gimo_mcp/` | ? | No (bridge está en `gimo_server/mcp_bridge/`) | **ELIMINAR** |

### 2.2 Migración de dependencias antes de eliminar

**`repo_orchestrator/` → `gimo_server/`:**
- `tools/gimo_server/services/plan_executor.py` importa:
  - `tools.repo_orchestrator.models.Plan`, `PlanTask`, `DelegationRequest`, `PlanUpdateRequest`
  - `tools.repo_orchestrator.services.plan_service.PlanService`
  - `tools.repo_orchestrator.services.sub_agent_manager.SubAgentManager`
- **Acción:** Mover los models usados a `gimo_server/ops_models.py` o crear `gimo_server/models/plan_models.py`. Actualizar imports en `plan_executor.py`. Si `PlanService` y `SubAgentManager` tienen lógica real, moverlos a `gimo_server/services/`.

**`llm_security/` → `gimo_server/`:**
- `tools/gimo_server/services/provider_service.py` importa `NormalizedLLMCache`
- **Acción:** Mover `NormalizedLLMCache` a `gimo_server/services/llm_cache.py`. Actualizar import.

### 2.3 Eliminar directorios vaciados
```bash
rm -rf tools/gptactions_gateway/
rm -rf tools/patch_validator/
rm -rf tools/patch_integrator/
rm -rf tools/gimo_mcp/
rm -rf tools/repo_orchestrator/  # después de migración
rm -rf tools/llm_security/       # después de migración
```

### 2.4 Tests que importan de módulos eliminados
- Buscar `from tools.repo_orchestrator` / `from tools.gptactions_gateway` etc. en `tests/`
- Actualizar imports o mover tests relevantes
- Eliminar tests de código que ya no existe

**Criterio Fase 2:** `ls tools/` muestra solo `gimo_server/` y `orchestrator_ui/`. Todos los tests pasan.

---

## FASE 3 — Consolidar Scripts

### 3.1 Inventario de `scripts/`

**Esenciales (mantener):**
| Script | Razón |
|--------|-------|
| `scripts/ci/quality_gates.py` | CI pipeline |
| `scripts/ci/verify_integrity.py` | CI pipeline |
| `scripts/ci/check_no_artifacts.py` | CI pipeline |
| `scripts/generate_license_keys.py` | Operaciones |
| `scripts/generate_manifest.py` | Operaciones |
| `scripts/ops/start_orch.cmd` + `.sh` | Launcher |

**Debug/dev (mover a `scripts/dev/` o eliminar):**
| Script | Acción |
|--------|--------|
| `scripts/dev/debug_llm_response.py` | Eliminar (one-off debug) |
| `scripts/dev/debug_qwen_connection.py` | Eliminar (one-off debug) |
| `scripts/dev/desktop_app.py` | Evaluar: ¿se usa? Si no → eliminar |
| `scripts/dev/test_*.py` | Mover tests reales a `tests/`, eliminar los ad-hoc |
| `scripts/dev/diagnose_failures.py` | Eliminar |
| `scripts/dev/analyze_dependencies.py` | Eliminar |
| `scripts/tools/installer_gui.py` | Evaluar: ¿funciona? Si no → eliminar |
| `scripts/tools/installer.iss` | InnoSetup script — ¿se usa? Si no → eliminar |
| `scripts/tools/scan_strange_terms.py` | Eliminar |
| `scripts/tools/probe_ports.py` | Mantener (útil para debug) |
| `scripts/tools/claude_cli.py` | Evaluar |
| `scripts/setup/setup_gptactions_jail.ps1` | Eliminar (gptactions ya eliminado) |
| `scripts/setup/sync_openai_ips.py` | Eliminar (gptactions ya eliminado) |

### 3.2 Limpiar pycache de scripts
```bash
find scripts -name "__pycache__" -exec rm -rf {} +
find scripts -name "*.pyc" -delete
```

### 3.3 Estructura final de scripts/
```
scripts/
├── ci/                    # Solo CI quality gates
│   ├── quality_gates.py
│   ├── verify_integrity.py
│   └── check_no_artifacts.py
├── ops/                   # Solo operaciones
│   ├── start_orch.cmd
│   ├── start_orch.sh
│   └── vitaminize_repo.sh
├── generate_license_keys.py
├── generate_manifest.py
└── setup_mcp.py
```

**Criterio Fase 3:** `scripts/` tiene ≤15 archivos. Zero pycache. Zero scripts de debug one-off.

---

## FASE 4 — Consolidar Documentación

### 4.1 Problema actual
67 archivos .md. Un agente nuevo tiene que leer 5,308 líneas de docs solo en `docs/` (sin contar deprecated/history). La mitad se contradicen entre sí o están obsoletos.

### 4.2 Documentos que se mantienen (máximo 10)

| Documento | Contenido | Líneas target |
|-----------|-----------|---------------|
| `README.md` | Intro, quickstart, links a los demás | ≤80 |
| `docs/SYSTEM.md` | Arquitectura del sistema (single source of truth) | ≤250 |
| `docs/SETUP.md` | Instalación, config, primer run | ≤100 |
| `docs/API.md` | Contratos API (merge de API_CONTRACTS + OPERATIONS) | ≤200 |
| `docs/SECURITY.md` | Auth, trust, policies | ≤150 |
| `docs/UI_IMPROVEMENT_PLAN_2026-02-23.md` | Plan de mejoras frontend activo | (ya existe) |
- [x] Fase 6: Mejoras Frontend (Optimización, UX, Traducción) - **ESTADO: COMPLETADO**
| `docs/REPO_MASTERPLAN_2026-02-23.md` | Este documento | (ya existe) |
| `docs/CHANGELOG.md` | Historial de cambios por versión | Crear nuevo |

### 4.3 Documentos a archivar en `docs/archive/`

Mover TODO lo siguiente a `docs/archive/`:
```
docs/deprecated/           → docs/archive/deprecated/
docs/history/              → docs/archive/history/
docs/evidence/             → docs/archive/evidence/
docs/runbooks/             → docs/archive/runbooks/

# Docs activos que se fusionan o se deprecan:
docs/GIMO_ROADMAP.md           → archive (contenido relevante fusionar en SYSTEM.md)
docs/GIMO_AUDIT_REPORT.md      → archive
docs/GIMO_UI_OVERHAUL_PLAN.md  → archive (ya deprecated)
docs/TOKEN_MASTERY_PLAN.md     → archive (lo implementado va a SYSTEM.md)
docs/PHOENIX_PLAN.md           → archive
docs/FASE3_UNIFICADO_TODO.md   → archive
docs/PROVIDER_UX_REWORK.md     → archive (ya deprecated)
docs/STATUS.md                 → archive
docs/COMPREHENSIVE_INFRASTRUCTURE_REPORT.md → archive
docs/HYBRID_INFRASTRUCTURE.md  → archive
docs/SUB_DELEGATION_PROTOCOL.md → archive (fusionar en SYSTEM.md si relevante)
docs/ADAPTERS.md               → archive (fusionar en SYSTEM.md)
docs/ISSUE_FEATURE_CODEX_ACCOUNT_MODE.md → archive
docs/PLAN_MAESTRO_UNIFICADO_GIMO_PRIMERA_PRUEBA_REAL.md → archive
docs/DOCS_REGISTRY.md          → archive (reemplazar por este plan)
docs/GPT_ACTIONS_SECURITY_ARCHITECTURE.md → archive (gptactions ya eliminado)
docs/CI.md                     → fusionar sección relevante en SETUP.md → archive
docs/Launcher.md               → fusionar en SETUP.md → archive
docs/RELEASE.md                → fusionar en SETUP.md → archive
docs/TROUBLESHOOTING.md        → fusionar en SETUP.md → archive
```

### 4.4 Root MDs a limpiar

| Archivo | Acción |
|---------|--------|
| `PLAN.md` | Eliminar — hay planes mejores en docs/ |
| `CLEANUP_PLAN.md` | Eliminar — ya ejecutado, este plan lo reemplaza |
| `GIMO_STATE_MAP.md` (376 líneas) | Fusionar lo útil en `docs/SYSTEM.md` → eliminar |
| `ARCHITECTURE.md` (44 líneas) | Fusionar en `docs/SYSTEM.md` → eliminar |
| `SECURITY.md` (7 líneas) | Fusionar en `docs/SECURITY.md` → eliminar root version |

### 4.5 Estructura final de docs/
```
docs/
├── SYSTEM.md                         # Arquitectura, componentes, flujos
├── SETUP.md                          # Instalación, config, CI, troubleshooting
├── API.md                            # Contratos de API
├── SECURITY.md                       # Auth, trust, policies
├── UI_IMPROVEMENT_PLAN_2026-02-23.md # Plan activo frontend
├── REPO_MASTERPLAN_2026-02-23.md     # Este documento
├── CHANGELOG.md                      # Nuevo: historial de releases
└── archive/                          # Todo lo demás, organizado por fecha
    ├── deprecated/
    ├── history/
    ├── evidence/
    └── plans/
```

**Criterio Fase 4:** `ls docs/*.md` muestra ≤8 archivos. `ls *.md` en root muestra solo `README.md`. Un agente nuevo puede entender el sistema leyendo solo SYSTEM.md + SETUP.md.

---

## FASE 5 — Higiene de Código Backend

### 5.1 Eliminar `__init__.py` vacíos innecesarios
```
tests/gptactions/__init__.py
tests/llm/__init__.py
tests/metrics/__init__.py
tests/services/__init__.py
tests/unit/__init__.py
tools/gimo_server/services/storage/__init__.py
tools/repo_orchestrator/services/providers/__init__.py  # se elimina con el dir
tools/repo_orchestrator/ws/__init__.py                  # se elimina con el dir
```

### 5.2 Verificar que `gimo_debug.log` writes se eliminan
- `tools/gimo_server/mcp_bridge/native_tools.py` — tiene writes de debug a archivo
- Buscar cualquier `open(` write to log en el codebase y eliminar

### 5.3 Limpiar imports muertos en backend
```bash
# Ejecutar después de eliminar tools legacy
grep -rn "from tools.gptactions_gateway" tools/gimo_server tests --include="*.py"
grep -rn "from tools.patch_validator" tools/gimo_server tests --include="*.py"
grep -rn "from tools.patch_integrator" tools/gimo_server tests --include="*.py"
grep -rn "from tools.gimo_mcp" tools/gimo_server tests --include="*.py"
# Cualquier resultado → fix o eliminar
```

### 5.4 Consolidar config
- `.env` debe tener SOLO las variables que realmente se usan
- `.env.example` debe ser el template exacto de `.env` con valores vacíos
- Eliminar cualquier variable que ya no aplique (ej: `ORCH_ACTIONS_TOKEN` si gptactions fue eliminado)

**Criterio Fase 5:** `python -m pytest -x -q` pasa 100%. Zero imports a módulos eliminados. Zero debug log writes.

---

## FASE 5.5 — Rediseño de Test Suite

### Diagnóstico

| Métrica | Antes | Target |
|---------|-------|--------|
| Tests totales | 648 | ~400-450 |
| Archivos test | 84 | ~35 |
| Subdirectorios | 7 (`unit/`, `services/`, `adversarial/`, `llm/`, `metrics/`, `llm_security/`, `gptactions/`) | 2 (`unit/`, `integration/`) |
| Security tests | 175 en 17+ archivos | ~80 en 4 archivos |
| Tests de módulo muerto | 44 (gptactions) + ~40 (llm_security) | 0 |
| Duplicados detectados | ~15-20 tests | 0 |

### Distribución actual por dominio

| Dominio | Tests | Archivos | Problema |
|---------|-------|----------|----------|
| Security/Trust/Adversarial | 175 (28%) | 17+ | Fragmentación extrema: `test_security_hardened`, `test_security_core`, `test_unit_security`, `test_security_validation`, `test_adaptive_security` — 5 archivos con nombres similares |
| GPT Actions | 44 | 1 (`tests/gptactions/test_gateway_security.py`) | Módulo `gptactions_gateway/` eliminado en Fase 2 → tests muertos |
| LLM Security | ~40 | 9 (`tests/llm_security/`) | Módulo `llm_security/` eliminado en Fase 2 → migrar lo útil |
| OPS (routes/plans/runs) | 108 | ~5 | Razonable, mantener |
| Cost/Economy/Mastery | 68 | 8 | Algo de duplicación (`test_provider_budget` existe en root Y en services/) |
| Core (services, auth, etc.) | ~213 | ~30 | Razonable, mantener |

### 5.5.1 Eliminar tests de módulos muertos (~84 tests)

**Eliminar completamente:**
```
tests/gptactions/                          # 44 tests → todo el directorio (gptactions_gateway eliminado)
tests/llm_security/test_anomaly_detector.py  # testa tools.llm_security (eliminado)
tests/llm_security/test_audit.py
tests/llm_security/test_cache.py
tests/llm_security/test_llm_client.py
tests/llm_security/test_metrics.py
tests/llm_security/test_prompts.py
tests/llm_security/test_scope_limiter.py
```

**Migrar antes de eliminar** (funcionalidad que se mueve a `gimo_server`):
```
tests/llm_security/test_input_sanitizer.py   → tests/unit/test_security.py (si sanitizer migra)
tests/llm_security/test_output_validator.py  → tests/unit/test_security.py (si validator migra)
```

**Tests de `repo_orchestrator` que necesitan actualizar imports:**
```
tests/services/test_file_service.py      → actualizar imports a gimo_server
tests/services/test_git_service.py       → actualizar imports a gimo_server
tests/services/test_snapshot_service.py  → actualizar imports a gimo_server
tests/test_quality_service.py            → actualizar imports a gimo_server
```

### 5.5.2 Consolidar security tests (175 → ~80, 17 archivos → 4)

**Estructura target:**

| Archivo nuevo | Fusiona | Tests aprox |
|---------------|---------|-------------|
| `tests/unit/test_auth.py` | `test_auth_validation.py` (13) + tests auth de `test_ops_v2.py` + `test_api_security.py` (8) | ~25 |
| `tests/unit/test_trust.py` | `test_trust_engine.py` (4) + `test_trust_engine_latency.py` (3) + `test_trust_event_buffer.py` (2) + `test_trust_store.py` (1) + `test_trust_routes.py` (19) + partes de `test_security_core.py` | ~25 |
| `tests/unit/test_security_guards.py` | `test_security_validation.py` (19) + `test_security_hardened.py` (5) + `test_unit_security.py` (4) + `test_adaptive_security.py` (12) + `test_cognitive_security_guard.py` (2) + `test_llm_security_leakage.py` (19 → reducir a ~10 representativos) | ~30 |
| `tests/integration/test_adversarial.py` | `test_exhaustive_adversarial.py` (7) + `test_adaptive_attack_vectors.py` (3) + `test_fuzzing.py` (2) + `test_threat_engine_custom.py` (4) | ~15 |

**Regla de consolidación:** Si dos tests hacen assert sobre el mismo endpoint o la misma función con inputs similares → merge en un test parametrizado.

**Ejemplo de deduplicación con parametrize:**
```python
# ANTES: 5 tests separados en 3 archivos
def test_sql_injection_blocked(): ...
def test_xss_blocked(): ...
def test_path_traversal_blocked(): ...
def test_command_injection_blocked(): ...
def test_null_byte_blocked(): ...

# DESPUÉS: 1 test parametrizado
@pytest.mark.parametrize("payload,attack_type", [
    ("' OR 1=1 --", "sql_injection"),
    ("<script>alert(1)</script>", "xss"),
    ("../../etc/passwd", "path_traversal"),
    ("; rm -rf /", "command_injection"),
    ("file\x00.txt", "null_byte"),
])
def test_malicious_input_blocked(payload, attack_type): ...
```

### 5.5.3 Deduplicar tests de dominio

**Duplicados concretos a fusionar:**
- `tests/test_provider_budget.py` + `tests/services/test_provider_budget.py` → uno solo en `tests/unit/`
- `tests/test_model_router_service.py` + `tests/services/test_model_router_v2.py` → uno solo
- `tests/services/test_economy_config.py` + `tests/unit/test_user_economy_config.py` → uno solo

### 5.5.4 Aplanar estructura de directorios

**Antes (7 subdirs):**
```
tests/
├── adversarial/      # 1 archivo
├── gptactions/       # 1 archivo (MUERTO)
├── llm/              # 1 archivo
├── llm_security/     # 9 archivos (MUERTOS)
├── metrics/          # 1 archivo
├── services/         # 14 archivos
├── unit/             # 12 archivos
├── test_*.py         # 30 archivos en root
└── conftest.py
```

**Después (2 subdirs):**
```
tests/
├── unit/              # Tests unitarios (mocks, sin I/O real)
│   ├── test_auth.py
│   ├── test_trust.py
│   ├── test_security_guards.py
│   ├── test_cost_service.py
│   ├── test_economy_config.py
│   ├── test_budget_forecast.py
│   ├── test_model_router.py
│   ├── test_provider_service.py
│   ├── test_graph_engine.py
│   ├── test_storage.py
│   ├── test_file_service.py
│   ├── test_license_guard.py
│   ├── test_routes.py
│   ├── test_services.py
│   └── test_config.py
├── integration/       # Tests E2E (TestClient, requieren app running)
│   ├── test_ops_e2e.py         # (viene de test_ops_v2.py)
│   ├── test_adversarial.py
│   ├── test_api_security.py
│   ├── test_adapters.py
│   └── test_mastery_integration.py
├── conftest.py
└── fixtures/          # Shared test data si hace falta
```

### 5.5.5 Reglas para la reescritura

1. **Usar `pytest.mark.parametrize`** agresivamente — si hay 5 tests que solo cambian el input, es un parametrize
2. **Un archivo = un dominio** — no `test_security_core` + `test_security_validation` + `test_security_hardened`
3. **Naming:** `test_{dominio}.py` en singular, no `test_{dominio}_v2` o `test_{dominio}_remaining`
4. **Fixtures compartidas** van en `conftest.py`, no duplicadas en cada archivo
5. **No testear implementación interna** — testear comportamiento público. Si un refactor rompe un test sin cambiar la API, el test era frágil
6. **Cada test debe tener un propósito claro** — si no puedes explicar en 1 frase qué regresión previene, elimínalo

### 5.5.6 Orden de ejecución

```
1. Eliminar tests/gptactions/ completo (0 riesgo, módulo muerto)
2. Eliminar tests/llm_security/ excepto input_sanitizer y output_validator
3. Migrar los 2 tests de llm_security a tests/unit/test_security_guards.py
4. Actualizar imports de repo_orchestrator en 4 archivos de tests/services/
5. Consolidar security: fusionar 17 archivos → 4
6. Deduplicar: provider_budget, model_router, economy_config
7. Mover archivos a estructura unit/ + integration/
8. Ejecutar pytest -x -q → verificar 100% pass
9. Eliminar subdirectorios vacíos
```

**Criterio Fase 5.5:**
- [ ] `find tests -name "test_*.py" | wc -l` → ≤35
- [ ] `ls tests/` → solo `unit/`, `integration/`, `conftest.py`, `fixtures/`
- [ ] `python -m pytest --co -q` → ~400-450 tests
- [ ] `python -m pytest -x -q` → 100% pass
- [ ] Zero archivos con `_v2`, `_remaining`, `_hardened` en el nombre
- [ ] Zero tests que importen de módulos eliminados

---

## FASE 6 — Frontend (Ejecutar UI_IMPROVEMENT_PLAN)

Esta fase es el documento separado `docs/UI_IMPROVEMENT_PLAN_2026-02-23.md` con sus 3 sub-fases propias. Resumen:

- **6.1** Bugs críticos: auth cookies, API_BASE, token leak, botones stub
- **6.2** Consistencia: idioma unificado, modelos dinámicos, exports muertos
- **6.3** UX: sidebar simplificado, chat colapsable, feedback de ejecución

**Criterio Fase 6:** Ver criterios de aceptación en `UI_IMPROVEMENT_PLAN_2026-02-23.md`

---

## FASE 7 — Polish Final [COMPLETADO]

### 7.1 README.md reescrito
```markdown
# GIMO — Gred In Multi-Agent Orchestrator

> Orquestador multiagente local con soporte para LLMs locales (Ollama) y cloud.

## Quickstart
1. `pip install -r requirements.txt`
2. `cp .env.example .env` → configurar token
3. `python -m uvicorn tools.gimo_server.main:app --port 9325`
4. `cd tools/orchestrator_ui && npm install && npm run dev`
5. Abrir http://localhost:5173

## Documentación
- [Arquitectura](docs/SYSTEM.md)
- [Instalación y Config](docs/SETUP.md)
- [API](docs/API.md)
- [Seguridad](docs/SECURITY.md)

## Tests
`python -m pytest -x -q`

## License
Propietario — Gred In Labs
```

### 7.2 pyproject.toml limpio
- Verificar que refleja las dependencias reales
- Eliminar dependencias de módulos eliminados

### 7.3 Crear CHANGELOG.md
```markdown
# Changelog

## [Unreleased]
- Refactor completo del repositorio (REPO_MASTERPLAN)
- Eliminados módulos legacy: gptactions_gateway, patch_validator, etc.
- Documentación consolidada de 67 → 8 archivos
- UI: fixes de auth, consistencia, UX

## [0.9.0] — 2026-02-23
- E2E funcional: plan → graph → approve → execute via Qwen
- MCP bridge operativo
- 648+ tests passing
```

### 7.4 Ejecutar tests finales
```bash
python -m pytest -x -q --tb=short
cd tools/orchestrator_ui && npx vitest run
```

---

## Orden de Ejecución

```
FASE 0   → Snapshot (CRÍTICO, hacer primero)
   ↓
FASE 1   → Purga de basura (5 min, zero riesgo)
   ↓
FASE 2   → Consolidar tools/ (30 min, riesgo medio — requiere migrar imports)
   ↓
FASE 3   → Consolidar scripts/ (10 min, bajo riesgo)
   ↓
FASE 4   → Consolidar docs/ (20 min, zero riesgo)
   ↓
FASE 5   → Higiene backend (15 min, bajo riesgo)
   ↓
FASE 5.5 → Rediseño test suite (648→~420 tests, 84→~35 archivos)
   ↓
FASE 6   → Frontend (UI_IMPROVEMENT_PLAN, varias horas)
   ↓
FASE 7   → Polish final (15 min)
```

**Dependencias críticas:**
- Fase 5.5 DEBE ir después de Fase 2 (eliminar tools/ legacy) y Fase 5 (limpiar imports)
- Los tests de módulos eliminados en Fase 2 se borran en 5.5, no antes (para no romper pytest entre fases)

## Criterio Global de Éxito

- [ ] `git branch -r` → solo `origin/main` + `origin/HEAD`
- [ ] `ls tools/` → solo `gimo_server/` y `orchestrator_ui/`
- [ ] `ls docs/*.md` → ≤8 archivos
- [ ] `ls *.md` (root) → solo `README.md`
- [ ] Zero archivos basura en root (no .json debug, no lock vacíos)
- [ ] Zero `__pycache__` en workspace
- [ ] Zero imports a módulos eliminados
- [ ] `python -m pytest -x -q` → 100% pass, ~400-450 tests
- [ ] `find tests -name "test_*.py" | wc -l` → ≤35 archivos
- [ ] Zero tests con `_v2`, `_remaining`, `_hardened` en el nombre
- [ ] Frontend sin bugs de auth, sin botones muertos, idioma unificado
- [ ] Un ingeniero nuevo puede entender el proyecto leyendo README + SYSTEM.md en <10 min

---

## Notas para Agentes

- **SIEMPRE ejecutar tests después de cada fase** — no avanzar si hay fallos
- **Fase 2 es la más delicada** — migrar imports de `repo_orchestrator` y `llm_security` requiere entender qué clases se usan realmente
- **No eliminar nada sin verificar** que no hay imports activos con `grep -rn`
- **El tag `v0.9-pre-refactor`** es el punto de rollback seguro
- **Commits atómicos por fase** — un commit por fase con mensaje descriptivo
- **Este documento se auto-depreca** cuando todas las checkboxes estén marcadas — en ese punto, moverlo a `docs/archive/`
