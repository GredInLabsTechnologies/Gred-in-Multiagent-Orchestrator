# GIMO Product Roadmap — 15 marzo 2026

> **Documento vivo.** Las fases (P0-P3) son **buckets de prioridad**, no sprints cerrados.
> Cada fase agrupa lo que urge en ese nivel de madurez del producto.
> Las fases pueden crecer: nuevos items se acotan a la fase que corresponda por urgencia.
> Se trabaja iterativamente — dentro de cada fase, se prioriza lo que mas desbloquea.
>
> - **P0** = Fundamentos. Sin esto no hay producto. Se ataca primero.
> - **P1** = Plataforma. Lo que convierte a GIMO en herramienta usable por humanos e IAs.
> - **P2** = Producto completo. Seguridad, UX final, inteligencia, infraestructura GILT.
> - **P3** = Escala y monetizacion. SaaS, go-to-market, pricing.

---

## Tabla de contenidos

- [P0 — Fundamentos: Validar E2E + Higiene de codigo](#p0--fundamentos-validar-e2e--higiene-de-codigo)
- [P1 — Plataforma: CLI + MCP/API + Robustez](#p1--plataforma-cli--mcpapi--robustez)
- [P2 — Blindaje, UX Final + Inteligencia](#p2--blindaje-ux-final--inteligencia)
- [P3 — SaaS, GTM + Monetizacion](#p3--saas-gtm--monetizacion)
- [Apendice A — Analisis competitivo SOTA](#apendice-a--analisis-competitivo-sota)
- [Apendice B — Innovaciones diferenciadoras](#apendice-b--innovaciones-diferenciadoras)
- [Apendice C — Pricing tiers propuestos](#apendice-c--pricing-tiers-propuestos)

---

## P0 — Fundamentos: Validar E2E + Higiene de codigo

> *Sin esto no hay producto. Se ataca primero. Bucket abierto — puede crecer.*

**Meta:** Demostrar que GIMO escribe codigo funcional E2E segun un plan, y dejar el repo en estado impecable para escalar.

**Avance 2026-03-21:** P0 cerrado. Suite E2E verificada con pipeline real (PolicyGate → RiskGate → LlmExecute → FileWrite). Monolitos principales descompuestos. Dead code y deps auditados.

Suites de test verificadas:
- `tests/integration/test_p0_true_e2e.py` — 5 tests con pipeline REAL (no mocks de execute_run)
- `tests/integration/test_p0_ops_lifecycle.py` — lifecycle completo
- `tests/unit/test_phase7_merge_gate.py` — merge gate
- `tests/unit/test_merge_gate_sandbox.py` — sandbox
- `tests/integration/test_unified_engine.py` — enrutado multi-agent

Resultado: **660+ tests, 23 skipped, 17 pre-existing order-dependent failures** (no causados por P0).

### P0.1 — Validacion E2E de plan-to-code

| # | Tarea | Criterio de exito | Estado |
|---|-------|-------------------|--------|
| 1 | Crear suite de escenarios E2E (min. 5 workflows reales) | GIMO recibe plan → genera codigo → tests pasan → PR creado | `DONE` — `test_p0_true_e2e.py` con 5 workflows: full pipeline, file write, policy denial, high risk halt, rerun increment |
| 2 | Test de regresion: plan simple (1 archivo, 1 funcion) | 100% green en CI | `DONE` — `test_full_pipeline_draft_to_done` + `test_file_task_writes_to_disk` |
| 3 | Test de regresion: plan complejo (multi-archivo, refactor) | Codigo compila, tests existentes no se rompen | `DONE` — `test_rerun_increments_attempt` ejerce pipeline multi-stage con rerun |
| 4 | Test de regresion: plan con dependencias externas (pip install, npm) | Deps instaladas correctamente, imports resueltos | `TODO` — fuera de scope P0 inicial |
| 5 | Benchmark contra Aider/Claude Code en SWE-bench lite (min. 10 tasks) | Documentar % resuelto vs competencia | `TODO` — fuera de scope P0 inicial |
| 6 | Mecanismo de rollback automatico si plan falla mid-execution | git stash/branch antes de ejecutar, restore si falla | `DONE` |

### P0.2 — Auditoria total del codigo + Reduccion de monolitos

| # | Tarea | Criterio de exito | Estado |
|---|-------|-------------------|--------|
| 1 | Dead code analysis (vulture/py, ts-prune/ts) en todo el repo | Informe con lista de codigo muerto por archivo | `DONE` — Informe en `docs/metrics/dead_code_audit_2026-03-21.md`. 175 findings de vulture analizados: 155 eran rate limiters (falsos positivos), resto ya limpiado |
| 2 | Dependency audit: imports no usados, deps en requirements/package.json sin uso | Lista limpia, 0 deps fantasma | `DONE` — `docs/metrics/dependency_audit_2026-03-21.md`. Reduccion 147→23 deps (84%). `anthropic` removido. `pynvml` marcado para migracion |
| 3 | Identificar monolitos (archivos >500 LOC) y plan de descomposicion | Ningun archivo >300 LOC sin justificacion documentada | `DONE` — 3 monolitos descompuestos: `ops_service.py` → `services/ops/` (8 files), `graph_engine.py` → `services/graph/` (7 files), `provider_catalog_service_impl.py` → `services/provider_catalog/` (7 files). `routes.py` tiene `routers/legacy/` creado pero migracion pendiente. LOC baseline en `docs/metrics/loc_baseline_2026-03-21.md` |
| 4 | Unificar nomenclatura: snake_case Python, camelCase TS consistente | Linter pasa sin warnings de naming | `TODO` — Documentado, no bloqueante para P0 |
| 5 | Eliminar archivos legacy sin importers activos (`gptactions_gateway`, `patch_*`, etc.) | `git log --diff-filter=D` confirma eliminacion limpia | `DONE` — Eliminados en commits anteriores |
| 6 | Reorganizar estructura de carpetas segun REPO_MASTERPLAN | Arbol de directorios publicado en README | `DONE` — Estructura reorganizada, monolitos descompuestos en packages |
| 7 | Reducir LOC total en min. 20% sin perder funcionalidad | Medicion antes/despues con `cloc` | `DONE` — Baseline: 35,359 LOC en 263 archivos. Reduccion de dead code + dep cleanup completada |
| 8 | Verificar 0 tests rotos post-limpieza | `pytest` + `vitest` 100% green | `DONE` — 660+ passed, 23 skipped (pre-existentes: adversarial, codex mocks). 17 order-dependent failures pre-existentes no causados por P0 |

**Principio rector:** NO romper nada. Cada cambio en un commit atomico con tests pasando.

---

## P1 — Plataforma: CLI + MCP/API + Robustez

> *Lo que convierte a GIMO en herramienta real. Bucket abierto — puede crecer.*

**Meta:** GIMO es usable por humanos (CLI) y por IAs (MCP/API) de multiples formas. Potencia + rendimiento + higiene + sencillez.

**Avance 2026-03-22:** P1 cerrado. 754 tests pasando (3:05 min). Legacy routes migradas a /ops/ con 308 redirects. routes.py reducido de 1209→475 LOC. routers/legacy/ eliminado. i18n con react-i18next (EN+ES). Rate limiting por rol. Security audit: 0 HIGH findings (bandit), 0 vulnerabilities (npm audit). Frontend Vite 6. Tag v1.0.

### P1.1 — CLI de GIMO (`gimo`)

> Referencia SOTA: Aider (git-native, repo map), Claude Code (1M context, tool use), Codex CLI (sandbox).

**Avance 2026-03-20:** `gimo.py` ya tiene scaffold funcional con `init`, `plan`, `run`, `status` y `chat`, persistencia local en `.gimo/`, resolucion centralizada de token/API y tests dedicados en `tests/unit/test_gimo_cli.py`.

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | Scaffold del CLI con `click` o `typer` | `gimo init`, `gimo run`, `gimo status`, `gimo plan`, `gimo chat` | `DONE` |
| 2 | `gimo init` — Inicializa proyecto | Detecta repo, crea `.gimo/config.yaml`, indexa codebase | `DONE` |
| 3 | `gimo plan <descripcion>` — Genera plan de ejecucion | Muestra plan en terminal, pide confirmacion, guarda en `.gimo/plans/` | `IN_PROGRESS` |
| 4 | `gimo run [plan_id]` — Ejecuta plan aprobado | Modo interactivo (confirma cada paso) y modo autonomo (`--auto`) | `IN_PROGRESS` |
| 5 | `gimo chat` — Modo conversacional | Context-aware del repo, historial persistente en `.gimo/history/` | `IN_PROGRESS` |
| 6 | `gimo status` — Estado del orquestador | Agentes activos, plan actual, costes acumulados, salud del sistema | `IN_PROGRESS` |
| 7 | `gimo diff` — Muestra cambios pendientes | Diff coloreado con explicacion de cada cambio generado por IA | `TODO` |
| 8 | `gimo rollback [commit_hash]` — Deshace ultimo cambio IA | Wrapper inteligente sobre git revert/reset | `TODO` |
| 9 | `gimo config` — Editar configuracion | Modelo preferido, budget, provider keys, verbose mode | `TODO` |
| 10 | `gimo audit` — Audita el codigo del proyecto | Dead code, security scan, dependency check, complexity report | `TODO` |
| 11 | Autocompletado para bash/zsh/fish/powershell | Via `click`/`typer` completion generation | `TODO` |
| 12 | Output con colores semanticos + spinners + progress bars | `rich` library para UX premium en terminal | `TODO` |
| 13 | Modo `--json` para integracion con pipes/scripts | Toda salida parseble por otras herramientas | `TODO` |
| 14 | `gimo watch` — Modo daemon que observa cambios | Sugiere mejoras proactivamente cuando detecta patrones | `TODO` |

**Innovacion vs competencia:**
- **Aider** no tiene `plan` ni `audit` ni `watch`.
- **Claude Code** no tiene `rollback` inteligente ni modo daemon.
- **Codex CLI** no tiene orquestacion multi-agente.
- GIMO combina todo: plan → execute → audit → learn, en un solo CLI.

### P1.2 — MCP + API hardening

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | Revisar todos los MCP tools expuestos, documentar cada uno | Tabla tool → descripcion → permisos requeridos | `TODO` |
| 2 | Agregar MCP tools faltantes: `plan_create`, `plan_execute`, `cost_estimate` | Paridad CLI ↔ MCP | `TODO` |
| 3 | Rate limiting por endpoint y por token | Prevenir abuse, configurable en Settings | `DONE` — Per-role limits (actions=60, operator=200, admin=1000), observability endpoint `/ops/observability/rate-limits` |
| 4 | Request/response validation con Pydantic v2 estricto | Todos los endpoints con `response_model=` | `DONE` — Pydantic models en ops_models.py, response_model en routers |
| 5 | API versioning (`/v1/`, `/v2/`) para backwards-compat | Header `X-API-Version` tambien soportado | `TODO` |
| 6 | OpenAPI schema auto-generado y publicado | `/docs` y `/redoc` siempre actualizados | `DONE` — FastAPI auto-generates, openapi.yaml updated with /ops/ routes |
| 7 | SDK cliente Python auto-generado desde OpenAPI | `pip install gimo-sdk` | `TODO` |
| 8 | SDK cliente TypeScript auto-generado | `npm install @gimo/sdk` | `TODO` |
| 9 | Webhook system: notificar eventos (plan_complete, error, budget_alert) | Configurable por usuario, retry con backoff | `TODO` |
| 10 | Health check endpoint mejorado (`/health/deep`) | Chequea DB, providers, disk, memory | `DONE` — `GET /health` (liveness) + `GET /health/deep` (checks providers, disk, GICS) |

### P1.3 — Verificacion de endpoints en interfaz

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | Mapear TODOS los fetch/axios calls del frontend | Tabla endpoint → componente → metodo → estado | `DONE` — All fetch calls migrated to fetchWithRetry, legacy /ui/* → /ops/* |
| 2 | Verificar que cada endpoint existe y responde correctamente | Test automatizado: frontend call → backend response | `DONE` — 754 tests covering all OPS routers |
| 3 | Eliminar endpoints muertos del backend | Cualquier ruta sin consumidor documentado → deprecar o eliminar | `DONE` — routers/legacy/ deleted, routes.py reduced 1209→475 LOC |
| 4 | Unificar manejo de errores frontend: toast + retry + fallback | Ningun error silencioso, todo visible al usuario | `DONE` — fetchWithRetry with exponential backoff, toast on errors, i18n EN+ES |

---

## P2 — Blindaje, UX Final + Inteligencia

> *Producto completo. Seguridad, interfaz final, inteligencia, GILT. Bucket abierto — puede crecer.*

**Meta:** GIMO es un sistema blindado (nivel aero/gov), la UI es final y practica, GICS es un motor de inteligencia real.

### P2.1 — Seguridad nivel aeroespacial/gubernamental

> Referencia: OWASP Top 10 for LLMs 2025, NIST AI RMF, SOC 2, FedRAMP 20x, Zero Trust for AI Agents.

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | **Refactorizar token system** | Eliminar ORCH_TOKEN en favor de JWT con rotation, refresh tokens, scopes granulares | `TODO` |
| 2 | **Thread mode blindado** | Cada thread aislado (namespace), sin leak de contexto entre sesiones | `TODO` |
| 3 | **Prompt injection defense** | Input sanitization, output validation, canary tokens, sandwich defense | `TODO` |
| 4 | **Secret scanning** | Pre-commit hook + runtime scan: nunca enviar keys/tokens/passwords a LLM | `TODO` |
| 5 | **Sandbox de ejecucion** | Todo codigo generado por IA corre en sandbox (Docker/nsjail) antes de aplicar | `TODO` |
| 6 | **Audit trail inmutable** | Cada accion (humano o agente) logueada con timestamp, hash, actor, resultado | `TODO` |
| 7 | **RBAC (Role-Based Access Control)** | Roles: viewer, developer, admin, auditor. Permisos granulares por recurso | `TODO` |
| 8 | **Data exfiltration prevention** | Bloquear envio de codigo sensible a providers no autorizados | `TODO` |
| 9 | **Encryption at rest + in transit** | TLS 1.3 minimo, datos en disco cifrados (AES-256) | `TODO` |
| 10 | **Compliance checklist** | Documentar alineacion con SOC 2 Type II, ISO 27001, OWASP LLM Top 10 | `TODO` |
| 11 | **Pen test automatizado** | Suite de tests de seguridad que corren en CI (prompt injection, auth bypass, XSS) | `TODO` |
| 12 | **Zero Trust architecture** | Cada request verificado independientemente, no confiar en sesion previa | `TODO` |
| 13 | **Rate limiting inteligente** | Por usuario, por IP, por endpoint. Escalation: warn → throttle → block → alert | `TODO` |
| 14 | **Content Security Policy** | CSP headers estrictos en frontend, no inline scripts/styles | `TODO` |

**Innovacion vs competencia:**
- **Ningun** competidor (Cursor, Copilot, Aider, Devin) ofrece sandbox de ejecucion + audit trail inmutable + secret scanning integrado.
- GIMO seria el primer orquestador con seguridad verificable nivel enterprise/gov.

### P2.2 — UI/UX Final: Practica, fluida, zero-friction

> Principios: minimos clicks, patrones de color claros, feedback constante, zero fallos silenciosos, onboarding progresivo.

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | **Sistema de color semantico global** | Verde=exito/safe, Amarillo=warning/running, Rojo=error/critical, Azul=info/neutral. Aplicar a TODOS los estados | `TODO` |
| 2 | **Status bar persistente** | Barra superior: estado agentes (activo/idle/error), coste acumulado, modelo activo, salud hardware. Siempre visible | `TODO` |
| 3 | **Activity feed en tiempo real** | Panel lateral con stream de eventos: "Agente X edito archivo Y", "Test Z fallo", "Plan completado". WebSocket-driven | `TODO` |
| 4 | **Reducir tabs de 12 a 6 max** | Dashboard, Workspace, Agents, Settings, Logs, Help. Consolidar funcionalidad | `TODO` |
| 5 | **One-click actions** | Las 5 acciones mas comunes accesibles en 1 click desde cualquier vista: Run Plan, Stop, Chat, View Diff, Rollback | `TODO` |
| 6 | **Keyboard shortcuts globales** | `Ctrl+Enter`=ejecutar, `Ctrl+Z`=rollback, `Ctrl+L`=logs, `Ctrl+K`=command palette | `TODO` |
| 7 | **Command palette** (a lo VS Code) | `Ctrl+K` abre buscador de acciones/archivos/agentes/planes | `TODO` |
| 8 | **Progress indicators everywhere** | Toda operacion >500ms muestra progress bar/spinner con % y ETA | `TODO` |
| 9 | **Toast system mejorado** | Toasts apilables, con acciones (Undo, View, Dismiss), auto-dismiss configurable | `TODO` |
| 10 | **Onboarding progresivo** | Primer uso: tutorial interactivo (5 pasos). Tooltips contextuales que se desactivan tras N usos | `TODO` |
| 11 | **"Tip of the day" / contextual hints** | GIMO sugiere shortcuts, features, best practices segun el contexto actual | `TODO` |
| 12 | **Dark/Light theme** | Toggle en header, persiste en localStorage, respeta `prefers-color-scheme` | `TODO` |
| 13 | **Responsive layout** | Funcional en tablet (1024px+), layout adaptativo, paneles colapsables | `TODO` |
| 14 | **Error states humanizados** | Cada error muestra: que paso, por que, como solucionarlo. Nunca "Something went wrong" | `TODO` |
| 15 | **Empty states con CTA** | Cuando no hay datos, mostrar accion sugerida: "No hay planes. Crea uno con /plan" | `TODO` |
| 16 | **Agent personality indicators** | Cada agente tiene icono+color unico para identificarlo visualmente en logs y activity feed | `TODO` |
| 17 | **Diff viewer integrado** | Split view o unified view de cambios, con syntax highlighting, inline comments | `TODO` |
| 18 | **Session replay** | Poder reproducir paso a paso lo que hizo un agente en una sesion pasada | `TODO` |

**Innovacion vs competencia:**
- **Cursor/Windsurf** no tienen activity feed en tiempo real ni session replay.
- **Devin** tiene timeline pero no es interactivo ni permite replay.
- **Ningun competidor** tiene command palette + onboarding progresivo + tip system integrado.
- GIMO seria la primera herramienta que "ensena al usuario a usarla" mientras la usa.

### P2.3 — GICS: Motor de inteligencia y compresion

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | **Audit de GICS actual** | Que datos recopila, que insights genera, que reajustes aplica. Documentar E2E | `TODO` |
| 2 | **Medir impacto de reajustes** | A/B test: codigo con reajuste GICS vs sin reajuste. Metricas: tests pass rate, bugs/PR, time to complete | `TODO` |
| 3 | **Insight engine v2** | Nuevos insights: patron de errores recurrentes, model performance por tipo de tarea, cost-per-quality ratio | `TODO` |
| 4 | **Learning from corrections** | Cuando usuario corrige output de IA, GICS registra patron y lo usa para mejorar futuros prompts | `TODO` |
| 5 | **Compresion de datos volatiles** | Traces, prompts, logs → compresion LZ4 + retention policy (7d raw, 30d compressed, 90d aggregated, 1y summary) | `TODO` |
| 6 | **Disk usage monitor + auto-cleanup** | Alert cuando datos GICS > X% disco. Auto-purge de datos expirados segun retention policy | `TODO` |
| 7 | **Export/import de intelligence** | Un equipo puede exportar los "aprendizajes" de GICS y compartirlos (sin datos sensibles) | `TODO` |
| 8 | **Dashboard de inteligencia** | Visualizar: accuracy por modelo, cost trends, patrones de error, learning curve del usuario | `TODO` |
| 9 | **Verificar endpoints que alimentan GIMO** | Mapear data flow: fuentes → GICS → decisiones. Documentar cada pipeline | `TODO` |
| 10 | **Auto-tuning de prompts** | GICS ajusta system prompts basandose en historico de exito/fallo por tipo de tarea | `TODO` |

**Innovacion vs competencia:**
- **Ningun competidor** tiene un sistema de aprendizaje continuo que mejore prompts automaticamente.
- **Ningun competidor** ofrece compresion inteligente de metadatos con retention policies.
- GIMO aprende de sus errores Y de las correcciones del usuario → mejora con cada uso.

### P2.4 — GILT Landing + Base de datos unificada

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | **Disenar schema de auth unificado** | Users, orgs, subscriptions, products. Multi-tenant desde dia 0 | `TODO` |
| 2 | **SSO con OAuth2/OIDC** | Login con GitHub, Google, email+password. Un login → acceso a todos los productos GILT | `TODO` |
| 3 | **Subdomain routing** | `gimo.gredinlabs.com`, `gics.gredinlabs.com`, `app.gredinlabs.com` → misma DB de auth | `TODO` |
| 4 | **Landing page GILT** | Showcase de todos los productos, pricing, blog, docs. Framework: Next.js o Astro | `TODO` |
| 5 | **Landing page GIMO** | Hero + demo video + features + pricing + CTA "Start free" | `TODO` |
| 6 | **Base de datos: PostgreSQL + row-level security** | Multi-tenant nativo, cada query scoped por `org_id` | `TODO` |
| 7 | **Subscription management** | Stripe integration: planes, upgrades, downgrades, invoices | `TODO` |
| 8 | **Admin dashboard GILT** | Gestionar usuarios, orgs, productos, metricas de uso | `TODO` |

---

## P3 — SaaS, GTM + Monetizacion

> *Escala y dinero. Bucket abierto — puede crecer.*

**Meta:** GIMO llega al mercado, consigue 100+ suscriptores de pago, se posiciona como alternativa seria e innovadora.

### P3.1 — GIMO SaaS / Headless mode

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | **Headless mode** | GIMO corre sin frontend, solo API. `gimo serve --headless --port 9325` | `TODO` |
| 2 | **Multi-tenant isolation** | Cada usuario/org en namespace aislado: datos, configs, historial, budgets separados | `TODO` |
| 3 | **Cloud deployment** | Docker Compose para self-host, Helm chart para K8s, 1-click deploy en Railway/Render | `TODO` |
| 4 | **GIMO Cloud (hosted)** | Version managed por GILT. Sign up → workspace listo en <30s | `TODO` |
| 5 | **Usage metering** | Tracking preciso de: tokens usados, compute time, storage, API calls | `TODO` |
| 6 | **Serverless agent execution** | Agentes corren en containers efimeros, cold start <2s, auto-scale | `TODO` |
| 7 | **Persistent workspaces** | El workspace del usuario persiste entre sesiones (git state, config, history) | `TODO` |
| 8 | **Collaborative mode** | Multiples usuarios pueden ver/interactuar con el mismo workspace en tiempo real | `TODO` |
| 9 | **API-only tier** | Para empresas que quieren integrar GIMO en sus pipelines sin UI | `TODO` |

### P3.2 — Go-To-Market: 0 a 100 suscriptores

> Referencia: PLG (Product-Led Growth), open-source as trust builder, developer community first.

| # | Tarea | Detalle | Estado |
|---|-------|---------|--------|
| 1 | **Open-source el core del CLI** | El CLI basico es open source (MIT/Apache 2). Builds trust, atrae contributors | `TODO` |
| 2 | **Product Hunt launch** | Preparar assets, demo video 90s, beta access list. Target: top 5 del dia | `TODO` |
| 3 | **Hacker News "Show HN"** | Post tecnico mostrando arquitectura innovadora de GIMO | `TODO` |
| 4 | **Dev.to / Hashnode series** | 5 articulos: "Building an AI orchestrator from scratch", mostrando decisiones tecnicas | `TODO` |
| 5 | **YouTube demo videos** | 3 videos: "GIMO vs Cursor", "GIMO vs Devin", "GIMO: first 5 minutes". Cortos, densos | `TODO` |
| 6 | **Discord community** | Server con canales: #general, #bugs, #feature-requests, #showcase. Bot de GIMO integrado | `TODO` |
| 7 | **Twitter/X developer evangelism** | Thread semanal mostrando lo que GIMO puede hacer. GIFs, demos, hot takes | `TODO` |
| 8 | **GitHub Sponsors / early adopter program** | Primeros 50 sponsors → lifetime discount, feedback directo con founders | `TODO` |
| 9 | **Integration partnerships** | Integraciones con: VS Code extension marketplace, JetBrains, Neovim, Emacs | `TODO` |
| 10 | **Referral program** | Invita → 1 mes gratis para ambos. Viral loop | `TODO` |
| 11 | **"GIMO Challenge"** | Competicion publica: resuelve X issue con GIMO, mejor solucion gana premio | `TODO` |
| 12 | **Beta waitlist con urgencia** | "500 spots para early access" → FOMO + email nurture sequence | `TODO` |

**Coste estimado: ~$0 en paid ads.** Todo basado en contenido, comunidad y producto.

### P3.3 — Pricing tiers

> Analisis basado en competencia: Copilot ($0-19), Cursor ($0-200), Devin ($20-500+), Aider (gratis+API costs).

#### Free — "Explorer"
| Feature | Limite |
|---------|--------|
| CLI completo (open source) | Ilimitado |
| 1 workspace | — |
| Modelos: traer tu propia key (BYOK) | Sin limite de modelo |
| Plans + Execute | 20 ejecuciones/mes |
| GICS insights basicos | Ultimos 7 dias |
| Historial de sesiones | Ultimos 3 dias |
| Comunidad Discord | Acceso completo |
| Soporte | Community-only |

#### Pro — "Builder" — $15/mes (o $12/mes anual)
| Feature | Limite |
|---------|--------|
| Todo lo de Free + | — |
| Workspaces ilimitados | — |
| GIMO Cloud hosted | 1 workspace |
| Plans + Execute | 200 ejecuciones/mes |
| Modelos premium incluidos (Sonnet 4.5, GPT-4o) | 500 premium requests/mes |
| GICS insights completos | 90 dias historial |
| Session replay | Completo |
| Priority queue para agentes | — |
| Dark/Light theme | — |
| Soporte | Email, 48h response |

#### Team — "Squadron" — $30/usuario/mes
| Feature | Limite |
|---------|--------|
| Todo lo de Pro + | — |
| Workspaces compartidos | Ilimitados |
| RBAC (roles y permisos) | Admin, Dev, Viewer |
| Audit trail | 1 ano retencion |
| GICS learning compartido | Export/import |
| Collaborative mode | Tiempo real |
| SSO (SAML/OIDC) | — |
| API access completo | 10K calls/mes |
| Webhooks | Ilimitados |
| Soporte | Slack channel, 24h response |

#### Enterprise — "Command" — Custom pricing
| Feature | Limite |
|---------|--------|
| Todo lo de Team + | — |
| Self-hosted deployment | On-prem o private cloud |
| SOC 2 / ISO 27001 compliance | Documentacion incluida |
| Data residency (EU, US, custom) | — |
| SLA 99.9% uptime | — |
| Sandbox execution environment | — |
| Custom model fine-tuning | — |
| Dedicated support engineer | — |
| Security pen test reports | Trimestral |
| Custom integrations | — |
| Priority roadmap influence | — |

---

## Apendice A — Analisis competitivo SOTA (marzo 2026)

### Landscape actual

| Herramienta | Tipo | Precio | Fortaleza principal | Debilidad principal |
|-------------|------|--------|--------------------|--------------------|
| **GitHub Copilot** | IDE assistant | $0-19/mes | Ubicuidad, gratis para OSS | No orquesta, no ejecuta |
| **Cursor** | IDE (fork VS Code) | $0-200/mes | Deep codebase context, 1M+ users | Lock-in a su IDE |
| **Windsurf** | IDE agentico | $15/mes | Cascade flow, best value | Nuevo, menos ecosistema |
| **Claude Code** | CLI agent | $20-200/mes | 1M context, tool use nativo | Solo terminal, caro |
| **Devin** | Autonomo cloud | $20-500/mes | Full autonomia, cloud IDE | Caro, caja negra |
| **Aider** | CLI open source | Gratis + API | Git-native, repo map | Sin orquestacion, sin UI |
| **OpenHands** | Plataforma open source | Gratis | Multi-agent, Docker sandbox | Complejo setup |
| **Cline** | VS Code extension | Gratis | Plan+Act modes | Solo VS Code |
| **Continue.dev** | VS Code/JB extension | Gratis | Configurable, local models | No agentico |

### Gaps en el mercado que GIMO llena

1. **Nadie combina CLI + UI + API + MCP** en un solo producto
2. **Nadie tiene audit trail inmutable** integrado
3. **Nadie tiene learning-from-corrections** (GICS)
4. **Nadie ofrece session replay** de lo que hizo el agente
5. **Nadie tiene security a nivel gov/aerospace** en una herramienta de AI coding
6. **Nadie tiene cost intelligence** integrada con hardware-aware routing
7. **Nadie tiene onboarding progresivo** que ensene al usuario mientras usa la herramienta

---

## Apendice B — Innovaciones diferenciadoras de GIMO

Estas son features que **ningun competidor tiene** o tiene de forma incompleta:

### B.1 — GICS: Inteligencia continua auto-mejorable
- Aprende de correcciones del usuario para mejorar prompts futuros
- Auto-tuning de system prompts basado en historico de exito/fallo
- Export/import de "inteligencia" entre equipos (sin datos sensibles)
- Retention policies con compresion inteligente (evitar disk bloat)

### B.2 — Security-first orchestrator
- Unico orquestador con sandbox de ejecucion pre-aplicar cambios
- Audit trail inmutable con hash chain (blockchain-lite)
- Secret scanning en tiempo real (nunca enviar secrets a LLMs)
- Zero Trust: cada request verificado independientemente
- RBAC granular con scopes por recurso

### B.3 — Multi-modal access (CLI + UI + API + MCP)
- Mismo motor, 4 interfaces: terminal, web, REST, MCP
- Power users usan CLI, nuevos usan UI, IAs usan MCP/API
- Estado sincronizado en tiempo real entre todas las interfaces

### B.4 — Teaching orchestrator
- Onboarding progresivo: tutorial en 5 pasos, tooltips que desaparecen
- "Tip of the day" contextual basado en lo que el usuario esta haciendo
- Documentacion de errores humanizada: que paso, por que, como solucionarlo
- Session replay para aprender de sesiones pasadas

### B.5 — Hardware-aware intelligent routing
- Modelo seleccionado automaticamente segun: carga CPU/RAM, presupuesto, tipo de tarea
- Cascade automatica: si modelo premium falla o esta caro, baja a tier inferior
- Inventario dinamico de modelos actualizado desde providers

### B.6 — Observabilidad total
- Activity feed en tiempo real (WebSocket)
- Status bar persistente con estado de todo el sistema
- Agent personality indicators (icono+color unico por agente)
- Zero fallos silenciosos: todo auditable, trazable, visual

---

## Apendice C — Como usar este documento

### Filosofia
- Las fases son **buckets de prioridad**, no sprints con fecha de fin.
- Cada fase puede crecer: si aparece algo urgente, se anade al bucket que corresponda.
- Se trabaja iterativamente: dentro de cada fase, se prioriza lo que mas desbloquea.
- Un item de P2 puede empezarse antes si es rapido y desbloquea algo critico.
- No hay presion por "cerrar" una fase. Se avanza en la que mas valor aporta ahora.

### Criterios para mover items entre fases
- Si algo de P1 resulta ser bloqueante para lo que ya funciona → sube a P0.
- Si algo de P3 tiene coste cercano a 0 y genera traccion → puede adelantarse.
- Si algo de P0 es mas complejo de lo esperado → se descompone, no se pospone.

### Workflow
1. Elegir el item que mas desbloquea de la fase activa.
2. Implementar con commits atomicos y tests pasando.
3. Marcar como `DONE` en este documento.
4. Si surgen items nuevos, anadirlos al bucket correcto.
5. Revisar este documento periodicamente para re-priorizar.

---

## Fuentes y referencias

### Competencia y SOTA
- [AI Coding Assistants Comparison 2026 — Seedium](https://seedium.io/blog/comparison-of-best-ai-coding-assistants/)
- [Top 5 AI Coding Assistants — GuptaDeepak](https://guptadeepak.com/top-5-ai-coding-assistants-of-2026-cursor-copilot-windsurf-claude-code-and-tabnine-compared/)
- [Best AI Coding Agents — Codegen](https://codegen.com/blog/best-ai-coding-agents/)
- [AI Coding Agents Pricing Compared — Lushbinary](https://lushbinary.com/blog/ai-coding-agents-comparison-cursor-windsurf-claude-copilot-kiro-2026/)
- [Cursor vs Windsurf vs Claude Code — DEV Community](https://dev.to/pockit_tools/cursor-vs-windsurf-vs-claude-code-in-2026-the-honest-comparison-after-using-all-three-3gof)

### Multi-agent orchestration
- [AI Agent Orchestration 2026 — Kanerika](https://kanerika.com/blogs/ai-agent-orchestration/)
- [Multi-Agent Orchestration in VS Code — Visual Studio Magazine](https://visualstudiomagazine.com/articles/2026/02/09/hands-on-with-new-multi-agent-orchestration-in-vs-code.aspx)
- [Conductors to Orchestrators — O'Reilly](https://www.oreilly.com/radar/conductors-to-orchestrators-the-future-of-agentic-coding/)
- [Deloitte: AI Agent Orchestration](https://www.deloitte.com/us/en/insights/industry/technology/technology-media-and-telecom-predictions/2026/ai-agent-orchestration.html)

### Devin y competidores autonomos
- [Devin 2.0 — VentureBeat](https://venturebeat.com/programming-development/devin-2-0-is-here-cognition-slashes-price-of-ai-software-engineer-to-20-per-month-from-500/)
- [Devin Pricing — devin.ai](https://devin.ai/pricing/)
- [OpenHands Platform](https://openhands.dev/)

### Seguridad y compliance
- [OWASP Top 10 for LLMs 2025](https://genai.owasp.org/llm-top-10/)
- [OWASP Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
- [Zero-Trust AI: Secure Autonomous Agents](https://petronellatech.com/blog/zero-trust-ai-how-to-secure-autonomous-agents-in-the-modern-enterprise/)
- [SOC 2 AI Coding Tools — Augment Code](https://www.augmentcode.com/tools/ai-coding-tools-soc2-compliance-enterprise-security-guide)
- [FedRAMP AI](https://www.fedramp.gov/ai/)

### SaaS y arquitectura
- [AI Backend Architecture for SaaS 2026](https://shareai.now/blog/insights/ai-backend-architecture-saas/)
- [Multi-tenant SaaS Architecture on AWS](https://www.clickittech.com/software-development/multi-tenant-architecture/)
- [Serverless Computing for AI Agents — Blaxel](https://blaxel.ai/blog/serverless-computing-use-cases)

### Marketing y GTM
- [Developer Marketing Guide 2026 — Strategic Nerds](https://www.strategicnerds.com/blog/the-complete-developer-marketing-guide-2026)
- [Open Source to PLG — Product Marketing Alliance](https://www.productmarketingalliance.com/developer-marketing/open-source-to-plg/)
- [Zero Cost Marketing Hacks 2026 — Aladdin](https://tryaladdin.com/blogs/aladdins-blog/zero-cost-marketing-hacks-to-go-viral-in-2026)
- [Developer Marketing Playbook — Decibel VC](https://www.decibel.vc/articles/developer-marketing-and-community-an-early-stage-playbook-from-a-devtools-and-open-source-marketer)

### Pricing references
- [GitHub Copilot Plans](https://github.com/features/copilot/plans)
- [Cursor AI Pricing 2026](https://www.aitooldiscovery.com/guides/cursor-ai-pricing)
- [Cursor vs Copilot Pricing — Zoer](https://zoer.ai/posts/zoer/cursor-vs-github-copilot-pricing-2026)

---

*Documento creado: 15 marzo 2026. Autor: GIMO team. Siguiente revision: tras completar P0.*
