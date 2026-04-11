package com.gredinlabs.gimomesh.ui.dashboard

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.cos
import kotlin.math.sin
import com.gredinlabs.gimomesh.data.model.ConnectionState
import com.gredinlabs.gimomesh.data.model.MeshState
import com.gredinlabs.gimomesh.data.model.OperationalState
import com.gredinlabs.gimomesh.ui.components.StatusDot
import com.gredinlabs.gimomesh.ui.graph.GraphOverlay
import com.gredinlabs.gimomesh.ui.graph.PlanGraphView
import com.gredinlabs.gimomesh.ui.theme.*

@Composable
fun DashboardScreen(
    state: MeshState,
    onToggleMesh: () -> Unit,
    onModeChange: (String) -> Unit = {},
    modeLocked: Boolean = false,
    onToggleModeLock: (Boolean) -> Unit = {},
    modifier: Modifier = Modifier,
) {
    var graphOverlayVisible by remember { mutableStateOf(false) }

    Box(modifier = modifier.fillMaxSize()) {
        Crossfade(
            targetState = state.operationalState == OperationalState.BUSY,
            animationSpec = tween(300),
            label = "dashMode",
        ) { isBusy ->
            if (isBusy) {
                BlackoutView(state = state, onToggleMesh = onToggleMesh)
            } else {
                InstrumentView(
                    state = state,
                    onToggleMesh = onToggleMesh,
                    onModeChange = onModeChange,
                    modeLocked = modeLocked,
                    onToggleModeLock = onToggleModeLock,
                    onExpandGraph = { graphOverlayVisible = true },
                )
            }
        }

        // Fullscreen graph overlay
        GraphOverlay(
            nodes = state.planNodes,
            visible = graphOverlayVisible,
            onDismiss = { graphOverlayVisible = false },
        )
    }
}

@Composable
private fun InstrumentView(
    state: MeshState,
    onToggleMesh: () -> Unit,
    onModeChange: (String) -> Unit = {},
    modeLocked: Boolean = false,
    onToggleModeLock: (Boolean) -> Unit = {},
    onExpandGraph: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
    ) {
        // App Header — edge-to-edge bar
        AppHeader(
            state = state,
            onModeChange = onModeChange,
            modeLocked = modeLocked,
            onToggleModeLock = onToggleModeLock,
        )

        // Content with horizontal padding
        Column(modifier = Modifier.padding(horizontal = 14.dp)) {

        // Status Strip (Connection + Health merged)
        StatusStrip(
            coreUrl = state.coreUrl,
            isLinked = state.isLinked,
            healthScore = state.healthScore,
        )
        Spacer(Modifier.height(7.dp))

        // Plan Graph
        PlanGraphView(
            nodes = state.planNodes,
            onNodeClick = { /* node tap in compact view — no-op */ },
            onExpandClick = onExpandGraph,
        )
        Spacer(Modifier.height(7.dp))

        // Metrics
        MetricsRow(
            cpuPercent = state.cpuPercent,
            ramPercent = state.ramPercent,
            batteryPercent = state.batteryPercent,
            isMeshRunning = state.isMeshRunning,
        )
        Spacer(Modifier.height(7.dp))

        // Thermal
        ThermalStrip(
            cpuTempC = state.cpuTempC,
            gpuTempC = state.gpuTempC,
            batteryTempC = state.batteryTempC,
            thermalStatus = state.thermalStatus,
        )
        Spacer(Modifier.height(7.dp))

        // Model
        ModelCard(
            modelName = state.modelLoaded,
            inferenceRunning = state.inferenceRunning,
            inferencePort = state.inferencePort,
            endpoint = state.inferenceEndpoint,
            params = state.modelParams,
            quantization = state.quantization,
            throughput = state.throughput,
        )

        // Kill Switch
        KillSwitch(
            isMeshRunning = state.isMeshRunning,
            onToggle = onToggleMesh,
        )

        Spacer(Modifier.height(20.dp))
        } // inner padding Column
    }
}

@Composable
private fun AppHeader(
    state: MeshState,
    onModeChange: (String) -> Unit = {},
    modeLocked: Boolean = false,
    onToggleModeLock: (Boolean) -> Unit = {},
) {
    val modes = listOf("inference", "utility", "server", "hybrid")
    var showDropdown by remember { mutableStateOf(false) }
    var pendingMode by remember { mutableStateOf<String?>(null) }

    val currentModeName = state.deviceMode.name.lowercase()
    val modeColor = modeColor(currentModeName)
    val pillColor = if (modeLocked) GimoAccents.warning else modeColor

    // ── Header bar — differentiated background ──
    Column {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(GimoSurfaces.surface3)
            .padding(horizontal = 14.dp, vertical = 10.dp),
    ) {
        // Left — Logo
        MeshLogo(
            size = 26.dp,
            modifier = Modifier.align(Alignment.CenterStart),
        )

        // Center — App name
        Row(
            modifier = Modifier.align(Alignment.Center),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "GIMO",
                fontFamily = GimoDisplay,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp,
                letterSpacing = 1.5.sp,
                color = GimoText.primary,
            )
            Spacer(Modifier.width(5.dp))
            Text(
                text = "MESH",
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 14.sp,
                letterSpacing = 1.5.sp,
                color = GimoText.tertiary,
            )
        }

        // Right — Status + Mode pill
        Box(modifier = Modifier.align(Alignment.CenterEnd)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                val dotColor = when (state.connectionState) {
                    ConnectionState.CONNECTED,
                    ConnectionState.APPROVED -> GimoAccents.green
                    ConnectionState.RECONNECTING,
                    ConnectionState.PENDING_APPROVAL,
                    ConnectionState.DISCOVERABLE -> GimoAccents.amber
                    ConnectionState.THERMAL_LOCKOUT,
                    ConnectionState.REFUSED -> GimoAccents.alert
                    ConnectionState.OFFLINE -> GimoText.tertiary
                }
                StatusDot(
                    color = dotColor,
                    size = 5.dp,
                    animated = state.connectionState != ConnectionState.OFFLINE &&
                            state.connectionState != ConnectionState.REFUSED,
                )
                Spacer(Modifier.width(7.dp))

                // Mode pill — clickable with generous touch target
                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(pillColor.copy(alpha = 0.1f))
                        .border(1.dp, pillColor.copy(alpha = 0.2f), RoundedCornerShape(6.dp))
                        .clickable { showDropdown = !showDropdown }
                        .padding(horizontal = 10.dp, vertical = 7.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (modeLocked) {
                        LockIcon(size = 10.dp, color = GimoAccents.warning, locked = true)
                        Spacer(Modifier.width(5.dp))
                    }
                    Text(
                        text = currentModeName.uppercase(),
                        fontFamily = GimoMono,
                        fontWeight = FontWeight.Medium,
                        fontSize = 9.sp,
                        letterSpacing = 0.7.sp,
                        color = pillColor,
                    )
                }
            }

            // Dropdown
            DropdownMenu(
                expanded = showDropdown,
                onDismissRequest = { showDropdown = false },
                modifier = Modifier
                    .background(GimoSurfaces.surface2)
                    .width(150.dp),
            ) {
                modes.forEach { mode ->
                    val isSelected = mode == currentModeName
                    val mc = modeColor(mode)
                    val enabled = !modeLocked || isSelected
                    val bg = when {
                        isSelected -> mc.copy(alpha = 0.12f)
                        else -> GimoSurfaces.surface2
                    }
                    val textColor = when {
                        isSelected -> mc
                        !enabled -> GimoText.tertiary.copy(alpha = 0.35f)
                        else -> GimoText.secondary
                    }

                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(bg)
                            .then(
                                if (enabled) Modifier.clickable {
                                    showDropdown = false
                                    if (!isSelected) {
                                        if (state.isMeshRunning && state.operationalState == OperationalState.BUSY) {
                                            pendingMode = mode
                                        } else {
                                            onModeChange(mode)
                                        }
                                    }
                                } else Modifier
                            )
                            .padding(horizontal = 12.dp, vertical = 11.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            // Mode color dot
                            Canvas(modifier = Modifier.size(6.dp)) {
                                drawCircle(
                                    color = if (enabled) mc else mc.copy(alpha = 0.2f),
                                )
                            }
                            Spacer(Modifier.width(8.dp))
                            Text(
                                text = mode.uppercase(),
                                fontFamily = GimoMono,
                                fontSize = 10.sp,
                                fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                                letterSpacing = 0.8.sp,
                                color = textColor,
                            )
                        }

                        // Lock toggle on the selected mode row
                        if (isSelected) {
                            Box(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(4.dp))
                                    .clickable { onToggleModeLock(!modeLocked) }
                                    .padding(4.dp),
                            ) {
                                LockIcon(
                                    size = 12.dp,
                                    color = if (modeLocked) GimoAccents.warning else GimoText.tertiary,
                                    locked = modeLocked,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
    // Bottom border — subtle separator
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(GimoBorders.primary),
    )
    } // Column

    // Confirmation dialog when device is busy
    if (pendingMode != null) {
        AlertDialog(
            onDismissRequest = { pendingMode = null },
            title = {
                Text(
                    "Change mode?",
                    fontFamily = GimoSans,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp,
                )
            },
            text = {
                Text(
                    "GIMO is using this device. Changing mode will interrupt the current task.",
                    fontFamily = GimoSans,
                    fontSize = 12.sp,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    pendingMode?.let { onModeChange(it) }
                    pendingMode = null
                }) {
                    Text("CHANGE", color = GimoAccents.alert, fontFamily = GimoMono, fontSize = 10.sp)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingMode = null }) {
                    Text("CANCEL", color = GimoText.secondary, fontFamily = GimoMono, fontSize = 10.sp)
                }
            },
            containerColor = GimoSurfaces.surface1,
            titleContentColor = GimoText.primary,
            textContentColor = GimoText.secondary,
        )
    }
}

/** Canvas-drawn lock icon matching GIMO visual identity. */
@Composable
private fun LockIcon(
    size: Dp,
    color: Color,
    locked: Boolean,
    modifier: Modifier = Modifier,
) {
    Canvas(modifier = modifier.size(size)) {
        val w = this.size.width
        val h = this.size.height
        val stroke = w * 0.14f

        // Shackle (arc)
        val shackleWidth = w * 0.5f
        val shackleHeight = h * 0.38f
        val shackleLeft = (w - shackleWidth) / 2f
        val shackleTop = h * 0.05f

        if (locked) {
            // Closed shackle — full arc
            drawArc(
                color = color,
                startAngle = 180f,
                sweepAngle = 180f,
                useCenter = false,
                topLeft = Offset(shackleLeft, shackleTop),
                size = Size(shackleWidth, shackleHeight * 2),
                style = Stroke(width = stroke, cap = StrokeCap.Round),
            )
        } else {
            // Open shackle — left side arc + gap on right
            drawArc(
                color = color,
                startAngle = 180f,
                sweepAngle = 140f,
                useCenter = false,
                topLeft = Offset(shackleLeft, shackleTop),
                size = Size(shackleWidth, shackleHeight * 2),
                style = Stroke(width = stroke, cap = StrokeCap.Round),
            )
        }

        // Body (rounded rect)
        val bodyTop = h * 0.42f
        val bodyHeight = h * 0.53f
        drawRoundRect(
            color = color,
            topLeft = Offset(w * 0.15f, bodyTop),
            size = Size(w * 0.7f, bodyHeight),
            cornerRadius = CornerRadius(w * 0.08f),
        )

        // Keyhole dot
        val dotRadius = w * 0.07f
        drawCircle(
            color = GimoSurfaces.surface2,
            radius = dotRadius,
            center = Offset(w / 2f, bodyTop + bodyHeight * 0.4f),
        )
    }
}

private fun modeColor(mode: String): Color = when (mode) {
    "inference" -> MeshModeColors.inference
    "utility" -> MeshModeColors.utility
    "server" -> MeshModeColors.server
    "hybrid" -> MeshModeColors.hybrid
    else -> GimoAccents.primary
}

/**
 * GIMO Mesh logo — hexagon (Gred In Labs ecosystem) with internal mesh nodes.
 * Drawn entirely with Canvas: hexagonal outline + 3 connected nodes inside.
 */
@Composable
private fun MeshLogo(
    size: Dp,
    modifier: Modifier = Modifier,
) {
    val teal = GimoAccents.trust       // 0xFF5A9F8F
    val blue = GimoAccents.primary     // 0xFF3B82F6

    Canvas(modifier = modifier.size(size)) {
        val w = this.size.width
        val h = this.size.height
        val cx = w / 2f
        val cy = h / 2f
        val r = w * 0.46f // hexagon radius
        val hexStroke = w * 0.055f

        // --- Hexagon outline ---
        val hexPath = Path()
        for (i in 0..5) {
            val angle = Math.toRadians((60.0 * i) - 90.0)
            val px = cx + r * cos(angle).toFloat()
            val py = cy + r * sin(angle).toFloat()
            if (i == 0) hexPath.moveTo(px, py) else hexPath.lineTo(px, py)
        }
        hexPath.close()
        drawPath(
            path = hexPath,
            color = teal,
            style = Stroke(width = hexStroke, cap = StrokeCap.Round, join = StrokeJoin.Round),
        )

        // --- 3 mesh nodes inside (triangle formation) ---
        val nodeR = w * 0.05f
        val meshR = r * 0.42f // inner triangle radius
        val nodes = listOf(
            // top node — offset slightly from exact top for visual balance
            Offset(cx, cy - meshR * 0.9f),
            // bottom-left
            Offset(cx - meshR * 0.85f, cy + meshR * 0.55f),
            // bottom-right
            Offset(cx + meshR * 0.85f, cy + meshR * 0.55f),
        )
        val lineStroke = w * 0.035f

        // Connect nodes with lines
        for (i in nodes.indices) {
            val from = nodes[i]
            val to = nodes[(i + 1) % nodes.size]
            drawLine(
                color = blue.copy(alpha = 0.5f),
                start = from,
                end = to,
                strokeWidth = lineStroke,
                cap = StrokeCap.Round,
            )
        }

        // Draw node dots on top
        nodes.forEachIndexed { idx, pos ->
            val nodeColor = when (idx) {
                0 -> teal
                1 -> blue
                else -> teal.copy(red = teal.red * 0.8f + blue.red * 0.2f)
            }
            drawCircle(color = nodeColor, radius = nodeR, center = pos)
        }

        // Center dot — the orchestrator
        drawCircle(
            color = GimoText.primary.copy(alpha = 0.4f),
            radius = nodeR * 0.6f,
            center = Offset(cx, cy + meshR * 0.07f),
        )
    }
}

@Composable
private fun BlackoutView(
    state: MeshState,
    onToggleMesh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // STATIC layout — zero animation, zero recomposition triggers
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 14.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = if (state.tokensPerSecond > 0f) "%.1f".format(state.tokensPerSecond) else "—",
            fontFamily = GimoMono,
            fontWeight = FontWeight.Light,
            fontSize = 48.sp,
            color = GimoAccents.trust,
        )
        Text(
            text = "tok/s",
            fontFamily = GimoMono,
            fontWeight = FontWeight.Medium,
            fontSize = 10.sp,
            letterSpacing = 1.sp,
            color = GimoText.tertiary,
        )
        Spacer(Modifier.height(24.dp))
        Text(
            text = state.modelLoaded,
            fontFamily = GimoMono,
            fontSize = 14.sp,
            color = GimoText.secondary,
        )
        Text(
            text = "task ${state.activeTaskId}",
            fontFamily = GimoMono,
            fontSize = 11.sp,
            color = GimoText.tertiary,
        )
        Text(
            text = "${state.tokensGenerated} tokens generated",
            fontFamily = GimoMono,
            fontSize = 11.sp,
            color = GimoText.tertiary,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = "elapsed: ${state.elapsedFormatted}",
            fontFamily = GimoMono,
            fontSize = 11.sp,
            color = GimoText.tertiary,
        )

        Spacer(Modifier.height(40.dp))

        KillSwitch(
            isMeshRunning = state.isMeshRunning,
            onToggle = onToggleMesh,
        )
    }
}
