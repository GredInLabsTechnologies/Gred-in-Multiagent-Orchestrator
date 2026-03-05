# IMPLEMENTATION PLAN OPERATIVO — Skills Visuales, Slash Commands, Background Runtime y Base de AI Containers

Estado: **READY FOR EXECUTION**  
Modo: **Sin versionado funcional (modelo único activo)**  
Objetivo: **Implementar lo más rápido posible con control operativo estricto**

---

## 0) Propósito del documento

Este documento es simultáneamente:

1. **Plan de implementación exhaustivo** (arquitectura + fases + entregables).  
2. **Checklist operativo** (seguimiento de avance y criterio Go/No-Go).  
3. **System Prompt operativo por fase y por agente** (comportamiento, entregables, validaciones, revisiones).

Si un agente entra en una fase, este documento ya contiene su contrato de ejecución.

---

## 1) Alcance exacto (scope cerrado)

### 1.1 In Scope

- Skills visuales basadas en grafo (`nodes` + `edges`) como **modelo único de Skill**.
- Ejecución desde chat por slash command (`/comando`).
- Modo ejecución:
  - `replace_graph = true` (carga en lienzo y ejecuta)
  - `replace_graph = false` (ejecución silenciosa/background)
- Progreso global background con SSE + widget UI.
- Base de empaquetado portable de skills (`skill.yaml` + `graph.json`) para instalación local.

### 1.2 Out of Scope (en este plan)

- Marketplace/registry público completo.
- Optimización autónoma del grafo en producción.
- Memoria cognitiva global autoevolutiva.
- Runtime distribuido multi-cluster.

---

## 2) Principios de implementación

1. **Modelo único activo**: no coexistencia funcional de modelos de Skill.  
2. **Contrato primero**: API + SSE + tipos UI definidos antes de implementar UI compleja.  
3. **Runtime antes que estética**: la fiabilidad manda.  
4. **Sin ambigüedad**: cada fase tiene DoD, validaciones y owner.  
5. **No merge sin evidencia**: tests y checklist de aceptación obligatorios.

---

## 3) Modelo canónico objetivo

```json
{
  "id": "explorar",
  "name": "Exploración de repo",
  "description": "Recorre estructura, detecta módulos y propone mapa técnico.",
  "command": "/explorar",
  "replace_graph": false,
  "nodes": [],
  "edges": [],
  "created_at": "2026-03-05T00:00:00Z",
  "updated_at": "2026-03-05T00:00:00Z"
}
```

Reglas:

- `command` regex obligatorio: `^/[a-z0-9_-]{2,32}$`
- `command` único en el sistema
- `nodes/edges` deben formar DAG válido
- exactamente 1 nodo orchestrator

---

## 4) Contratos API objetivo

### 4.1 Skills

- `GET /ops/skills`
- `POST /ops/skills`
- `DELETE /ops/skills/{skill_id}`
- `POST /ops/skills/generate-description`
- `POST /ops/skills/{skill_id}/execute`

### 4.2 Execute response

```json
{
  "skill_run_id": "skill_run_1741132812_ab12",
  "skill_id": "explorar",
  "replace_graph": false,
  "status": "queued"
}
```

### 4.3 SSE Events

- `skill_execution_started`
- `skill_execution_progress`
- `skill_execution_finished`

Payload mínimo común:

```json
{
  "skill_run_id": "skill_run_1741132812_ab12",
  "skill_id": "explorar",
  "command": "/explorar",
  "status": "running",
  "progress": 0.42,
  "message": "Ejecutando nodo worker_2",
  "started_at": "2026-03-05T12:00:00Z",
  "finished_at": null
}
```

---

## 5) Arquitectura de ejecución objetivo (rápida y robusta)

1. Skill se persiste con `nodes/edges`.  
2. `execute` crea `skill_run_id`.  
3. Runtime reutiliza ejecución de CustomPlan (sin duplicar motor).  
4. Eventos de estado se publican con namespace skill + `skill_run_id`.  
5. UI:
   - `replace_graph=true` hidrata canvas y dispara execute visual.
   - `replace_graph=false` no toca canvas y muestra progreso en background runner.

---

## 6) Fases y secuencia obligatoria

## FASE 1 — Backend modelo único + almacenamiento + CRUD

### Objetivo
Sustituir sistema de Skill actual por modelo canónico de skill visual.

### Archivos objetivo (referenciales)
- `tools/gimo_server/ops_models.py`
- `tools/gimo_server/services/skills_service.py`
- `tools/gimo_server/routers/ops/skills_router.py`

### Tareas
- [ ] Definir `SkillDefinition` canónico en backend
- [ ] Reescribir persistencia de skills en `.orch_data/ops/skills/`
- [ ] Implementar validaciones fuertes (`command`, DAG, orchestrator único)
- [ ] Implementar GET/POST/DELETE
- [ ] Implementar endpoint `generate-description`

### Entregables
- Servicio de skills operando con modelo único
- Rutas API funcionales
- Tests unitarios backend de validación y CRUD

### DoD Fase 1
- [ ] Crear skill válida -> 201
- [ ] Duplicado de command -> 409/400
- [ ] Grafo inválido -> 400
- [ ] Listado devuelve skills parseadas correctamente

### System Prompt — Agente Backend Fase 1

```text
SYSTEM
Eres un Backend Engineer Senior orientado a entrega rápida y segura.

MISIÓN
Implementar FASE 1: modelo único SkillDefinition + CRUD + validaciones.

REGLAS DE COMPORTAMIENTO
1) No implementar features fuera de alcance.
2) Priorizar contratos API claros y errores accionables.
3) Toda validación crítica debe tener test.
4) Si detectas ambigüedad, elige la opción más simple y explícita.

ENTREGA OBLIGATORIA
- lista de archivos cambiados
- resumen técnico de decisiones
- casos de test añadidos
- evidencia de tests ejecutados

CRITERIOS DE ACEPTACIÓN
- CRUD estable
- command único y validado
- validación DAG y orchestrator único
- generate-description operativo
```

---

## FASE 2 — Runtime de ejecución + `skill_run_id` + SSE

### Objetivo
Ejecutar skills de forma trazable y desacoplada del plan visual activo.

### Tareas
- [ ] Implementar `POST /ops/skills/{id}/execute`
- [ ] Generar `skill_run_id` único por ejecución
- [ ] Integrar ejecución con motor de CustomPlan
- [ ] Emitir SSE start/progress/finish por run
- [ ] Manejar error terminal con evento final

### Entregables
- Endpoint execute funcional
- Contrato SSE documentado
- Tests integración de ejecución + streaming

### DoD Fase 2
- [ ] Dos ejecuciones simultáneas no colisionan
- [ ] Hay progreso incremental real
- [ ] Error emite `skill_execution_finished` con estado error

### System Prompt — Agente Runtime Fase 2

```text
SYSTEM
Eres Runtime Engineer. Tu prioridad es fiabilidad, trazabilidad y simplicidad.

MISIÓN
Implementar execute + skill_run_id + SSE consistente.

REGLAS
1) Cada evento debe incluir skill_run_id.
2) No mezclar estado del canvas activo con background run.
3) Siempre cerrar run con evento finished (success o error).
4) Evitar duplicación de lógica: reutilizar motor CustomPlan.

ENTREGA OBLIGATORIA
- implementación endpoint
- mapeo skill -> run
- eventos SSE estables
- pruebas integración

CRITERIOS DE ACEPTACIÓN
- flujo start/progress/finish completo
- tolerancia básica a fallo
- no colisiones concurrentes
```

---

## FASE 3 — UI Graph: Guardar como Skill + SkillsPanel operativo

### Objetivo
Permitir crear/gestionar skills desde el editor visual.

### Tareas
- [ ] Añadir botón “Guardar como Skill” en `GraphToolbar`
- [ ] Crear `SkillCreateModal`
- [ ] Integrar formulario (name, command, replace_graph, descripción IA)
- [ ] Evolucionar `SkillsPanel` para listar/ejecutar/cargar/eliminar

### Entregables
- flujo completo de guardado skill desde grafo
- panel skills funcional extremo a extremo

### DoD Fase 3
- [ ] Guardar skill desde graph editor funciona
- [ ] Ejecutar skill desde panel funciona
- [ ] Cargar skill al grafo hidrata nodos y aristas
- [ ] Eliminar skill refleja estado en UI

### System Prompt — Agente Frontend Fase 3

```text
SYSTEM
Eres Frontend Engineer experto en React/Zustand y UX operativa.

MISIÓN
Implementar UI de creación y gestión de skills en el lienzo.

REGLAS
1) Cada acción async debe tener estado loading/error/success.
2) No romper estilos ni patrones visuales existentes.
3) Mantener componentes legibles y acotados.
4) Error UX siempre accionable (toast claro).

ENTREGA OBLIGATORIA
- componentes nuevos
- integración toolbar/panel
- casos de prueba de interacción

CRITERIOS DE ACEPTACIÓN
- crear/listar/ejecutar/cargar/eliminar operativo
- UX fluida sin bloqueos opacos
```

---

## FASE 4 — Chat Slash Commands + Autocomplete + Dispatch

### Objetivo
Interceptar slash commands y enrutar a ejecución de skills.

### Tareas
- [ ] Parsear input `/` en `OrchestratorChat`
- [ ] Mostrar autocomplete de commands
- [ ] Si slash válido: ejecutar skill (no LLM)
- [ ] Soportar `replace_graph=true` y `replace_graph=false`

### Entregables
- slash UX funcional por teclado
- dispatch correcto al endpoint execute

### DoD Fase 4
- [ ] Mensaje normal mantiene comportamiento actual
- [ ] `/comando` válido no pasa por flujo LLM
- [ ] Autocomplete usable con Enter/Arrow keys

### System Prompt — Agente Chat Fase 4

```text
SYSTEM
Eres Chat Interaction Engineer. Tu objetivo es routing preciso sin romper el chat existente.

MISIÓN
Implementar slash commands robustos y rápidos.

REGLAS
1) No alterar flujo de mensajes no slash.
2) Slash inválido: feedback con sugerencias.
3) Atajos teclado deben ser confiables.
4) Evitar race conditions por múltiples envíos.

ENTREGA OBLIGATORIA
- parser slash
- autocomplete y selección
- dispatch execute
- tests de interacción

CRITERIOS DE ACEPTACIÓN
- slash enruta correctamente
- no regresión chat normal
```

---

## FASE 5 — BackgroundRunner global

### Objetivo
Mostrar progreso de skills en background sin contaminar el canvas.

### Tareas
- [ ] Crear componente `BackgroundRunner`
- [ ] Integrar escucha SSE global
- [ ] Mostrar progreso, estado y finalización
- [ ] Auto-dismiss a 5s post-completion

### Entregables
- widget global estable
- visualización multi-run (cola/lista compacta)

### DoD Fase 5
- [ ] run iniciado -> widget visible
- [ ] progreso se actualiza en tiempo real
- [ ] run terminado -> estado final + auto cierre

### System Prompt — Agente UX Runtime Fase 5

```text
SYSTEM
Eres UX Runtime Engineer. Tu prioridad es claridad y baja fricción.

MISIÓN
Implementar un widget de progreso background confiable y no intrusivo.

REGLAS
1) Solo visible cuando hay runs activos o recién completados.
2) Mensajes cortos y comprensibles.
3) Nunca mostrar stacktrace al usuario final.
4) Mantener rendimiento UI estable.

ENTREGA OBLIGATORIA
- componente global
- integración SSE/store
- pruebas de visibilidad y transición de estados

CRITERIOS DE ACEPTACIÓN
- experiencia de background clara y robusta
```

---

## FASE 6 — Skill Bundle (base de AI Container)

### Objetivo
Añadir portabilidad local instalable sin registry remoto.

### Estructura bundle objetivo

```text
skill_bundle/
 ├─ skill.yaml
 └─ graph.json
```

### Tareas
- [ ] Definir schema `skill.yaml`
- [ ] Implementar export local de skill
- [ ] Implementar install local desde bundle
- [ ] Implementar run por command/id instalada

### Entregables
- formato portable usable entre entornos locales
- comandos CLI base

### DoD Fase 6
- [ ] export -> install -> run funciona end-to-end
- [ ] validación de bundle inválido rechaza instalación

### System Prompt — Agente Platform Fase 6

```text
SYSTEM
Eres Platform Engineer. Tu objetivo es portabilidad mínima real y segura.

MISIÓN
Implementar skill bundle local como base de AI Containers.

REGLAS
1) Formato simple, explícito y documentado.
2) Validar integridad antes de instalar.
3) Errores CLI claros y accionables.
4) No dependencias externas innecesarias.

ENTREGA OBLIGATORIA
- schema bundle
- export/import/run local
- tests de round-trip

CRITERIOS DE ACEPTACIÓN
- skill portable entre instalaciones locales
```

---

## FASE 7 — QA Integral + Hardening + Release interna

### Objetivo
Cerrar la implementación con estabilidad operativa.

### Tareas
- [ ] Unit tests backend/frontend añadidos
- [ ] Integración execute + SSE + chat slash
- [ ] E2E de flujo completo
- [ ] Test de concurrencia básica
- [ ] Test de reinicio backend durante run
- [ ] Informe Go/No-Go

### Entregables
- reporte QA completo
- defect log priorizado
- decisión release interna

### DoD Fase 7
- [ ] 0 bugs críticos abiertos (P0)
- [ ] smoke end-to-end estable
- [ ] criterios de release aprobados

### System Prompt — Agente QA Fase 7

```text
SYSTEM
Eres QA Lead de release interna.

MISIÓN
Certificar o bloquear release según evidencia reproducible.

REGLAS
1) No aceptar “funciona en mi máquina” como evidencia.
2) Cada bug debe tener pasos, esperado, observado, severidad.
3) Re-test obligatorio tras cada fix.
4) Si hay riesgo alto no mitigado: NO-GO.

ENTREGA OBLIGATORIA
- matriz de pruebas
- bug log priorizado
- reporte Go/No-Go firmado

CRITERIOS DE ACEPTACIÓN
- sin P0
- flujo completo estable
- evidencia almacenada
```

---

## 7) Matriz de agentes y ownership

- **Agente A — Backend Core**: Fase 1, Fase 2
- **Agente B — Frontend UI**: Fase 3, Fase 4, Fase 5
- **Agente C — Platform/CLI**: Fase 6
- **Agente D — QA/Release**: Fase 7
- **Agente E — Integrator**: control cross-fase + merge gate

---

## 8) Prompt del Agente Integrador (siempre activo)

```text
SYSTEM
Eres Integration Lead. Tu misión es coordinar fases, bloquear deuda y garantizar contratos consistentes.

REGLAS
1) No merge sin criterios de aceptación de fase.
2) Verificar coherencia API backend <-> tipos frontend.
3) Exigir tests mínimos por PR.
4) Mantener changelog técnico por fase.

SALIDA OBLIGATORIA POR CICLO
- estado checklist
- bloqueos activos
- riesgos abiertos
- decisión: CONTINUAR / PAUSAR
```

---

## 9) Cronograma acelerado (ejecución rápida)

- Día 1-2: Fase 1
- Día 3-4: Fase 2
- Día 5-6: Fase 3
- Día 7: Fase 4
- Día 8: Fase 5
- Día 9-10: Fase 6
- Día 11-12: Fase 7

---

## 10) Riesgos críticos y mitigación

1. **Colisión de comandos** -> validar unicidad transaccional.  
2. **Runs background huérfanos** -> evento terminal obligatorio.  
3. **Mezcla de estado canvas/run** -> separar por `skill_run_id`.  
4. **Regresión en chat normal** -> tests de no regresión.  
5. **DAG inválido en producción** -> validación en create/update.  
6. **UX confusa en background** -> widget compacto y semántica de estados.  
7. **Deuda técnica por prisas** -> merge gate por fase y DoD estricto.

---

## 11) Checklist maestro de Go/No-Go final

- [ ] Skill model único activo y estable
- [ ] CRUD skills completo
- [ ] Execute con `skill_run_id` operativo
- [ ] SSE start/progress/finish estable
- [ ] Slash commands con autocomplete operativo
- [ ] `replace_graph` y background funcionando
- [ ] BackgroundRunner global estable
- [ ] Bundle export/install/run local operativo
- [ ] Tests unit/integration/e2e mínimos verdes
- [ ] QA emite **GO** para release interna

---

## 12) Modo de uso práctico de este documento

1. Seleccionar fase activa.  
2. Asignar agente owner.  
3. Copiar su **System Prompt de fase**.  
4. Ejecutar tareas con checklist de fase.  
5. Validar DoD de fase.  
6. Integrator decide CONTINUAR/PAUSAR.  
7. Repetir hasta checklist maestro completo.

---

## 13) Registro de ejecución (rellenable)

### Fase 1
- Owner:
- Fecha inicio:
- Fecha fin:
- PR(s):
- Resultado DoD: PASS / FAIL
- Incidencias:

### Fase 2
- Owner:
- Fecha inicio:
- Fecha fin:
- PR(s):
- Resultado DoD: PASS / FAIL
- Incidencias:

### Fase 3
- Owner:
- Fecha inicio:
- Fecha fin:
- PR(s):
- Resultado DoD: PASS / FAIL
- Incidencias:

### Fase 4
- Owner:
- Fecha inicio:
- Fecha fin:
- PR(s):
- Resultado DoD: PASS / FAIL
- Incidencias:

### Fase 5
- Owner:
- Fecha inicio:
- Fecha fin:
- PR(s):
- Resultado DoD: PASS / FAIL
- Incidencias:

### Fase 6
- Owner:
- Fecha inicio:
- Fecha fin:
- PR(s):
- Resultado DoD: PASS / FAIL
- Incidencias:

### Fase 7
- Owner:
- Fecha inicio:
- Fecha fin:
- PR(s):
- Resultado DoD: PASS / FAIL
- Incidencias:

---

## 14) Cierre

Este documento define el camino más corto y controlado para entregar:

- skills visuales reutilizables,
- ejecución por slash command,
- runtime background trazable,
- y base real para empaquetado portable de workflows de agentes.

**Regla final:** no se avanza de fase sin DoD cumplido.
