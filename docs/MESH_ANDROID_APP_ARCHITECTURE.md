# GIMO Mesh — Android App Architecture

## 1. Vision

App nativa Android (Kotlin + Jetpack Compose) que convierte un dispositivo Android en un nodo autogobernado de la mesh GIMO. La app es **la interfaz del dispositivo con la mesh** — no un dashboard remoto. Muestra lo que este dispositivo está haciendo, cómo se siente, y le da al humano control absoluto.

**Principio de diseño**: Instrumento de precisión. Como un panel de avión — muestra todo lo necesario, nada superfluo, y cada elemento tiene una razón de existir.

**Principio de peso**: La app es un parásito benigno — cuando el mesh trabaja, la app NO EXISTE como carga computacional. Cero recomposiciones, cero polling, cero animaciones. El 100% de CPU/RAM va a llama-server.

**Mockup visual**: `docs/mockups/gimo-mesh-app.html` — diseño interactivo con las 4 pantallas.

---

## 2. Zero-Weight Architecture

### 2.1 El Problema

El Galaxy S10 genera 2.6 tok/s con 4 threads a tope. Cada ciclo de CPU que robe la app es un token que no se genera. La app Android debe ser **termodinámicamente invisible** durante inferencia.

### 2.2 Dos Modos de UI: Instrument vs Blackout

La app tiene dos modos de renderizado, determinados por `operational_state`:

| Modo | Cuándo | UI | CPU de la app | RAM de la app |
|------|--------|-----|---------------|---------------|
| **Instrument** | idle, paused, error | Full UI con gauges, graph, animations | Normal (~2-5%) | ~40MB |
| **Blackout** | busy (inferencia activa) | Pantalla estática minimal | **~0%** | ~15MB |

#### Modo Instrument (idle)
El dashboard completo: health ring animado, mesh graph con glows, métricas actualizándose cada 30s, terminal con auto-scroll. La app se comporta como un instrumento de precisión.

#### Modo Blackout (inferencia activa)
Cuando `operational_state == busy`, la app entra en blackout:

```
┌─────────────────────────────────────┐
│  GIMO Mesh              ● Working  │
├─────────────────────────────────────┤
│                                     │
│                                     │
│            ╭─────────╮             │
│            │  2.6    │             │
│            │  tok/s  │             │
│            ╰─────────╯             │
│                                     │
│         qwen2.5:3b                  │
│         task t-0042                 │
│         31 tokens generated         │
│                                     │
│         elapsed: 11.9s              │
│                                     │
│                                     │
│  ┌──────────────────────────────┐   │
│  │      ⏻  STOP INFERENCE       │   │
│  │      (hold 2s to confirm)    │   │
│  └──────────────────────────────┘   │
│                                     │
├─────────────────────────────────────┤
│  ◉ Dash  ▷ Term  ◈ Agent  ⚙ Conf  │
└─────────────────────────────────────┘
```

**Qué se apaga en blackout:**
- Todas las animaciones CSS/Compose (glow, pulse, spring)
- Canvas del mesh graph (se reemplaza por texto estático)
- Health ring SVG (se reemplaza por número)
- LazyColumn del terminal (el buffer sigue llenándose, NO se renderiza)
- Recomposiciones periódicas de métricas (se congela la UI)
- Heartbeat polling reduce de 30s a 60s

**Qué queda activo en blackout:**
- Un único `Text` estático con tok/s + modelo + task (actualizado solo al recibir SSE chunk)
- El kill switch (siempre accesible)
- La foreground notification (Android la maneja, no la app)
- El terminal buffer sigue coleccionando en memoria (ring buffer, zero UI cost)

**Cómo se implementa:**

```kotlin
@Composable
fun DashboardScreen(state: MeshState) {
    if (state.operationalState == OperationalState.BUSY) {
        BlackoutView(state)  // ~5 composables, zero animation
    } else {
        InstrumentView(state)  // Full dashboard
    }
}

@Composable
fun BlackoutView(state: MeshState) {
    // STATIC layout — no animation, no recomposition triggers
    // Solo se recompone cuando cambia tok/s o token count
    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "${state.tokensPerSecond}",
            fontFamily = GimoMono,
            fontSize = 48.sp,
            fontWeight = FontWeight.Light,
            color = GimoAccents.teal
        )
        Text("tok/s", style = labelStyle)
        Spacer(Modifier.height(24.dp))
        Text(state.modelLoaded, style = subtitleStyle)
        Text("task ${state.activeTaskId}", style = captionStyle)
        Text("${state.tokensGenerated} tokens", style = captionStyle)
        Spacer(Modifier.height(8.dp))
        Text("elapsed: ${state.elapsedFormatted}", style = captionStyle)
    }
    // Kill switch siempre visible en la base
    KillSwitch(...)
}
```

### 2.3 Presupuesto de CPU por Componente

| Componente | Instrument Mode | Blackout Mode |
|-----------|----------------|---------------|
| Compose recompositions | 2-4% | **0%** (static) |
| Canvas mesh graph | 1-2% | **0%** (hidden) |
| Animations (glow, pulse) | 1-2% | **0%** (disabled) |
| Health ring SVG | <1% | **0%** (replaced by text) |
| OkHttp heartbeat (30s/60s) | <1% spike/30s | <1% spike/60s |
| Terminal LazyColumn scroll | 1-2% when visible | **0%** (buffer only) |
| MetricsCollector | <1% | <1% (still needed for thermal protection) |
| **TOTAL** | **~8%** | **<1%** |

### 2.4 Protección Térmica Siempre Activa

Incluso en blackout, `MetricsCollector` sigue leyendo temperaturas cada 60s. Si detecta thermal warning, la app puede pausar llama-server. Esto es la ÚNICA razón por la que la app consume algo de CPU en blackout — proteger el hardware.

### 2.5 Transiciones

```
User taps "Start Mesh" → Instrument mode
  ↓
Task dispatched → operational_state = busy
  ↓
UI transitions to Blackout (crossfade 300ms, then freeze)
  ↓
Task completes → operational_state = idle
  ↓
UI transitions to Instrument (crossfade 300ms, resume animations)
```

La transición es un simple crossfade de 300ms. No hay animación de entrada en blackout — eso sería desperdiciar CPU en el momento exacto en que la inferencia empieza.

---

## 3. Tech Stack

| Capa | Tecnología | Razón |
|------|-----------|-------|
| UI | Jetpack Compose + Material 3 | Declarativo, nativo, rendimiento |
| Tema | Custom dark theme (GIMO identity) | Réplica del frontend web |
| Navegación | Compose Navigation | Single-activity |
| Networking | OkHttp + Kotlin Serialization | Lightweight, suspend-native |
| Background | Foreground Service (solo cuando activo) | Control explícito |
| Wake | BLE PendingIntent Scanner | Zero-process cuando apagado |
| Terminal | LazyColumn + monospace (solo en Instrument mode) | Stream de output del agente |
| Gráfos | Canvas API (Compose, solo en Instrument mode) | Visualización ligera del mesh |
| DI | Manual (singleton objects) | Sin Hilt/Dagger — app mínima |
| Storage | DataStore (Preferences) | Config persistente |

---

## 4. Identidad Visual — GIMO Dark Theme

Replicada del frontend web (`index.css`):

### 4.1 Superficies

```kotlin
object GimoSurfaces {
    val surface0 = Color(0xFF080C14)  // Fondo más oscuro
    val surface1 = Color(0xFF0C1222)  // Superficie primaria
    val surface2 = Color(0xFF141C2E)  // Superficie elevada
    val surface3 = Color(0xFF1C2640)  // Superficie secundaria elevada
}
```

### 4.2 Acentos Semánticos

```kotlin
object GimoAccents {
    val primary    = Color(0xFF3B82F6)  // Azul — acciones primarias
    val approval   = Color(0xFFD4A574)  // Dorado — aprobaciones
    val trust      = Color(0xFF5A9F8F)  // Teal — éxito, salud
    val alert      = Color(0xFFC85450)  // Rojo — errores, peligro
    val warning    = Color(0xFFD4975A)  // Naranja — precaución
    val purple     = Color(0xFF8B7EC8)  // Púrpura — acento secundario
}
```

### 4.3 Texto

```kotlin
object GimoText {
    val primary   = Color(0xFFE8ECF4)  // Texto principal
    val secondary = Color(0xFF7D8A99)  // Texto secundario
    val tertiary  = Color(0xFF5A6A7C)  // Texto muted
}
```

### 4.4 Bordes

```kotlin
object GimoBorders {
    val primary = Color(0xFF1E2A3E)
    val subtle  = Color(0xFF141C2E)
    val focus   = Color(0xFF3B82F6)
}
```

### 4.5 Colores de Estado (Mesh)

```kotlin
object MeshStateColors {
    val connected      = Color(0xFF22C55E)  // Verde
    val approved       = Color(0xFF4ADE80)  // Verde claro
    val pendingApproval = Color(0xFFEAB308) // Amarillo
    val reconnecting   = Color(0xFFFACC15)  // Amarillo claro
    val thermalLockout = Color(0xFFEF4444)  // Rojo
    val refused        = Color(0xFFF87171)  // Rojo claro
    val offline        = Color(0xFF71717A)  // Zinc
    val discoverable   = Color(0xFF60A5FA)  // Azul
}
```

### 4.6 Colores de Modo

```kotlin
object MeshModeColors {
    val inference = Color(0xFF2563EB)  // Azul
    val utility   = Color(0xFF9333EA)  // Púrpura
    val server    = Color(0xFFD97706)  // Ámbar
    val hybrid    = Color(0xFF0891B2)  // Cyan
}
```

### 4.7 Tipografía

```kotlin
// Monospace para métricas y terminal
val GimoMono = FontFamily(Font(R.font.jetbrains_mono))
// Sans para UI
val GimoSans = FontFamily.Default  // System SF Pro / Roboto
```

### 4.8 Efectos

- **Glass**: `surface1.copy(alpha = 0.75f)` + `Modifier.blur(20.dp)`
- **Glow**: `shadow(color = accent.copy(alpha = 0.15f), blurRadius = 20.dp)`
- **Press**: `animateFloatAsState(if (pressed) 0.97f else 1f)` → `Modifier.scale()`
- **Border radius**: `RoundedCornerShape(12.dp)` (cards), `RoundedCornerShape(8.dp)` (buttons)

---

## 5. Arquitectura de Pantallas

### 5.0 Diagrama de Navegación

```
                    ┌─────────────────────┐
                    │    SplashScreen      │
                    │  (auto → Dashboard)  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │    BottomNavBar      │
                    │  ┌───┬───┬───┬───┐  │
                    │  │ D │ T │ A │ S │  │
                    │  └─┬─┴─┬─┴─┬─┴─┬─┘  │
                    └────┼───┼───┼───┼────┘
                         │   │   │   │
              ┌──────────┘   │   │   └──────────┐
              │              │   │              │
    ┌─────────▼──────┐ ┌────▼───▼────┐ ┌───────▼──────┐
    │   Dashboard    │ │  Terminal   │ │   Settings   │
    │                │ │             │ │              │
    │ • Mesh Graph   │ │ • Live log  │ │ • Core URL   │
    │ • Status ring  │ │ • History   │ │ • Token      │
    │ • Telemetry    │ │ • Task JSON │ │ • BLE wake   │
    │ • Model info   │ │             │ │ • Device ID  │
    │ • Kill switch  │ │             │ │ • Thermal    │
    └────────────────┘ └─────────────┘ └──────────────┘
                              │
                    ┌─────────▼─────────┐
                    │    Agent Screen    │
                    │                   │
                    │ • Task queue      │
                    │ • Current task    │
                    │ • Dispatch log    │
                    └───────────────────┘

    D = Dashboard (home)
    T = Terminal
    A = Agent
    S = Settings
```

---

### 5.1 Dashboard (pantalla principal)

La pantalla que ves al abrir la app. Responde a: **¿qué está haciendo mi dispositivo ahora mismo?**

```
┌─────────────────────────────────────┐
│  GIMO Mesh              ● Connected │  ← Header: logo + estado
├─────────────────────────────────────┤
│                                     │
│        ┌───┐    ┌───┐              │
│   ┌───►│ PC├───►│ S10│◄── YOU ARE  │  ← Mini Mesh Graph
│   │    └───┘    └───┘    HERE      │     (Canvas, 3-5 nodos max)
│   │                                 │
│                                     │
├─────────────────────────────────────┤
│                                     │
│  ┌────────────────────────────────┐ │
│  │        HEALTH  87%             │ │  ← Health Ring (circular gauge)
│  │       ╭━━━━━━━━━╮             │ │     Teal cuando >70
│  │      ╱     87     ╲            │ │     Amarillo 40-70
│  │     ╱               ╲          │ │     Rojo <40
│  │     ╲               ╱          │ │
│  │      ╲             ╱           │ │
│  │       ╰━━━━━━━━━╯             │ │
│  └────────────────────────────────┘ │
│                                     │
│  ┌──────┐ ┌──────┐ ┌──────┐       │
│  │ CPU  │ │ RAM  │ │ BAT  │       │  ← Metric Cards (3 columnas)
│  │      │ │      │ │      │       │     Valor grande + mini gauge
│  │ 23%  │ │ 54%  │ │ 78%  │       │
│  │ ━━━━ │ │ ━━━━ │ │ ━━━━ │       │
│  └──────┘ └──────┘ └──────┘       │
│                                     │
│  ┌──────────────────────────────┐   │
│  │ 🌡 Thermal                    │   │  ← Thermal Strip
│  │ CPU 42°C  GPU --  BAT 31°C  │   │     Color-coded por umbrales
│  │ throttled: no  lockout: no   │   │
│  └──────────────────────────────┘   │
│                                     │
│  ┌──────────────────────────────┐   │
│  │ MODEL  qwen2.5:3b            │   │  ← Model Card
│  │ Endpoint  192.168.0.244:8080 │   │
│  │ Params  3.09B  Quant Q4_K_M  │   │
│  │ Mode  inference              │   │
│  └──────────────────────────────┘   │
│                                     │
│  ┌──────────────────────────────┐   │
│  │      ⏻  STOP MESH NODE       │   │  ← Kill Switch
│  │      (hold 2s to confirm)    │   │     Long-press para confirmar
│  └──────────────────────────────┘   │     Rojo alert, glow pulsante
│                                     │
├─────────────────────────────────────┤
│  ◉ Dashboard  ▷ Terminal  ◈ Agent  ⚙│  ← Bottom Nav
└─────────────────────────────────────┘
```

#### 5.1.1 Mini Mesh Graph

Renderizado con **Canvas API** (Compose). No ReactFlow — demasiado pesado para móvil.

- Layout LR (left-to-right), 3-5 nodos máximo (solo los que importan)
- Nodo actual resaltado con glow pulsante (`glow-breath` animation)
- Nodos = círculos con icono (PC = monitor, phone = smartphone, server = rack)
- Edges = líneas con dash animado si hay tráfico activo
- Colores por rol: los mismos `MeshModeColors`
- Tap en nodo muestra tooltip con nombre + estado
- Datos desde `GET /ops/mesh/devices` — se muestran todos los devices de la mesh

```kotlin
// Representación simplificada
data class MeshNodeView(
    val id: String,
    val label: String,
    val mode: DeviceMode,
    val state: ConnectionState,
    val isCurrentDevice: Boolean  // ← este tiene glow
)
```

#### 5.1.2 Health Ring

Gauge circular al estilo Apple Watch. `Canvas` con `drawArc`:

```
- Track: surface3, strokeWidth = 12.dp
- Fill: trust/warning/alert según score, strokeWidth = 12.dp
- Center: score en texto grande (GimoMono, 48sp)
- Label debajo: "HEALTH" en 10sp uppercase tracking-wider
- Animación: spring animation al cambiar valor
```

#### 5.1.3 Metric Cards

Grid de 3 columnas, cada card:

```
- Background: surface1, border: border-primary, rounded 12dp
- Icono arriba-derecha: 14dp, text-secondary
- Valor: GimoMono, 24sp, colored (trust si OK, warning si medio, alert si alto)
- Label: 10sp uppercase, text-secondary, tracking wide
- Mini progress bar: h=2dp en la base, mismo color que el valor
```

#### 5.1.4 Kill Switch

Botón de emergencia — apaga llama-server, detiene heartbeats, desregistra de la mesh.

```
- Long-press (2 segundos) para activar — previene taps accidentales
- Visual: surface2 bg, border alert/50, text alert
- Durante hold: progress arc circular se llena de rojo
- Al completar: vibración háptica + confirmación flash
- Post-kill: botón cambia a "START MESH NODE" en verde
```

---

### 5.2 Terminal

Emulador de terminal que muestra el output del agente de inferencia en tiempo real.

```
┌─────────────────────────────────────┐
│  Terminal              ● LIVE       │  ← Header con indicador live
├─────────────────────────────────────┤
│                                     │
│  ┌─ Filter ─────────────────────┐   │
│  │ ALL │ AGENT │ INFERENCE │ SYS│   │  ← Tabs de filtro
│  └──────────────────────────────┘   │
│                                     │
│  > 14:23:01 [AGENT] heartbeat OK    │  ← LazyColumn, font mono
│  > 14:23:01 [AGENT] cpu=23% ram=54% │     Auto-scroll, coloreado
│  > 14:23:31 [AGENT] heartbeat OK    │
│  > 14:24:02 [INFER] request recv    │
│  > 14:24:02 [INFER] loading ctx...  │
│  > 14:24:03 [INFER] generating...   │
│  > 14:24:03 [INFER] tok/s: 2.6     │
│  > 14:24:08 [INFER] 12 tokens done  │
│  > 14:24:08 [AGENT] task complete   │
│  │                                   │
│  │                                   │
│  │                                   │
│                                     │
│  ┌──────────────────────────────┐   │
│  │ ⏸ Pause   📋 Copy   🗑 Clear│   │  ← Action bar
│  └──────────────────────────────┘   │
│                                     │
├─────────────────────────────────────┤
│  ◉ Dashboard  ▷ Terminal  ◈ Agent  ⚙│
└─────────────────────────────────────┘
```

#### 5.2.1 Fuentes de log

El terminal agrega múltiples fuentes:

| Fuente | Color | Contenido |
|--------|-------|-----------|
| `AGENT` | `primary` (azul) | Heartbeats, estado, errores del mesh agent |
| `INFER` | `trust` (teal) | Output de llama-server (tok/s, requests, modelo) |
| `SYS` | `secondary` (gris) | Batería, temperatura, warnings del sistema |
| `TASK` | `approval` (dorado) | Tareas recibidas, completadas, fallidas |

#### 5.2.2 Implementación

```kotlin
data class TerminalLine(
    val timestamp: Instant,
    val source: LogSource,  // AGENT, INFER, SYS, TASK
    val message: String,
    val level: LogLevel     // DEBUG, INFO, WARN, ERROR
)

// Ring buffer de 5000 líneas (evita OOM)
class TerminalBuffer(capacity: Int = 5000) {
    private val buffer = ArrayDeque<TerminalLine>(capacity)
    // ...
}
```

- **Live mode**: Auto-scroll al final, indicador "LIVE" pulsante
- **Pause mode**: Scroll libre, botón "↓ Jump to bottom" aparece
- **Copy**: Copia selección o las últimas 100 líneas al clipboard
- **Export**: Share sheet con las últimas 1000 líneas como .txt

---

### 5.3 Agent

Vista de las tareas que la mesh ha despachado a este dispositivo.

```
┌─────────────────────────────────────┐
│  Agent Tasks                     3  │
├─────────────────────────────────────┤
│                                     │
│  ┌──────────────────────────────┐   │
│  │ ● RUNNING                    │   │  ← Current Task Card
│  │                              │   │     (expandido, glow azul)
│  │ Task: code_review            │   │
│  │ Target: auth_middleware.py   │   │
│  │ Complexity: moderate         │   │
│  │ Dispatched: 14:20:01        │   │
│  │                              │   │
│  │ ┌ Prompt Schema ──────────┐ │   │
│  │ │ {                       │ │   │  ← JSON colapsable del
│  │ │   "action_class": "..." │ │   │     TaskFingerprint recibido
│  │ │   "target_type": "..."  │ │   │
│  │ │   "domain_hints": [...] │ │   │
│  │ │   "complexity": "..."   │ │   │
│  │ │ }                       │ │   │
│  │ └────────────────────────-┘ │   │
│  │                              │   │
│  │ ┌ Inference Stream ───────┐ │   │
│  │ │ The auth middleware sho… │ │   │  ← Output en tiempo real
│  │ │ uld validate the token  │ │   │     del modelo (streaming)
│  │ │ before checking roles…  │ │   │
│  │ │ █                       │ │   │  ← Cursor parpadeante
│  │ └────────────────────────-┘ │   │
│  └──────────────────────────────┘   │
│                                     │
│  ── History ────────────────────    │
│                                     │
│  ┌──────────────────────────────┐   │
│  │ ✓ code_generation  14:15    │   │  ← Completed tasks
│  │   api_router.py  2.3s       │   │     (colapsado, tap = expand)
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │ ✗ test_execution   14:10    │   │  ← Failed task
│  │   test_auth.py  timeout     │   │     (borde rojo)
│  └──────────────────────────────┘   │
│                                     │
├─────────────────────────────────────┤
│  ◉ Dashboard  ▷ Terminal  ◈ Agent  ⚙│
└─────────────────────────────────────┘
```

#### 5.3.1 Task Card (expandida)

- **Header**: badge de estado con glow (running=azul, done=teal, error=rojo)
- **Metadata**: action_class, target_type, domain_hints, complexity
- **Prompt Schema**: `TaskFingerprint` completo en JSON syntax-highlighted, colapsable
- **Inference Stream**: Output del modelo en tiempo real con cursor parpadeante
- **Timing**: dispatched_at, started_at, completed_at, duration

#### 5.3.2 Inference Stream

```kotlin
// SSE-like stream desde llama-server
// GET http://localhost:8080/v1/chat/completions (stream=true)
// Cada chunk se appenda al LazyColumn con animación typewriter
```

---

### 5.4 Settings

```
┌─────────────────────────────────────┐
│  Settings                           │
├─────────────────────────────────────┤
│                                     │
│  ── Connection ─────────────────    │
│  Core URL     http://192.168.0.49.. │
│  Token        ••••••••••••••k8A     │
│  Device ID    galaxy-s10            │
│  Device Name  Samsung Galaxy S10    │
│                                     │
│  ── Mesh Node ──────────────────    │
│  Mode         [inference ▾]         │
│  Model        qwen2.5:3b            │
│  Inference Port  8080               │
│  Threads      4                     │
│  Context Size 2048                  │
│                                     │
│  ── BLE Wake ───────────────────    │
│  Enable BLE wake    [━━● ON ]       │
│  Wake key     ••••••••••••          │
│  Scan mode    Low Power             │
│                                     │
│  ── Thermal Limits ─────────────    │
│  CPU warning     65°C               │
│  CPU lockout     75°C               │
│  Battery warning 38°C               │
│  Battery lockout 42°C               │
│  Min battery %   20%                │
│                                     │
│  ── About ──────────────────────    │
│  Version      1.0.0                 │
│  Agent        mesh_agent_lite 0.1   │
│  llama.cpp    b4567                 │
│                                     │
├─────────────────────────────────────┤
│  ◉ Dashboard  ▷ Terminal  ◈ Agent  ⚙│
└─────────────────────────────────────┘
```

---

## 6. Arquitectura de Módulos

```
app/
├── src/main/
│   ├── java/com/gredinlabs/gimomesh/
│   │   │
│   │   ├── ui/                          # Capa de presentación
│   │   │   ├── theme/
│   │   │   │   ├── GimoTheme.kt         # Material 3 custom theme
│   │   │   │   ├── Color.kt             # Paleta GIMO completa
│   │   │   │   ├── Type.kt              # Tipografía
│   │   │   │   └── Shape.kt             # Formas (radii)
│   │   │   │
│   │   │   ├── navigation/
│   │   │   │   └── NavGraph.kt           # Bottom nav + routes
│   │   │   │
│   │   │   ├── dashboard/
│   │   │   │   ├── DashboardScreen.kt    # Pantalla principal
│   │   │   │   ├── MeshGraphView.kt      # Canvas mesh graph
│   │   │   │   ├── HealthRing.kt         # Gauge circular
│   │   │   │   ├── MetricCard.kt         # CPU/RAM/Battery cards
│   │   │   │   ├── ThermalStrip.kt       # Barra de temperaturas
│   │   │   │   ├── ModelCard.kt          # Info del modelo cargado
│   │   │   │   └── KillSwitch.kt         # Botón de apagado
│   │   │   │
│   │   │   ├── terminal/
│   │   │   │   ├── TerminalScreen.kt     # Pantalla de terminal
│   │   │   │   ├── TerminalLine.kt       # Línea individual
│   │   │   │   └── TerminalFilter.kt     # Tabs de filtro
│   │   │   │
│   │   │   ├── agent/
│   │   │   │   ├── AgentScreen.kt        # Pantalla de tareas
│   │   │   │   ├── TaskCard.kt           # Card de tarea expandible
│   │   │   │   ├── JsonViewer.kt         # Syntax-highlighted JSON
│   │   │   │   └── InferenceStream.kt    # Streaming de output
│   │   │   │
│   │   │   ├── settings/
│   │   │   │   └── SettingsScreen.kt     # Configuración
│   │   │   │
│   │   │   └── components/               # Componentes compartidos
│   │   │       ├── StatusDot.kt          # Dot con color de estado
│   │   │       ├── GlassCard.kt          # Card con glass effect
│   │   │       ├── MiniGauge.kt          # Progress bar horizontal
│   │   │       └── Badge.kt             # Badge de modo/estado
│   │   │
│   │   ├── data/                         # Capa de datos
│   │   │   ├── api/
│   │   │   │   ├── GimoCoreClient.kt     # OkHttp client → GIMO Core
│   │   │   │   ├── MeshApi.kt            # Endpoints /ops/mesh/*
│   │   │   │   └── InferenceApi.kt       # Endpoints llama-server
│   │   │   │
│   │   │   ├── model/
│   │   │   │   ├── MeshDevice.kt         # Mirror de MeshDeviceInfo
│   │   │   │   ├── HeartbeatPayload.kt   # Mirror de HeartbeatPayload
│   │   │   │   ├── TaskFingerprint.kt    # Mirror de TaskFingerprint
│   │   │   │   ├── ThermalProfile.kt     # Mirror de thermal profile
│   │   │   │   ├── DispatchDecision.kt   # Mirror de DispatchDecision
│   │   │   │   └── MeshStatus.kt         # Mirror de MeshStatus
│   │   │   │
│   │   │   └── store/
│   │   │       └── SettingsStore.kt      # DataStore preferences
│   │   │
│   │   ├── service/                      # Capa de servicios
│   │   │   ├── MeshAgentService.kt       # Foreground Service: heartbeats + métricas
│   │   │   ├── InferenceService.kt       # Gestión de llama-server process
│   │   │   ├── MetricsCollector.kt       # CPU/RAM/Battery/Thermal (port de android_metrics.py)
│   │   │   ├── TerminalBuffer.kt         # Ring buffer de logs
│   │   │   └── BleWakeReceiver.kt        # BLE PendingIntent handler
│   │   │
│   │   ├── ble/                          # Capa BLE
│   │   │   ├── WakeScanner.kt            # Registro de PendingIntent scan
│   │   │   ├── WakeTokenVerifier.kt      # HMAC verification
│   │   │   └── BootReceiver.kt           # Re-registra scan tras reboot
│   │   │
│   │   └── GimoMeshApp.kt               # Application class
│   │
│   ├── res/
│   │   ├── font/
│   │   │   └── jetbrains_mono*.ttf       # Fuente monospace
│   │   ├── drawable/
│   │   │   └── ic_gimo_mesh.xml          # App icon
│   │   └── values/
│   │       └── strings.xml               # EN + ES
│   │
│   └── AndroidManifest.xml
│
├── build.gradle.kts
└── proguard-rules.pro
```

---

## 7. Ciclo de Vida de la App

### 7.1 Estados de la App

```
                    ┌─────────────┐
                    │   DORMANT   │  App no existe en memoria
                    │  (0% CPU)   │  Solo BLE scanner HW activo
                    └──────┬──────┘
                           │
              BLE wake / Usuario abre app
                           │
                    ┌──────▼──────┐
                    │   AWAKE     │  App abierta, UI visible
                    │  (idle)     │  No corre inferencia
                    └──────┬──────┘
                           │
              Usuario toca "Start Mesh" / Tarea llega
                           │
                    ┌──────▼──────┐
                    │   ACTIVE    │  Foreground Service activo
                    │  (mesh on)  │  Heartbeats + llama-server
                    └──────┬──────┘
                           │
              Kill switch / Thermal lockout / Batería baja
                           │
                    ┌──────▼──────┐
                    │   AWAKE     │  Vuelve a idle
                    └──────┬──────┘
                           │
              Usuario cierra app / Timeout
                           │
                    ┌──────▼──────┐
                    │   DORMANT   │
                    └─────────────┘
```

### 7.2 Regla de Oro

> **Cuando el usuario apaga el mesh, TODO se detiene.** Cero servicios, cero heartbeats, cero sockets. Solo el BLE scanner de hardware (si está habilitado en Settings) permanece como observer pasivo en el chip Bluetooth — no es un proceso de la app.

### 7.3 Consumo de Batería por Estado

| Estado | Consumo estimado |
|--------|-----------------|
| DORMANT (BLE wake ON) | ~0.5%/día |
| DORMANT (BLE wake OFF) | 0%/día |
| AWAKE (UI visible, mesh off) | Normal (como cualquier app) |
| ACTIVE (mesh on, idle) | ~1-2%/hora (heartbeats cada 30s) |
| ACTIVE (inferencia) | ~8-15%/hora (CPU a tope, 4 threads) |

---

## 8. Flujo de Datos

### 8.1 Heartbeat Loop (cuando ACTIVE)

```
┌──────────────┐     POST /ops/mesh/heartbeat      ┌────────────┐
│ MetricsCollector├──────────────────────────────────►│ GIMO Core  │
│ (cada 30s)   │     {device_id, secret,            │            │
│              │      cpu%, ram%, bat%,              │            │
│              │      temps, model, endpoint}        │            │
│              │◄──────────────────────────────────── │            │
│              │     Response: MeshDeviceInfo        │            │
│              │     + pending_task (futuro)         │            │
└──────────────┘                                     └────────────┘
       │
       ▼
  TerminalBuffer.append(AGENT, "heartbeat OK cpu=23%...")
       │
       ▼
  DashboardScreen (recompose con nuevos datos)
```

### 8.2 Inference Flow (cuando tarea asignada)

```
GIMO Core ──dispatch──► Heartbeat response con pending_task
                              │
                              ▼
                     AgentScreen muestra TaskCard
                     JsonViewer muestra TaskFingerprint
                              │
                              ▼
                     InferenceService envía request a
                     localhost:8080/v1/chat/completions
                              │ (stream=true)
                              ▼
                     InferenceStream muestra tokens
                     TerminalBuffer.append(INFER, ...)
                              │
                              ▼
                     Response completa → POST resultado a Core
```

### 8.3 BLE Wake Flow (cuando DORMANT)

```
PC (GIMO Core)
  │
  │ BLE Advertisement:
  │ Manufacturer Data = [timestamp(4B) + counter(4B) + HMAC(16B)]
  │
  ▼
Android BLE HW (ScanFilter match on manufacturer ID)
  │
  │ PendingIntent fired
  ▼
BleWakeReceiver.onReceive()
  │
  ├── WakeTokenVerifier.verify(manufacturerData)
  │   ├── Reject if timestamp > 60s old
  │   ├── Reject if counter <= lastSeen
  │   └── Verify HMAC-SHA256-128(psk, timestamp || counter)
  │
  ├── OK → NotificationManager.notify("GIMO needs your device")
  │         Action button: "Start Mesh" → launches app → ACTIVE
  │
  └── FAIL → Log + ignore (no notification, no wake)
```

---

## 9. API Contract (app ↔ GIMO Core)

### 9.1 Endpoints consumidos por la app

| Endpoint | Método | Frecuencia | Propósito |
|----------|--------|------------|-----------|
| `/ops/mesh/heartbeat` | POST | 30s (ACTIVE) | Enviar telemetría, recibir estado |
| `/ops/mesh/status` | GET | 60s | Fleet overview para mini graph |
| `/ops/mesh/devices` | GET | 60s | Lista de nodos para mini graph |
| `/ops/mesh/devices/{id}` | GET | On-demand | Detalle propio |
| `/ops/mesh/profiles/{id}` | GET | 5min | Perfil térmico propio |
| `/ops/mesh/thermal-history` | GET | On-demand | Historial térmico |
| `/ops/mesh/thermal-event` | POST | On-event | Reportar evento térmico |

### 9.2 Endpoints consumidos del llama-server local

| Endpoint | Método | Propósito |
|----------|--------|-----------|
| `/v1/chat/completions` | POST (stream) | Inferencia con streaming |
| `/health` | GET | Health check del servidor |
| `/v1/models` | GET | Modelo cargado |

---

## 10. Componentes Clave

### 10.1 MeshGraphView (Canvas)

Representación visual simplificada del mesh. No usa librería de grafos — Canvas puro.

```kotlin
@Composable
fun MeshGraphView(
    devices: List<MeshDevice>,
    currentDeviceId: String,
    modifier: Modifier = Modifier
) {
    // Layout: LR (left-to-right)
    // Nodos posicionados en grid simple:
    //   - Server mode → izquierda
    //   - Inference/utility → derecha
    //   - Current device → resaltado con glow
    //
    // Visual:
    //   - Nodo = RoundedRect 48x48dp con icono centrado
    //   - Edge = línea con dash animado si connected
    //   - Current = border accent-primary + glow-breath animation
    //   - Offline = opacity 0.3, border dashed
    //
    // Colores: MeshModeColors por device_mode
    // Iconos: Monitor (server), Smartphone (phone), Cpu (utility)
}
```

### 10.2 HealthRing

```kotlin
@Composable
fun HealthRing(
    score: Float,         // 0-100
    modifier: Modifier = Modifier
) {
    // Canvas drawArc:
    //   - Track: surface3, 12dp stroke, 270° sweep
    //   - Fill: colored arc, animated sweep
    //   - Color: trust >70, warning 40-70, alert <40
    //   - Center text: score en GimoMono 48sp
    //   - Sublabel: "HEALTH" 10sp uppercase
    //   - Animation: animateFloatAsState con spring
}
```

### 10.3 KillSwitch

```kotlin
@Composable
fun KillSwitch(
    isRunning: Boolean,
    onStop: () -> Unit,
    onStart: () -> Unit
) {
    // Long-press detector (2000ms)
    // Visual states:
    //   Running → "STOP MESH NODE" en rojo
    //     - Border: alert/50
    //     - During hold: circular progress overlay llenándose
    //     - Complete: haptic + flash animation
    //   Stopped → "START MESH NODE" en verde
    //     - Border: trust/50
    //     - Single tap
}
```

### 10.4 JsonViewer

```kotlin
@Composable
fun JsonViewer(
    json: String,
    collapsed: Boolean = true,
    modifier: Modifier = Modifier
) {
    // Syntax highlighting:
    //   Keys: accent-primary (azul)
    //   Strings: trust (teal)
    //   Numbers: approval (dorado)
    //   Booleans: warning (naranja)
    //   Null: text-tertiary
    //   Brackets: text-secondary
    //
    // Collapsible con animación expand/collapse
    // Font: GimoMono, 11sp
    // Background: surface0
    // Scroll horizontal si líneas largas
}
```

---

## 11. Gestión de Procesos Nativos

La app gestiona `llama-server` como proceso nativo:

```kotlin
class InferenceService {
    private var process: Process? = null

    fun start(modelPath: String, port: Int = 8080, threads: Int = 4) {
        // 1. Copy binary from assets to filesDir (first run only)
        // 2. Set LD_LIBRARY_PATH
        // 3. ProcessBuilder:
        //    ./llama-server -m $modelPath -c 2048 --host 0.0.0.0 --port $port -t $threads
        // 4. Redirect stdout/stderr → TerminalBuffer (INFER source)
        // 5. Health check loop: GET :8080/health cada 5s
    }

    fun stop() {
        process?.destroyForcibly()
        process = null
    }

    val isRunning: Boolean get() = process?.isAlive == true
}
```

**Binarios embebidos en la app**:
- `llama-server` (arm64-v8a, ~99MB) en `assets/` o descargado on-demand
- `lib*.so` (5 libs) en `jniLibs/arm64-v8a/`
- Modelo GGUF **NO** embebido — seleccionado por el usuario desde storage

---

## 12. Notificaciones

### 12.1 BLE Wake Notification (DORMANT → usuario decide)

```
╔══════════════════════════════════════╗
║  GIMO Mesh                          ║
║  Your device is needed for          ║
║  inference work.                    ║
║                                     ║
║  [Dismiss]          [Start Mesh]    ║
╚══════════════════════════════════════╝
```

### 12.2 Foreground Service Notification (ACTIVE)

```
╔══════════════════════════════════════╗
║  GIMO Mesh ● Active                 ║
║  qwen2.5:3b │ CPU 23% │ 42°C       ║
║                          [Stop]     ║
╚══════════════════════════════════════╝
```

### 12.3 Thermal Warning

```
╔══════════════════════════════════════╗
║  ⚠ GIMO Mesh — Thermal Warning     ║
║  CPU temperature 68°C.              ║
║  Inference paused until cooldown.   ║
╚══════════════════════════════════════╝
```

---

## 13. Build & Distribution

| Aspecto | Decisión |
|---------|----------|
| Min SDK | 28 (Android 9) — cubre S10 |
| Target SDK | 34 (Android 14) |
| APK size | ~110MB (99MB llama-server + 10MB app + 1MB libs) |
| Distribución | Sideload via ADB (no Play Store) |
| Signing | Debug key (desarrollo), self-signed release key |
| ProGuard | Habilitado para release (ofusca Kotlin, no toca JNI) |

---

## 14. Fases de Implementación

### Fase 1 — Skeleton (1 sesión)
- Proyecto Android Studio, theme GIMO, navegación bottom tabs
- DashboardScreen con datos mock
- HealthRing, MetricCards, ThermalStrip
- SettingsScreen con DataStore

### Fase 2 — Conectividad (1 sesión)
- GimoCoreClient (OkHttp + auth)
- MetricsCollector (port de android_metrics.py)
- MeshAgentService (Foreground Service + heartbeats)
- Dashboard con datos reales

### Fase 3 — Terminal + Agent (1 sesión)
- TerminalBuffer + TerminalScreen
- InferenceService (gestión de llama-server)
- AgentScreen + TaskCard + JsonViewer
- InferenceStream (SSE)

### Fase 4 — BLE Wake (1 sesión)
- WakeScanner + PendingIntent registration
- WakeTokenVerifier (HMAC-SHA256)
- BootReceiver
- Advertiser en PC (Python/C#)

### Fase 5 — Mesh Graph + Polish (1 sesión)
- MeshGraphView (Canvas)
- KillSwitch con long-press
- Animations (glow-breath, spring gauges)
- Notificaciones (wake, foreground, thermal)

---

## 15. Dependencias

```kotlin
// build.gradle.kts
dependencies {
    // Compose BOM
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.8.5")

    // Networking
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // DataStore
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    // Lifecycle (Foreground Service)
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")

    // No Hilt, no Room, no Retrofit — keep it minimal
}
```

**Total de dependencias externas**: 7 (+ Compose BOM). App mínima.
