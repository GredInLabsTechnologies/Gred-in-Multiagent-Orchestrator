# Plan de Implementación — Drafts + Chat del Orquestador (Tabs/Split)

## Fase 1: Backend y Frontend de Drafts (Bandeja Operativa)

### 1) Diagnóstico actual (Drafts)

1. `OpsService.list_drafts()` lista todos los drafts persistidos en `.orch_data/ops/drafts`.
2. Al aprobar/rechazar, el draft no se elimina; solo cambia `status` (`draft|approved|rejected|error`).
3. El endpoint de rechazo OPS (`POST /ops/drafts/{draft_id}/reject`) requiere rol `admin`.
4. Resultado operativo:
   - sensación de “siempre salen los mismos drafts” (histórico mezclado),
   - usuarios `operator/actions` no pueden rechazar.

### 2) Objetivo funcional

1. Convertir Drafts en bandeja operativa real de pendientes.
2. Mantener trazabilidad histórica sin contaminar la vista principal.
3. Transformar la vista central del orquestador a UX tipo VS Code (tabs + split).

### 3) Backend Drafts (OPS)

1. Añadir filtros al listado de drafts:
   - `status` (draft/approved/rejected/error),
   - `limit`, `offset`.
2. Mantener compatibilidad con listado completo sin filtros.
3. Definir política de rechazo:
   - Opción A: mantener solo `admin`.
   - Opción B: permitir `operator` (si política interna lo permite).
4. (Opcional) endpoint de archivado/limpieza manual por estado/antigüedad.

### 4) Frontend Drafts

1. Filtro por defecto: `status=draft`.
2. Pestañas por estado:
   - Pendientes,
   - Aprobados,
   - Rechazados/Error,
   - Todos.
3. Mostrar badges con conteo por estado.
4. Error explícito cuando rechazo falla por permisos (403).

---

## Fase 2: Interfaz de Pestañas y Modo Dividido (Terminal y Chat)

### 5) Chat del Orquestador (integración solicitada)

#### 5.1 Objetivo

Transformar “CHAT DEL ORQUESTADOR” a sistema de pestañas:

- Tabs por defecto: `Chat` y `Terminal`.
- Clic derecho en tab Terminal para alternar:
  - `Modo Pestaña`
  - `Modo Dividido`

#### 5.2 Diseño objetivo

**Modo Pestaña (por defecto)**
- Barra de tabs: `💬 Chat` | `>_ Terminal`.
- Se renderiza una sola vista según tab activa.

**Modo Dividido**
- Chat (izquierda) + Terminal (derecha).
- Divisor redimensionable.

#### 5.3 Cambios UI

1. **[MODIFICAR] Cabecera**
   - Reemplazar “CHAT DEL ORQUESTADOR” por “CHAT” o delegar jerarquía al sistema de tabs.

2. **[NUEVO] Sistema de tabs**
   - Crear `ChatTerminalLayout.tsx`.
   - Estados:
     - `activeTab: 'chat' | 'terminal'`
     - `viewMode: 'tabs' | 'split'`

3. **[NUEVO] Menú contextual en tab Terminal**
   - Manejar evento `contextmenu`.
   - Opciones:
     - “Modo Pestaña”
     - “Modo Dividido”

4. **[NUEVO] `tools/orchestrator_ui/src/components/OpsTerminal.tsx`**
   - MVP: terminal de solo lectura consumiendo `/ops/stream` (o logs disponibles).
   - Acción: botón “Enviar resumen al chat”.

5. **[REFACTOR] `tools/orchestrator_ui/src/components/OrchestratorChat.tsx`**
   - Separar vista actual para poder montarla en tabs o panel split.
   - Añadir botón pequeño “Enviar a terminal” por mensaje.

6. **[MODIFICAR] Split panel**
   - Usar `react-resizable-panels` (o equivalente) cuando `viewMode === 'split'`.
   - Layout horizontal con divisor operable.

#### 5.4 Interacciones Chat ↔ Terminal

1. “Enviar a terminal” desde chat crea evento/entrada en terminal.
2. “Enviar resumen al chat” desde terminal publica resumen en chat.
3. Añadir trazabilidad mínima (timestamp + origen).

---

## Fase 3: Pruebas, Validación y Reparto

### 6) Plan de pruebas

1. Verificar tabs por defecto (`Chat`, `Terminal`).
2. Verificar cambio de tab por clic izquierdo.
3. Verificar menú contextual al clic derecho en tab `Terminal`.
4. Verificar “Modo Dividido” con ambos paneles y divisor funcional.
5. Volver a “Modo Pestaña” y validar consolidación visual.
6. Validar “Enviar a terminal” desde mensajes de chat.
7. Validar “Enviar resumen al chat” desde terminal.
8. Validar persistencia básica de modo/tab (si se implementa).

### 7) Reparto por agentes (recomendado)

1. **Agente A (Backend Drafts OPS):** filtros + permisos rechazo + cleanup opcional.
2. **Agente B (Layout Tabs):** `ChatTerminalLayout` + estado UI.
3. **Agente C (Context menu + Split):** menú contextual + paneles redimensionables.
4. **Agente D (OpsTerminal):** componente terminal read-only + resumen al chat.
5. **Agente E (Chat Refactor):** desacople de `OrchestratorChat` + envío a terminal.
6. **Agente F (QA):** pruebas funcionales/regresión.

### 8) Criterios de aceptación (DoD)

1. Drafts pendientes no mezclan histórico por defecto.
2. El rechazo comunica claramente permisos cuando no está autorizado.
3. La vista del orquestador soporta tabs y split sin romper flujos existentes.
4. Menú contextual de Terminal estable y usable.
5. Interacciones Chat↔Terminal operativas.
6. Pruebas mínimas en verde en rutas críticas.

---

## Fase 4: Gobernanza IDS de Agentes + Aprendizaje con GICS (integrado al split)

### 9) Objetivo de esta fase

Añadir una capa de gobernanza y trazabilidad por identidad de agente (IDS) que:

1. Distinga capacidades entre orquestador, workers y conexiones externas (ej. GPT Actions).
2. Limite la capacidad de la IA por perfil/canal, sin limitar la autoridad del usuario dueño.
3. Alimente GICS con telemetría simple para reducir fallos y adaptar el sistema al estilo de trabajo real del usuario.

### 10) Principios de diseño

1. **Usuario dueño**: control total.
2. **IA gobernada por capacidad**: no hereda automáticamente privilegios altos.
3. **Permiso efectivo**:
   - `ALLOW = owner_override OR (agent_verified AND capability_allows AND policy_allows AND hitl_if_required)`
4. Separar claramente:
   - autoridad humana,
   - capacidad de agente,
   - riesgo de acción.

### 11) Contrato IDS mínimo (telemetría simple para GICS)

Registrar eventos `AgentActionEvent` con campos mínimos:

1. `timestamp`
2. `agent_id`
3. `agent_role` (`orchestrator|worker|external_action`)
4. `channel` (`cli|provider_api|gpt_actions|mcp_remote`)
5. `trust_tier` (`t0..t3`)
6. `capability_profile` (`read_only|propose_only|execute_safe|execute_extended`)
7. `tool`
8. `action`
9. `context` (repo/task)
10. `policy_decision` (`allow|review|deny`)
11. `outcome` (`success|error|timeout|rejected`)
12. `error_code` (opcional)
13. `duration_ms` y `cost_usd` (opcionales)

### 12) Integración técnica con GICS (sin rehacer GICS)

1. **No crear nuevo motor de storage**.
2. Extender sobre GICS existente con 2 servicios nuevos en GIMO:
   - `agent_telemetry_service` (ingesta IDS)
   - `agent_insight_service` (detección de patrones y recomendaciones)
3. Persistencia por claves tipo:
   - `ae:{agent_id}:{timestamp}`
   - índices por `agent_id`, `tool`, `channel`, `trust_tier`.

### 13) Qué análisis debe habilitar

1. Detección de fallos recurrentes por combinación:
   - `agent_id + tool + context + policy_decision`.
2. Hipótesis de causa probable (ej. permisos, contrato, timeout, path scope, canal frágil).
3. Recomendaciones estructurales:
   - ajuste de policy,
   - reroute de agente/modelo,
   - elevar HITL,
   - degradar capacidad por canal.
4. Validación de impacto post-corrección (7/30 días).

### 14) Integración con UI split Chat/Terminal

1. En modo Split, usar Terminal para exponer eventos IDS relevantes en tiempo real.
2. Desde Terminal: “Enviar resumen al chat” con insights de fallos/patrones.
3. Desde Chat: “Enviar a terminal” para abrir investigación operativa de un incidente.
4. Mostrar trazabilidad mínima por evento:
   - `timestamp`, `agent_id`, `channel`, `policy_decision`, `outcome`.

### 15) Criterios de aceptación adicionales (DoD IDS)

1. Cada acción de IA relevante queda asociada a un `agent_id` trazable.
2. Se distingue claramente canal/rol/capacidad del agente en la decisión de permitir o bloquear.
3. GICS puede consultar histórico de eventos IDS para patrones de fallo.
4. Se generan recomendaciones estructurales (no solo logs crudos).
5. UI Chat/Terminal split permite observar y resumir eventos IDS en flujo operativo.
