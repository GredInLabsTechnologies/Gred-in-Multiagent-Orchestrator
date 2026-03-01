# GIMO UI Improvement Plan — 2026-02-23

> **DEPRECATED** — Supersedido por [`FIREBASE_SSO_PROFILE_PLAN_2026-02-25.md`](FIREBASE_SSO_PROFILE_PLAN_2026-02-25.md)
> Fases 1-2 completadas (commits 9662a48 y anteriores). Fase 3 parcialmente integrada en el nuevo plan.
>
> **Supersedes:** `docs/GIMO_UI_OVERHAUL_PLAN.md`, `docs/PROVIDER_UX_REWORK.md`, secciones UI de `docs/GIMO_AUDIT_REPORT.md`
> **Status:** DEPRECATED
> **Scope:** `tools/orchestrator_ui/src/`
> **Validated by:** Auditoría E2E completa con backend+frontend corriendo (2026-02-23)

---

## Context

Se completó una prueba E2E real del sistema GIMO: plan generation via LLM (Qwen) → graph visualization → approval desde frontend → ejecución por agente local. Durante esta prueba y la auditoría visual posterior, se identificaron los siguientes problemas organizados en 3 fases de prioridad.

---

## FASE 1 — Bugs Críticos (Funcionalidad Rota)

### 1.1 InspectPanel usa Bearer token en vez de cookies
- **Archivo:** `src/components/InspectPanel.tsx`
- **Líneas:** ~38-39 y ~76-89
- **Problema:** Usa `headers: { 'Authorization': 'Bearer ${ORCH_TOKEN}' }` mientras todo el resto del frontend usa `credentials: 'include'` (cookie auth vía httpOnly session)
- **Fix:** Reemplazar todas las llamadas `fetch` en InspectPanel para usar `credentials: 'include'` en vez de `Authorization` header. Eliminar import de `ORCH_TOKEN` de types.ts si ya no se usa en ningún otro componente.
- **Impacto:** Sin este fix, el InspectPanel puede fallar si `VITE_ORCH_TOKEN` no está configurado

### 1.2 GraphCanvas fetch sin API_BASE
- **Archivo:** `src/components/GraphCanvas.tsx` línea ~78
- **Archivo:** `src/App.tsx` línea ~187
- **Problema:** `fetch('/ui/graph', ...)` usa ruta relativa sin `API_BASE`. En desarrollo (Vite port 5173, backend port 9325), esto envía requests al puerto equivocado a menos que haya un proxy configurado
- **Fix:** Cambiar a `fetch(\`${API_BASE}/ui/graph\`, ...)` con import de `API_BASE` desde `../types`
- **Verificación:** Comprobar si `vite.config.ts` tiene proxy configurado para `/ui/` → si lo tiene, documentarlo; si no, aplicar el fix

### 1.3 Token de seguridad expuesto en build
- **Archivo:** `src/components/LoginModal.tsx` línea 13
- **Problema:** `import.meta.env.VITE_ORCH_TOKEN` se transpila al bundle JS final. El propio código tiene un WARNING comentado pero sigue activo
- **Fix:** Eliminar el auto-fill de token desde env var. El login debe ser siempre manual, o implementar un endpoint `/auth/auto` que valide por IP local (localhost-only)
- **Alternativa mínima:** Mantener solo en `development` mode con `import.meta.env.DEV` guard

### 1.4 Botones stub que no hacen nada
- **Archivo:** `src/components/InspectPanel.tsx`
  - Línea ~243: "SWAP AGENT INHERITANCE" → `onClick` no definido
  - Línea ~165-166: `onAnswer`/`onDismiss` → solo `console.log`
  - Línea ~280-281: Trust level buttons → solo `console.log('Update trust', level)`
  - Línea ~177: Reset prompt → solo `console.log`
- **Fix:**
  - Opción A: Implementar la funcionalidad real (API calls)
  - Opción B: Ocultar los botones con `// TODO` y comentario explicativo hasta que el backend los soporte
  - **Recomendación:** Opción B — no mostrar UI que no funciona. Un operador humano esperará que los botones hagan algo

### 1.5 MenuBar "Help" roto
- **Archivo:** `src/components/MenuBar.tsx` líneas 68-69
- **Problema:**
  - "Documentación" abre `/docs` que no existe (404)
  - "Acerca de" solo navega al tab Graph sin mostrar info
- **Fix:**
  - "Documentación" → abrir URL real (GitHub wiki, o redirigir a Settings con info)
  - "Acerca de" → mostrar modal con versión, uptime, repo info (datos ya disponibles en `/ui/status`)

### 1.6 Tab "Logs" es duplicado exacto de Maintenance
- **Archivo:** `src/App.tsx` líneas 333-340
- **Problema:** Renderiza `<MaintenanceIsland />` idéntico al tab "Maintenance", solo con un banner informativo extra
- **Fix:** Eliminar el tab "Logs" del sidebar y mover la funcionalidad de logs como sub-tab dentro de Maintenance. O bien, hacer que Logs muestre solo los audit logs filtrados (sin la sección de repos/runs)

---

## FASE 2 — Consistencia (Idioma, Datos, Duplicación)

### 2.1 Idioma mezclado EN/ES sin criterio
- **Componentes afectados:**
  - `MenuBar.tsx`: "File/Edit/View/Tools/Help" (EN)
  - `Sidebar.tsx`: "Graph, Plans, Composer, Maint, Settings" (EN)
  - `WelcomeScreen.tsx`: "Nuevo Plan", "Conectar Provider" (ES)
  - `OrchestratorChat.tsx`: "Drafts pendientes", "Actualizar" (ES)
  - `InspectPanel.tsx`: "Node Properties", "Agent Tuning", "SWAP AGENT INHERITANCE" (EN)
  - `PlansPanel.tsx`: "Plan History" (EN), subtextos en ES
  - `SettingsPanel.tsx`: "General", "Economy", "Security", "About" (EN), contenido ES
  - `PlanOverlayCard.tsx`: "Orch. Model" (EN), "Aprobar/Denegar" (ES)
- **Decisión requerida:** Elegir UN idioma para toda la UI
  - **Recomendación:** Todo en **español** para operadores hispanohablantes, manteniendo solo términos técnicos en inglés (Draft, Run, Graph, Token, etc.)
- **Fix:** Crear un archivo `src/i18n/es.ts` con todas las strings centralizadas, o al menos hacer un pass unificando todas las labels

### 2.2 Listas de modelos hardcodeadas y duplicadas
- **Archivos afectados:**
  - `src/components/PlanOverlayCard.tsx` líneas 23-35 → 11 modelos
  - `src/components/InspectPanel.tsx` líneas 195-222 → 15+ modelos con optgroups
- **Problemas:**
  - Modelos obsoletos: `codex-davinci`, `codex-cushman` (deprecated por OpenAI en 2023)
  - Modelos con nombres viejos: `claude-3-5-sonnet`, `claude-3-haiku` (ahora son 4.x)
  - Las dos listas son diferentes entre sí
  - No reflejan los modelos realmente disponibles en el sistema
- **Fix:**
  1. Crear endpoint backend `GET /ops/provider/models` que retorne los modelos disponibles del provider configurado
  2. Crear hook `useAvailableModels()` que consuma ese endpoint
  3. Reemplazar ambas listas hardcodeadas por el hook
  4. Fallback: si el endpoint falla, mostrar campo de texto libre para escribir el model ID manualmente

### 2.3 Eliminar exports/imports muertos
- **`src/types.ts`**: Verificar si `ORCH_TOKEN` sigue exportándose y si se usa en algún sitio aparte de InspectPanel (que se va a migrar a cookies). Si no → eliminar
- **Limpieza general:** Buscar `console.log` usados como placeholder handlers y reemplazar por funciones stub documentadas

---

## FASE 3 — UX (Mejoras de Experiencia de Operador)

### 3.1 Simplificar sidebar (12 tabs → 7-8 agrupados)
- **Estado actual:** 12 tabs (graph, plans, composer, threads, skills, evals, metrics, mastery, security, maintenance, logs, settings)
- **Problema:** Demasiadas opciones para un operador. Algunos tabs se solapan:
  - `plans` y `composer` son conceptualmente lo mismo
  - `logs` y `maintenance` renderizan lo mismo
  - `threads` y `skills` son features avanzadas que podrían ser sub-secciones
- **Propuesta:**
  ```
  PRIMARY:
  1. Graph (vista principal de orquestación)
  2. Plans (unificar plans + composer)
  3. Evals (test suite)
  4. Metrics (observabilidad)
  5. Mastery (economía de tokens)

  SYSTEM:
  6. Security (trust + policies)
  7. Operations (maintenance + logs + threads)
  8. Settings (providers + config)
  ```

### 3.2 Chat colapsable / redimensionable
- **Archivo:** `src/App.tsx` líneas 265-279
- **Problema:** El OrchestratorChat ocupa 40% fijo de la vista Graph (`h-2/5`). No se puede colapsar ni redimensionar
- **Fix:**
  - Añadir un drag handle entre el graph y el chat para resize
  - Añadir botón de colapsar/expandir chat (chevron)
  - Cuando está colapsado, mostrar solo la barra de input como floating bar
  - Librería sugerida: `react-resizable-panels` (ya bien integrada con el ecosystem)

### 3.3 Feedback visual de ejecución en tiempo real
- **Problema:** Cuando un Run está en progreso, los nodos cambian status pero:
  - No hay indicador de qué tarea está ejecutándose ahora
  - No hay logs en vivo en el grafo
  - No hay barra de progreso global
- **Fix:**
  - Añadir animación de pulse más visible en nodo "running"
  - Mostrar mini-log debajo del nodo activo (últimas 2 líneas del log)
  - Barra de progreso global en el header o footer (X/N tareas completadas)
  - Polling de `/ops/runs/{id}` cada 2s durante ejecución activa

### 3.4 PlanOverlayCard posicionamiento
- **Archivo:** `src/components/PlanOverlayCard.tsx`
- **Problema:** Se posiciona en `top-left` del ReactFlow canvas, tapando nodos
- **Fix:** Mover a `bottom-right` o `bottom-center`, o hacerla draggable, o convertirla en un panel lateral que no tape el grafo

### 3.5 Creación manual de nodos en el grafo
- **Solicitud del usuario** (sesión anterior): "tampoco me deja crear nuevos nodos y conectarlos entre ellos para hacer un plan manual yo en el grafo"
- **Fix:**
  - Añadir modo "edit" al GraphCanvas (toggle button)
  - En modo edit: double-click en canvas crea nodo, drag entre handles crea edge
  - Guardar el plan resultante como draft vía `POST /ops/drafts`
  - Esto unifica la experiencia de "Composer" con el Graph

---

## Archivos Clave Afectados (Referencia Rápida)

| Archivo | Fases | Cambios |
|---------|-------|---------|
| `src/App.tsx` | 1.2, 1.6, 3.1, 3.2 | API_BASE fix, eliminar tab logs, resize chat |
| `src/components/InspectPanel.tsx` | 1.1, 1.4, 2.1, 2.2 | Cookie auth, remover stubs, idioma, modelos dinámicos |
| `src/components/GraphCanvas.tsx` | 1.2, 3.3, 3.5 | API_BASE fix, feedback ejecución, modo edit |
| `src/components/MenuBar.tsx` | 1.5, 2.1 | Fix Help links, idioma |
| `src/components/Sidebar.tsx` | 1.6, 2.1, 3.1 | Reducir tabs, idioma |
| `src/components/LoginModal.tsx` | 1.3 | Remover token auto-fill inseguro |
| `src/components/PlanOverlayCard.tsx` | 2.1, 2.2, 3.4 | Idioma, modelos dinámicos, posición |
| `src/components/OrchestratorChat.tsx` | 2.1, 3.2 | Idioma, colapsable |
| `src/components/OrchestratorNode.tsx` | 3.3 | Mejor feedback visual running |
| `src/components/PlansPanel.tsx` | 2.1, 3.1 | Idioma, unificar con Composer |
| `src/components/SettingsPanel.tsx` | 2.1 | Idioma |
| `src/types.ts` | 2.3 | Limpiar exports muertos |

---

## Criterios de Aceptación por Fase

### Fase 1 completada cuando:
- [ ] Todos los `fetch()` usan `credentials: 'include'` (zero Bearer headers en frontend)
- [ ] Todos los `fetch()` usan `API_BASE` prefix
- [ ] No hay token en el bundle JS de producción
- [ ] Zero botones visibles que no hagan nada (ocultar o implementar)
- [ ] Help > Documentación abre algo real
- [ ] Tab Logs eliminado o diferenciado de Maintenance

### Fase 2 completada cuando:
- [ ] Idioma unificado en toda la UI (decisión: ES con términos técnicos EN)
- [ ] Lista de modelos viene del backend o de un archivo de config centralizado
- [ ] Zero `console.log` como handler de eventos de usuario
- [ ] `ORCH_TOKEN` eliminado de types.ts si no se usa

### Fase 3 completada cuando:
- [ ] Sidebar tiene ≤ 8 tabs sin duplicados funcionales
- [ ] Chat es colapsable/redimensionable
- [ ] Run en progreso muestra feedback visual claro (progreso, nodo activo animado)
- [ ] PlanOverlayCard no tapa nodos del grafo
- [ ] (Opcional) Modo edición manual de nodos en el grafo

---

## Notas para Agentes

- **Auth pattern:** Siempre `credentials: 'include'`, NUNCA `Authorization: Bearer`. El backend usa cookies httpOnly con HMAC-signed sessions (ver `tools/gimo_server/auth.py`)
- **API_BASE:** Importar desde `../types` → `export const API_BASE = ...`
- **Tests existentes:** Hay 575+ tests pytest backend. Para frontend, hay tests con jest pero con errores preexistentes de tipos (missing jest types, framer-motion). No son bloqueantes pero hay que ser consciente
- **Design system:** Dark theme macOS-like. Colores: bg `#0a0a0a`/`#141414`, accent `#0a84ff`, success `#32d74b`, warning `#ff9f0a`, danger `#ff453a`, text `#f5f5f7`, muted `#86868b`, border `#2c2c2e`
- **No crear archivos nuevos innecesarios.** Preferir editar los existentes
- **ReactFlow version:** v11 (import from `reactflow`, not `@xyflow/react`)
