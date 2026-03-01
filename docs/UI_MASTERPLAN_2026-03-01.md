# GIMO UI Masterplan: Transformacion Apple-Level

## Contexto

La UI de GIMO es funcional pero **generica**. Parece un dashboard oscuro mas, no un producto premium. Los problemas raiz:

- `App.tsx` es un dios monolitico (18 useState, 530 lineas, todo acoplado)
- 8 tabs sin jerarquia — sobrecarga cognitiva
- `GraphCanvas.tsx` (560 lineas) hace rendering + edicion + polling + ejecucion + validacion
- 19 hooks custom sin capa de cache — 5+ intervalos de polling independientes
- Glassmorphism definido en CSS pero apenas usado (solo MenuBar, Toast, LoginModal)
- 40+ endpoints del backend ignorados (cost analytics, trust dashboard, observability, threads)
- Cero onboarding — el usuario no sabe por donde empezar
- Feedback invisible — refetches silenciosos, spinner de boot de 6px, sin skeleton screens
- Chat sin auto-scroll, sin retry, sin historial persistente

**Objetivo**: Transformar GIMO en una interfaz excepcional con flujo humano-maquina impecable.

---

## Fase 0 — Cimientos (State Management + Design Tokens)

### 0.1 Instalar dependencias criticas
```bash
npm install zustand framer-motion
npm uninstall reactflow  # duplicado con @xyflow/react
```

**Por que Zustand**: Ligero (1.1kb), sin boilerplate, perfecto para reemplazar los 18 useState de App.tsx.
**Por que framer-motion**: Spring physics, layout animations, AnimatePresence para mount/unmount. Es lo que hace que las apps se sientan "fisicas".

### 0.2 Crear store central — `src/stores/appStore.ts` (NUEVO)
```typescript
// Reemplaza los 18 useState de App.tsx
interface AppState {
  // Auth
  authenticated: boolean | null;
  bootState: 'checking' | 'ready' | 'offline';
  sessionUser: SessionUser | null;

  // Navigation
  activeTab: SidebarTab;
  selectedNodeId: string | null;

  // UI state
  isCommandPaletteOpen: boolean;
  isChatCollapsed: boolean;
  isProfileOpen: boolean;

  // Graph
  graphNodeCount: number;
  activePlanIdFromChat: string | null;

  // Actions
  setActiveTab: (tab: SidebarTab) => void;
  selectNode: (id: string | null) => void;
  login: (user: SessionUser) => void;
  logout: () => void;
  // ...
}
```

### 0.3 Refinar Design Tokens — Editar `src/index.css`
- Agregar spacing scale explicito: `--space-1: 4px` ... `--space-8: 32px`
- Agregar sombras con profundidad real:
  - `--shadow-sm`: sombra sutil para cards
  - `--shadow-md`: sombra media para paneles flotantes
  - `--shadow-lg`: sombra profunda para modales
  - `--shadow-glow-{color}`: bloom effect por color semantico
- Subir contraste de `--text-tertiary` de `#3d4a5c` a `#5a6a7c` (WCAG AA)
- Agregar variable `--transition-spring` para curvas tipo Apple
- Definir `--glass-bg`, `--glass-border`, `--glass-shadow` como tokens reutilizables

### 0.4 Crear utilidad glass — `src/lib/glass.ts` (NUEVO)
```typescript
// Clases Tailwind reutilizables para glassmorphism consistente
export const glass = {
  panel: 'bg-surface-1/80 backdrop-blur-xl border border-white/[0.06] shadow-lg',
  card: 'bg-surface-2/70 backdrop-blur-lg border border-white/[0.04] shadow-md',
  toolbar: 'bg-surface-0/60 backdrop-blur-2xl border border-white/[0.08] shadow-xl',
  overlay: 'bg-black/40 backdrop-blur-sm',
};
```

### Archivos a modificar/crear:
| Archivo | Accion |
|---------|--------|
| `package.json` | Agregar zustand, framer-motion; quitar reactflow |
| `src/stores/appStore.ts` | **NUEVO** — store central |
| `src/lib/glass.ts` | **NUEVO** — utilidades glass |
| `src/index.css` | Refinar tokens, subir contraste, agregar sombras |
| `src/App.tsx` | Migrar 18 useState → useAppStore (reduccion masiva) |

---

## Fase 1 — Layout & Navegacion Revolution

### 1.1 Sidebar: De 8 tabs planos a navegacion jerarquica

**Editar `src/components/Sidebar.tsx`**

Redisenar completamente:
- **Grupo primario** (siempre visible): Graph, Chat (icono separado del graph)
- **Grupo secundario** (colapsable): Plans, Evals, Analytics (merge metrics+mastery)
- **Grupo sistema** (al fondo): Settings (merge security+operations dentro)
- Total: **5 items visibles** en lugar de 8
- Iconos mas grandes (20px → 24px), labels visibles on hover (tooltip animado)
- Active state: linea lateral luminosa + glow sutil (no solo color)
- Hover: background glass con blur

**Merge de tabs**:
- `metrics` + `mastery` → **Analytics** (un solo tab con sub-navegacion interna)
- `security` + `operations` → Mover dentro de **Settings** como secciones

### 1.2 MenuBar: Simplificar y hacer glass real

**Editar `src/components/MenuBar.tsx`**
- Quitar menus duplicados (View menu replica el sidebar — eliminar)
- Hacer el bar full glass: `bg-surface-0/60 backdrop-blur-2xl`
- Agregar breadcrumb contextual: `GIMO > Graph > Node: worker_01`
- Profile avatar con ring de estado (verde=conectado, naranja=degradado)
- Animacion de entrada con framer-motion (slide-down + fade)

### 1.3 StatusBar: De invisible a informativo

**Editar `src/components/StatusBar.tsx`**
- Hacer glass: `bg-surface-1/60 backdrop-blur-xl`
- Agregar: costo estimado de la sesion (desde `/ops/mastery/status`)
- Agregar: indicador de latencia del provider (ms)
- Dot de salud animado con pulse suave via framer-motion
- Click en provider → abre Settings directamente

### 1.4 Command Palette: Potenciar como hub central

**Editar `src/components/Shell/CommandPalette.tsx`**
- Agregar busqueda de nodos del grafo en vivo
- Agregar acciones rapidas: "Aprobar draft pendiente", "Ver ultimo run"
- Animacion de apertura: scale from center + glass overlay
- Resultados con iconos semanticos y preview inline
- Keyboard nav mejorada: arrow keys + Enter + Escape

### 1.5 App.tsx: Adelgazar el dios

**Editar `src/App.tsx`**
- Migrar TODO el estado a `appStore` (Zustand)
- Extraer `checkSession()` a `src/lib/auth.ts`
- Extraer `handleMcpSync()` a `src/lib/mcp.ts`
- Extraer `handleCommandAction()` como mapa en `src/lib/commands.ts`
- Convertir `renderMainContent()` en lazy-loaded routes con `React.lazy()`
- App.tsx queda como: store subscription + layout shell + providers. ~100 lineas max.

### Archivos a modificar/crear:
| Archivo | Accion |
|---------|--------|
| `src/components/Sidebar.tsx` | Redisenar: 5 items, jerarquia, glass, glow |
| `src/components/MenuBar.tsx` | Glass real, breadcrumb, quitar duplicados |
| `src/components/StatusBar.tsx` | Glass, costo sesion, latencia, animaciones |
| `src/components/Shell/CommandPalette.tsx` | Busqueda nodos, acciones rapidas |
| `src/App.tsx` | Adelgazar a ~100 lineas con store + lazy routes |
| `src/lib/auth.ts` | **NUEVO** — logica de sesion extraida |
| `src/lib/mcp.ts` | **NUEVO** — logica MCP extraida |
| `src/lib/commands.ts` | **NUEVO** — mapa de comandos |

---

## Fase 2 — Graph Canvas: El Corazon de la Experiencia

### 2.1 Dividir GraphCanvas en modulos

**De 1 archivo de 560 lineas → 4 archivos enfocados:**

| Nuevo archivo | Responsabilidad |
|--------------|-----------------|
| `src/components/graph/GraphView.tsx` | ReactFlow wrapper + rendering puro + minimap + controles |
| `src/components/graph/GraphEditor.tsx` | Edit mode: crear nodos, edges, validar, guardar draft |
| `src/components/graph/GraphExecutor.tsx` | Polling + EventSource + progress bar + status updates |
| `src/components/graph/useGraphStore.ts` | Zustand store para todo el estado del grafo |
| `src/components/graph/GraphToolbar.tsx` | Toolbar flotante glass con acciones contextuales |

**`GraphCanvas.tsx` actual** se convierte en un thin wrapper que compone los 3 modulos.

### 2.2 Nodos premium — Redisenar ComposerNode

**Editar `src/components/ComposerNode.tsx`**

Transformacion visual completa:
- **Layout**: Card con borde izquierdo de color semantico (tipo Apple Reminders)
- **Status integrado**: Borde brilla con color de estado (running=blue pulse, done=green flash, error=red)
- **Informacion progresiva**:
  - Zoom < 0.5: Solo icono + color
  - Zoom 0.5-1.0: Icono + label + status
  - Zoom > 1.0: Todo visible (model, role, output preview)
- **Hover card**: Al pasar mouse, muestra tooltip glass con detalles completos
- **Handles mas grandes**: De 8px a 12px, con glow on hover para indicar "conecta aqui"
- **Animacion de creacion**: Nodo aparece con spring scale (0.8 → 1.0)
- **Animacion de ejecucion**: Shimmer subtle en el borde mientras `running`

### 2.3 Edges con personalidad

**Crear `src/components/graph/CustomEdge.tsx` (NUEVO)**
- Edge animado con particulas cuando `running` (no solo dash offset)
- Color semantico: gris=pending, azul=active, verde=done, rojo=error
- Flecha mas grande y visible
- Al hover, resaltar el edge completo + mostrar label si existe

### 2.4 Edit Mode distinguible

- Banner superior glass: "MODO EDICION" con icono de lapiz, fondo accent-primary/10
- Borde del canvas cambia a azul sutil (visual boundary)
- Nodos tienen handles siempre visibles en edit mode
- Double-click para crear nodo: Mostrar ghost node en la posicion del cursor ANTES de crear
- Validacion en tiempo real: Nodos con problemas tienen borde rojo pulsante

### 2.5 Progress feedback de ejecucion

- Barra de progreso global en la parte superior del canvas (glass)
- Cada nodo muestra su estado con animacion: pending → shimmer → running → done (checkmark animado)
- Timeline mini en la esquina: Mostrar orden de ejecucion como dots conectados
- Si un nodo tiene `error`: Tooltip automatico con el error message

### Archivos a modificar/crear:
| Archivo | Accion |
|---------|--------|
| `src/components/GraphCanvas.tsx` | Reducir a thin wrapper |
| `src/components/graph/GraphView.tsx` | **NUEVO** — rendering puro |
| `src/components/graph/GraphEditor.tsx` | **NUEVO** — edit mode |
| `src/components/graph/GraphExecutor.tsx` | **NUEVO** — ejecucion + SSE |
| `src/components/graph/useGraphStore.ts` | **NUEVO** — store del grafo |
| `src/components/graph/GraphToolbar.tsx` | **NUEVO** — toolbar glass |
| `src/components/graph/CustomEdge.tsx` | **NUEVO** — edges premium |
| `src/components/ComposerNode.tsx` | Rediseno completo |

---

## Fase 3 — Chat & Comunicacion

### 3.1 OrchestratorChat: De utilidad a experiencia

**Editar `src/components/OrchestratorChat.tsx`**

Transformaciones:
- **Auto-scroll**: Scroll suave al ultimo mensaje cuando llega uno nuevo
- **Message bubbles premium**:
  - Bordes redondeados asimetricos (como iMessage)
  - Avatar del sistema vs usuario
  - Timestamp formateado (hace 2 min, hoy 14:30)
  - Animacion de entrada: slide-up + fade con stagger
- **Execution steps colapsables**: En vez de 5 badges inline, mostrar como timeline vertical colapsable
- **Retry en errores**: Boton "Reintentar" en mensajes fallidos
- **Provider check proactivo**: Si no hay provider, mostrar card inline con boton directo a Settings
- **Input premium**:
  - Textarea auto-expandible
  - Placeholder animado (typewriter effect)
  - Indicador de "GIMO esta pensando..." con dots animados
  - Cmd+Enter para enviar (no solo Enter)
- **Draft sidebar mejorada**: Cards con glass effect, preview del prompt, status badge animado

### 3.2 Collapsed chat inteligente

- Cuando colapsado: Mostrar ultima linea del ultimo mensaje + badge de nuevos
- Animacion de colapso: spring physics, no linear
- Click en el mensaje preview → expande el chat

### 3.3 InspectPanel: De panel denso a detalle elegante

**Editar `src/components/InspectPanel.tsx`**

- **Glass panel**: `bg-surface-1/80 backdrop-blur-xl`
- **Header con nodo preview**: Icono de tipo + label + status badge animado
- **Tabs como pills**: En vez de botones planos, pills redondeadas con transicion de indicator
- **Prompt editor premium**: Syntax highlighting basico, counter de caracteres, boton de reset
- **Config como form validado**: Dropdowns con search, validacion en tiempo real
- **Animacion de entrada**: slide-in-right con spring (no ease-out lineal)
- **Dirty state warning**: Si hay cambios sin guardar, mostrar dot naranja en tab

### Archivos a modificar:
| Archivo | Accion |
|---------|--------|
| `src/components/OrchestratorChat.tsx` | Rediseno completo de mensajes, input, sidebar |
| `src/components/InspectPanel.tsx` | Glass, tabs pills, animaciones spring |

---

## Fase 4 — Settings, Analytics & Vistas Secundarias

### 4.1 SettingsPanel: De lista plana a experiencia organizada

**Editar `src/components/SettingsPanel.tsx`**

- **Navegacion lateral interna**: En vez de scroll infinito, sidebar de categorias:
  - Proveedores (prioritario, primero siempre)
  - General
  - Economia
  - Seguridad (absorber TrustSettings)
  - Mantenimiento (absorber MaintenanceIsland)
  - Acerca de
- **Cada seccion como card glass**
- **Toggles con animacion suave** (framer-motion layout)
- **Validacion inline**: Campos numericos con limites, budgets no-negativos
- **Save/Apply global**: Barra inferior sticky con "Guardar cambios" cuando hay dirty state

### 4.2 Analytics: Merge metrics + mastery

**Crear `src/components/analytics/AnalyticsView.tsx` (NUEVO)**

Merge de ObservabilityPanel + TokenMastery en una sola vista:
- **Resumen ejecutivo** (hero cards):
  - Costo total (con trend arrow)
  - Workflows ejecutados
  - Tasa de error
  - Ahorro por eco-mode
- **Sub-tabs**: Costos | Traces | Metricas | Forecast
- **Charts con tooltips custom** y animaciones de entrada
- **Time range selector**: 7d / 30d / 90d / custom

### 4.3 WelcomeScreen: De 4 botones a onboarding guiado

**Editar `src/components/WelcomeScreen.tsx`**

- **Stepper visual**:
  1. "Conectar provider" (si no hay → card prominente con form inline)
  2. "Crear tu primer plan" (una vez conectado → CTA grande)
  3. "Explorar" (shortcuts a chat, docs, command palette)
- **Animacion de entrada**: Cards aparecen staggered con spring
- **Background**: Gradiente sutil con particulas orbitales (reusar animacion `orbit`)
- **Si provider ya conectado**: Saltar paso 1, mostrar paso 2 como hero

### Archivos a modificar/crear:
| Archivo | Accion |
|---------|--------|
| `src/components/SettingsPanel.tsx` | Rediseno con nav lateral, absorber security + operations |
| `src/components/analytics/AnalyticsView.tsx` | **NUEVO** — merge metrics + mastery |
| `src/components/WelcomeScreen.tsx` | Onboarding stepper guiado |
| `src/components/TrustSettings.tsx` | Mover dentro de SettingsPanel |

---

## Fase 5 — Polish & Micro-interacciones (The Apple Touch)

### 5.1 Sistema de transiciones unificado

**Editar `src/index.css`** + componentes

- **Toda transicion de layout**: framer-motion `layout` prop (AnimatePresence)
- **Mount/unmount**: Fade + slide con spring (no CSS animation)
- **Tab switching**: Crossfade con shared layout animation
- **Modales**: Scale from center + glass overlay fade
- **Toast rewrite**: Slide desde la derecha con spring, stack con stagger, swipe to dismiss

### 5.2 Loading states de primer nivel

- **Boot screen**: Logo GIMO animado (pulse + glow), no un spinner de 6px
- **Skeleton screens**: Para GraphCanvas, SettingsPanel, Chat — shimmer glass
- **Button loading**: Spinner inline dentro del boton (no toast separado)
- **Graph refetch**: Indicator sutil en esquina (dot pulsante azul)

### 5.3 Feedback tactil

- **Botones**: Scale 0.97 on press (ya existe) + color transition mas rapida (100ms)
- **Cards clickables**: Hover eleva la card (translateY -1px + shadow increase)
- **Toggles**: Spring bounce en el toggle handle
- **Inputs focus**: Glow ring animado (expand from 0 to full)

### 5.4 Empty states con personalidad

- Cada vista sin datos: Ilustracion minimalista + CTA claro
- Chat vacio: "Escribe tu primera instruccion..." con sugerencias debajo
- Graph vacio: Animacion de nodos fantasma que aparecen y desaparecen
- Analytics vacio: "Ejecuta tu primer workflow para ver metricas"

### 5.5 Accesibilidad enterprise

- `aria-label` en todos los botones de icono
- `role="navigation"` en sidebar
- `aria-live="polite"` en toast container
- Skip links para keyboard navigation
- Focus trap en modales
- Contraste WCAG AA en todo texto visible

### Archivos a modificar:
| Archivo | Accion |
|---------|--------|
| `src/index.css` | Spring curves, shadow scale, skeleton tokens |
| `src/components/Toast.tsx` | Rewrite con framer-motion + swipe dismiss |
| Todos los componentes | AnimatePresence wraps, layout animations |
| `src/components/LoginModal.tsx` | Boot screen premium con logo animado |

---

## Orden de Ejecucion y Dependencias

```
Fase 0 (cimientos)
  ├─→ Fase 1 (layout) ─→ Fase 4 (settings/analytics)
  └─→ Fase 2 (graph) ──→ Fase 3 (chat/inspect)
                                    └──→ Fase 5 (polish)
```

- Fase 0 es prerequisito de todo
- Fases 1 y 2 pueden hacerse en paralelo
- Fase 3 depende de Fase 2 (chat vive dentro del graph)
- Fase 4 depende de Fase 1 (nueva estructura de navegacion)
- Fase 5 es la ultima — pulido final sobre todo lo anterior

---

## Verificacion

Despues de cada fase:
1. `npm run build` — sin errores TypeScript
2. `npm run dev` — verificar visualmente cada componente
3. Probar flujo completo: Login → Welcome → Configurar provider → Crear plan en chat → Ver en graph → Aprobar → Ejecutar → Ver resultados
4. Verificar responsive (resize de ventana)
5. Verificar keyboard navigation (Tab, Enter, Escape, Ctrl+K)
6. Verificar que toasts aparecen con feedback correcto en cada accion

---

## Resumen de Impacto

| Metrica | Antes | Despues |
|---------|-------|---------|
| useState en App.tsx | 18 | 0 (Zustand) |
| Tabs de sidebar | 8 | 5 |
| Lineas en GraphCanvas | 560 | ~120 (wrapper) + 4 modulos |
| Lineas en App.tsx | 530 | ~100 |
| Endpoints usados del backend | ~12 | ~25+ |
| Glassmorphism usado | 3 sitios | Todo panel/toolbar/overlay |
| Animaciones con spring physics | 0 | Todas las transiciones |
| Skeleton loading screens | 0 | Todas las vistas |
| Onboarding guiado | No | Si (stepper 3 pasos) |
| Accesibilidad WCAG AA | Parcial | Completa |
