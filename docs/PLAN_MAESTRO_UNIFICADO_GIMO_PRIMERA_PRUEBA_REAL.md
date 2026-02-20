# PLAN MAESTRO UNIFICADO — GIMO (Providers + Licensing + GIOS/GICS + Primera Prueba Real)

Fecha: 2026-02-19  
Estado: Propuesto para ejecución inmediata

## 1) Objetivo ejecutivo

Dejar GIMO **listo para una primera prueba real end-to-end** desde el chat del orquestador, con:

- Configuración de provider dinámica y estable.
- Licensing operativo en modo `debug bypass` para no bloquear la validación técnica.
- Integración de capacidades útiles de GIOS sobre la base modular de GICS.
- Flujo de chat -> draft -> aprobación -> ejecución -> evidencia verificable.

## 2) Decisión de arquitectura (clave)

### Decisión
Integrar GIOS como **módulo cognitivo dentro del ecosistema GICS** (no como sistema paralelo independiente).

### Motivo
- GICS ya es modular, robusto y superior en storage/integridad/inteligencia estadística.
- GIOS aporta valor diferencial en intent detection, direct response y routing semántico.
- Evitamos duplicidad, reducimos deuda técnica y aceleramos la monetización.

### Diseño objetivo (alto nivel)
- **Capa Cognitiva (GIOS-in-GICS):** intent detector + security detector + direct response/tool-call.
- **Capa Inteligencia (GICS):** tracker/correlación/señales/confianza.
- **Capa Ejecución (GIMO):** OPS drafts/runs + provider routing + UI chat.

### Protocolo de aprobación multiagente (aplicable a todas las fases)
- Cada fase se marca con estado: `Pendiente` -> `En revisión` -> `Aprobada` / `Rechazada`.
- Ninguna fase pasa a la siguiente sin:
  - checklist operativo completo,
  - evidencia adjunta,
  - aprobación de **Responsable** y **Revisor**.
- La evidencia mínima por fase debe incluir: comandos ejecutados, resultado, y enlace/ruta de artefacto (`docs/evidence/...`).

### Política de dependencias (decisión técnica obligatoria)

**Objetivo:** reutilizar el valor de GIOS sin heredar acoplamiento legacy.

Reglas:
- **No** se permite dependencia runtime directa `GICS -> GIOS (legacy repo)`.
- **Sí** se permite extracción/refactor de capacidades de GIOS hacia módulos nuevos y limpios.
- GIMO depende de **interfaces (puertos)**, no de implementaciones legacy.
- Toda compatibilidad temporal irá detrás de feature flag con fecha de retiro.

Patrón de migración:
1. **Dependency Inversion (DIP):** definir contratos (`IntentEngine`, `SecurityGuard`, `DirectResponseEngine`).
2. **Strangler Fig:** enrutar primero por interfaz nueva, mantener bridge legacy temporal solo para no bloquear entregas.
3. **Retiro de puente:** cuando los tests/evidencias estén en verde, eliminar bridge y acoplamientos restantes.

Resultado esperado:
- Se desplazan **capacidades** (intent/security/direct-response), no se arrastran dependencias técnicas antiguas.

---

## 3) Estado actual consolidado (resumen)

### Plan Providers
- Funcionalidad core: alta (catálogo, install, validate, save active provider, UI dinámica).
- Gaps principales: tests de router HTTP, tests frontend avanzados, e2e, limpieza de tipos compartidos.

### Plan Licensing
- Server (LicenseGuard): alto y operativo.
- Web (GIMO WEB): alto y operativo.
- Gaps principales: cobertura de tests web/e2e, endurecimiento de dependencias y entorno.

---

## 4) Plan por fases (unificado)

## Fase 0 — Baseline y congelación de alcance (0.5 día)

### Entregables
- Branch de integración para primera prueba real.
- Snapshot de configuración inicial (`provider.json`, `.env`, endpoints de salud).

### Criterio de salida
- Build backend/frontend verde.
- Lanzador funcional.

### Checklist aprobable por agentes — Fase 0
- [ ] Crear rama de integración para primera prueba real.
- [ ] Generar snapshot inicial de `provider.json`, `.env` y salud (`/status`).
- [ ] Validar build backend en verde.
- [ ] Validar build frontend en verde.
- [ ] Verificar arranque con `GIMO_LAUNCHER.cmd`.
- [ ] Guardar evidencia en `docs/evidence/fase0_baseline.md`.
- [ ] Aprobación Responsable.
- [ ] Aprobación Revisor.

**Responsable sugerido:** `@agent-ops`  
**Revisor sugerido:** `@agent-qa`  
**Estado:** `Pendiente`

---

## Fase 1 — Cierre de gaps críticos en Providers y Licensing (1–2 días)

### 1.1 Providers (backend + frontend)
- Añadir tests HTTP para:
  - `GET /ops/connectors/{type}/models`
  - `POST /ops/connectors/{type}/models/install`
  - `POST /ops/connectors/{type}/validate`
- Añadir tests UI para:
  - cambio de provider type -> recarga de catálogo,
  - `Download & Use` con polling,
  - auth mode dinámico,
  - estado efectivo visible.
- Unificar tipos provider v2 en `tools/orchestrator_ui/src/types.ts` (evitar drift con hooks).

### 1.2 Licensing
- Confirmar dependencia directa de `jose` en `gimo-web/package.json` (si aún no está explícita).
- Completar `.env.example` web con variables faltantes de operación real.
- Validar `DEBUG + ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true` como modo oficial de prueba técnica.

### Criterio de salida
- Suite de pruebas mínima de providers/licensing en verde.
- Sin secretos en responses/logs.

### Checklist aprobable por agentes — Fase 1
- [ ] Añadir y pasar tests HTTP de catálogo/install/validate en OPS.
- [ ] Añadir y pasar tests UI de Provider Settings (catálogo, auth mode, polling, estado efectivo).
- [ ] Unificar tipos provider v2 en `tools/orchestrator_ui/src/types.ts`.
- [ ] Confirmar dependencia y entorno de licensing web (`jose`, `.env.example`).
- [ ] Ejecutar suite objetivo backend/frontend y capturar resultados.
- [ ] Verificar redacción de secretos en logs/respuestas.
- [ ] Guardar evidencia en `docs/evidence/fase1_providers_licensing.md`.
- [ ] Aprobación Responsable.
- [ ] Aprobación Revisor.

**Responsable sugerido:** `@agent-backend` + `@agent-frontend`  
**Revisor sugerido:** `@agent-qa`  
**Estado:** `Pendiente`

---

## Fase 2 — Integración GIOS útil dentro del stack GICS/GIMO (2–3 días)

### 2.1 Extraer solo lo valioso de GIOS
Migrar/adaptar:
- `IntentDetector` (semántico + aprendizaje incremental).
- `SecurityDetector` (bloqueo de prompt injection/jailbreak básico).
- Patrón `DirectResponse` / `toolCall` (bypass de LLM cuando aplica).

Descartar/no migrar en esta fase:
- Enrichers acoplados al dominio WoW.
- Flujo legacy no modular.

### 2.2 Contrato interno nuevo (GIMO)
Definir interfaz mínima:
- `detect_intent(input, context) -> intent`
- `can_bypass_llm(intent, context) -> bool`
- `build_execution_plan(intent, context) -> draft_payload`

### 2.3 Implementación sin acoplar legacy
- Crear contratos en módulo cognitivo (`IntentEngine`, `SecurityGuard`, `DirectResponseEngine`).
- Implementar `GiosBridgeAdapter` temporal solo si es necesario para transición.
- Activar bridge con feature flag (`COGNITIVE_GIOS_BRIDGE_ENABLED=true/false`).
- Planificar retiro del bridge al cerrar Fase 3.

### Criterio de salida
- Chat puede enrutar al menos 3 intents:
  - `CREATE_PLAN`
  - `ASK_STATUS`
  - `HELP`
- `SECURITY_BLOCK` funcional para inputs maliciosos obvios.

### Checklist aprobable por agentes — Fase 2
- [ ] Integrar `IntentDetector` adaptado al stack actual.
- [ ] Integrar `SecurityDetector` (bloqueo base de inyección/jailbreak).
- [ ] Integrar patrón `DirectResponse/toolCall` para bypass de LLM cuando aplique.
- [ ] Implementar contrato interno (`detect_intent`, `can_bypass_llm`, `build_execution_plan`).
- [ ] Verificar que no exista dependencia runtime directa `GICS -> GIOS legacy`.
- [ ] Si existe bridge temporal, dejarlo detrás de feature flag y con plan de retiro.
- [ ] Verificar en runtime intents `CREATE_PLAN`, `ASK_STATUS`, `HELP`.
- [ ] Verificar evento `SECURITY_BLOCK` con casos controlados.
- [ ] Guardar evidencia en `docs/evidence/fase2_gios_modular.md`.
- [ ] Aprobación Responsable.
- [ ] Aprobación Revisor.

**Responsable sugerido:** `@agent-cognitive`  
**Revisor sugerido:** `@agent-qa-security`  
**Estado:** `Pendiente`

---

## Fase 3 — Orquestación conversacional para primera prueba real (2 días)

### 3.1 Flujo objetivo
`Usuario en chat` -> `intención detectada` -> `draft estructurado` -> `approve` -> `run` -> `resultado + evidencia`.

### 3.2 Implementación mínima (MVP real)
- En `OrchestratorChat`, mantener UX actual pero añadir:
  - etiqueta de intención detectada,
  - estado de ejecución por pasos,
  - mensajes de error accionables.
- En backend OPS:
  - endpoint de generación mantiene compatibilidad,
  - enruta por intent antes de llamar LLM,
  - usa `DirectResponse` cuando no requiere LLM.

### Criterio de salida
- Al pedir “crea un plan X”, produce draft estructurado en formato esperado.
- Se puede aprobar y ejecutar sin intervención manual fuera del flujo.

### Checklist aprobable por agentes — Fase 3
- [ ] Añadir etiqueta de intención detectada en `OrchestratorChat`.
- [ ] Añadir estado de ejecución por pasos y errores accionables en UI.
- [ ] Enrutar por intent en backend antes de llamada LLM.
- [ ] Activar `DirectResponse` para intents de bypass.
- [ ] Probar flujo completo: chat -> draft -> approve -> run.
- [ ] Guardar evidencia en `docs/evidence/fase3_orquestacion_chat.md`.
- [ ] Aprobación Responsable.
- [ ] Aprobación Revisor.

**Responsable sugerido:** `@agent-orchestrator`  
**Revisor sugerido:** `@agent-qa-e2e`  
**Estado:** `Pendiente`

---

## Fase 4 — Preparación de primera prueba real con LLM Locales de Ollama (1 día)

> Nota operativa: se abandona el plan de usar Codex/OpenAI. Se utilizarán **LLMs locales a través de Ollama** para la primera prueba real, garantizando ejecución local y privada.

### 4.1 Preparación de entorno
- Activar `debug bypass` licensing:
  - `DEBUG=true`
  - `ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true`
- Configurar provider Ollama:
  - **Modo (recomendado):** `auth_mode=local` (o equivalente para servidor local).
  - Verificar que el servidor de Ollama esté en ejecución (`http://localhost:11434` o similar).
  - Asegurar la descarga previa del modelo a probar (ej. `llama3` o `mistral`).

### 4.2 Runbook de prueba real (requiere intervención humana)
1. Iniciar servidor Ollama localmente.
2. Lanzar GIMO (`GIMO_LAUNCHER.cmd`).
3. Verificar backend `/status` y UI cargada.
4. En Provider Settings:
   - seleccionar Ollama (Local LLM),
   - validar conexión al host local,
   - fijar modelo efectivo.
5. En Orchestrator Chat:
   - prompt de prueba: “Crea un plan técnico de 5 tareas para X con riesgos y DoD”.
6. Aprobar draft y ejecutar run.
7. Guardar evidencia:
   - draft generado,
   - run logs,
   - estado provider efectivo,
   - métricas básicas (latencia, errores, reintentos).

### Criterio de salida
- 1 ejecución completa e2e exitosa (chat -> draft -> run -> resultado).
- Evidencia persistida en docs/evidence.

### Checklist aprobable por agentes — Fase 4
- [ ] Configurar `DEBUG=true` y `ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true`.
- [ ] Verificar que Ollama está corriendo y el modelo descargado.
- [ ] Seleccionar provider Ollama y validar conexión en Provider Settings.
- [ ] Ejecutar runbook real desde chat con prompt de prueba (acción humana).
- [ ] Aprobar draft y ejecutar run real (acción humana).
- [ ] Capturar métricas mínimas (latencia, errores, reintentos).
- [ ] Guardar evidencia en `docs/evidence/fase4_primera_prueba_real.md`.
- [ ] Aprobación Responsable.
- [ ] Aprobación Revisor.

**Responsable sugerido:** `@agent-release`  
**Revisor sugerido:** `@agent-qa-e2e`  
**Estado:** `Pendiente`

---

## Fase 5 — Hardening post-prueba (1–2 días)

- Ajustes de prompts/intents por resultados reales.
- Cobertura e2e adicional (casos felices + fallos).
- Cierre de deuda menor (tipos, mensajes, documentación de operación).

### Checklist aprobable por agentes — Fase 5
- [ ] Aplicar ajustes de prompt/intents basados en la evidencia de Fase 4.
- [ ] Añadir casos e2e de éxito y fallo controlado.
- [ ] Cerrar deuda menor priorizada (tipos/mensajes/docs).
- [ ] Publicar informe de hardening en `docs/evidence/fase5_hardening.md`.
- [ ] Aprobación Responsable.
- [ ] Aprobación Revisor.

**Responsable sugerido:** `@agent-hardening`  
**Revisor sugerido:** `@agent-qa`  
**Estado:** `Pendiente`

---

## 5) Matriz Migrar / Adaptar / Descartar (GIOS -> GICS/GIMO)

### Migrar directo
- Intent detection semántico.
- Security detector base.
- Direct response/tool call pattern.

### Adaptar
- Learner/contexto a modelos y storage actuales de GIMO.
- Auditoría de decisiones alineada con OPS/trust logs.

### Descartar (en primera prueba)
- Lógica WoW específica.
- Enrichers acoplados a datasets legacy.

---

## 6) KPIs de éxito (primera prueba real)

- Tiempo chat -> draft aprobado: <= 120s.
- Tasa de error de ejecución en prueba controlada: < 10%.
- 100% de errores con mensaje accionable.
- 0 filtraciones de secretos en logs/responses.

---

## 7) Riesgos y mitigaciones

- **Riesgo:** confusión entre ChatGPT Plus y API programática.  
  **Mitigación:** priorizar API key; account mode solo si connector-capability lo confirma.

- **Riesgo:** deriva entre tipos/config en frontend y backend.  
  **Mitigación:** consolidar contratos en `types.ts` + tests de integración.

- **Riesgo:** deuda técnica de módulos legacy GIOS.  
  **Mitigación:** migración selectiva por valor, no port completo.

---

## 7.1) Issue abierta (apartado separado) — Tests frontend Orchestrator UI

### Estado
- **Abierta**
- Severidad: media (no bloquea build ni backend, sí bloquea validación automática UI en Vitest).

### Síntoma observado
- En `tools/orchestrator_ui`, Vitest reporta repetidamente: `No test suite found in file ...` en múltiples suites.
- Afecta a suites como `ProviderSettings`, `OrchestratorChat` y otras de hooks/componentes.

### Evidencia
- `docs/evidence/fase1_providers_licensing.md`
- `docs/evidence/fase3_orquestacion_chat.md`
- Corrida consolidada: `npm --prefix tools/orchestrator_ui run test:ci` (fallos masivos por `No test suite found`).

### Estado técnico actual
- **Ya unificado** el entrypoint de tests Node/Vitest (`scripts/run-vitest.mjs`) y scripts npm.
- **Build frontend OK** con `tsconfig.build.json` separado de tests.
- **Resuelto**: Vitest fue actualizado a `v4.0.18` y configurado correctamente para dominar el entorno `jsdom`. La suite de UI ahora pasa exitosamente (121 tests verdes).

### Siguiente acción obligatoria
- ~~Abrir subfase específica de estabilización Vitest UI y cerrar con evidencia en verde antes de marcar Fase 1/Fase 3 como totalmente cerradas en frontend.~~ (**Completado**)
- Evidencia registrada en: `docs/evidence/fase1_3_vitest_stabilization.md`.

---

## 8) Checklist final de ejecución inmediata

- [ ] Fase 1 completada (tests críticos providers/licensing).
- [ ] Fase 2 completada (intent/security/direct-response integrados).
- [ ] Fase 3 completada (flujo conversacional mínimo estable).
- [ ] Entorno de prueba configurado con debug bypass.
- [ ] Provider OpenAI validado (api_key o account soportado).
- [ ] Prueba real e2e ejecutada y evidencias guardadas.

## 9) Tablero maestro de aprobación por agentes

- [ ] **Fase 0 aprobada** (Responsable + Revisor + evidencia).
- [ ] **Fase 1 aprobada** (Responsable + Revisor + evidencia).
- [ ] **Fase 2 aprobada** (Responsable + Revisor + evidencia).
- [ ] **Fase 3 aprobada** (Responsable + Revisor + evidencia).
- [ ] **Fase 4 aprobada** (Responsable + Revisor + evidencia).
- [ ] **Fase 5 aprobada** (Responsable + Revisor + evidencia).

> Regla operativa: ningún agente marca una fase como "aprobada" sin evidencia trazable en `docs/evidence/` y verificación cruzada del revisor.
