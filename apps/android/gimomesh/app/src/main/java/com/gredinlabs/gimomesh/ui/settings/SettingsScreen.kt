package com.gredinlabs.gimomesh.ui.settings

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInParent
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.data.model.MeshState
import com.gredinlabs.gimomesh.data.store.SettingsStore
import com.gredinlabs.gimomesh.ui.components.GimoIcons
import com.gredinlabs.gimomesh.ui.theme.*
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(
    state: MeshState,
    settings: SettingsStore.Settings,
    settingsStore: SettingsStore,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 14.dp)
    ) {
        // Header
        Text(
            text = "Settings",
            fontFamily = GimoDisplay,
            fontWeight = FontWeight.Bold,
            fontSize = 14.sp,
            letterSpacing = 0.5.sp,
            color = GimoText.primary,
            modifier = Modifier.padding(vertical = 10.dp),
        )

        // Connection
        SettingsGroup("Connection") {
            SettingsRow("Core URL", settings.coreUrl.replace(Regex("\\d+\\.\\d+\\.\\d+"), "•••.•••.•"), isMasked = true)
            SettingsRow(
                "Token",
                if (settings.token.isEmpty()) "not set" else "••••${settings.token.takeLast(4)}",
                isMasked = true,
            )
            SettingsRow("Device ID", settings.deviceId.ifEmpty { state.deviceId })
            SettingsRow("Device Name", settings.deviceName.ifEmpty { state.deviceName }, isLast = true)
        }

        SettingsGroup("Local Host") {
            SettingsRow(
                "Runtime",
                state.hostRuntimeStatus,
                valueColor = when (state.hostRuntimeStatus) {
                    "ready" -> GimoAccents.green
                    "degraded", "starting" -> GimoAccents.warning
                    "error", "unavailable" -> GimoAccents.alert
                    else -> GimoText.tertiary
                },
            )
            SettingsRow("Control URL", if (state.hostRuntimeAvailable) "127.0.0.1:9325" else "disabled")
            SettingsRow("LAN URL", state.hostLanUrl.ifBlank { "not published" })
            SettingsRow("Web UI", state.hostWebUrl.ifBlank { "unavailable" })
            SettingsRow("MCP", state.hostMcpUrl.ifBlank { "unavailable" })
            SettingsRow("Runtime Error", state.hostRuntimeError.ifBlank { "none" }, isLast = true)
        }

        // Mesh Node
        SettingsGroup("Mesh Node") {
            SettingsRow("Model", settings.model)
            SettingsRow("Inference Port", settings.inferencePort.toString())
            SettingsRow("Threads", settings.threads.toString())
            SettingsRow("Context Size", settings.contextSize.toString())
            SettingsRowToggle(
                "Auto-start when safe",
                settings.inferenceAutoStartAllowed,
                onToggle = { enabled ->
                    scope.launch { settingsStore.updateInferenceAutoStartAllowed(enabled) }
                },
                isLast = true,
            )
        }

        // Hybrid Mode Configuration
        HybridCapabilitiesSection(
            settings = settings,
            onToggleAuto = { scope.launch { settingsStore.updateHybridAuto(it) } },
            onToggleInference = { scope.launch { settingsStore.updateHybridInference(it) } },
            onToggleUtility = { scope.launch { settingsStore.updateHybridUtility(it) } },
            onToggleServe = { scope.launch { settingsStore.updateHybridServe(it) } },
        )

        // BLE Wake
        SettingsGroup("BLE Wake") {
            SettingsRowToggle(
                "Enable BLE Wake",
                settings.bleWakeEnabled,
                onToggle = { enabled ->
                    scope.launch { settingsStore.updateBleWakeEnabled(enabled) }
                },
            )
            SettingsRow(
                "Wake Key",
                if (settings.bleWakeKey.isEmpty()) "not set" else "••••••••••••",
                isMasked = true,
            )
            SettingsRow("Scan Mode", "Low Power", isLast = true)
        }

        // Thermal Limits
        SettingsGroup("Thermal Limits") {
            SettingsRow("CPU Warning", "${settings.cpuWarningTemp}°C", valueColor = GimoAccents.warning)
            SettingsRow("CPU Lockout", "${settings.cpuLockoutTemp}°C", valueColor = GimoAccents.alert)
            SettingsRow("Battery Warning", "${settings.batteryWarningTemp}°C", valueColor = GimoAccents.warning)
            SettingsRow("Battery Lockout", "${settings.batteryLockoutTemp}°C", valueColor = GimoAccents.alert)
            SettingsRow("Min Battery", "${settings.minBatteryPercent}%", isLast = true)
        }

        // Runtime
        SettingsGroup("Runtime") {
            SettingsRow("Connection", state.connectionState.name.lowercase(), valueColor = when (state.connectionState) {
                com.gredinlabs.gimomesh.data.model.ConnectionState.CONNECTED,
                com.gredinlabs.gimomesh.data.model.ConnectionState.APPROVED -> GimoAccents.green
                com.gredinlabs.gimomesh.data.model.ConnectionState.RECONNECTING,
                com.gredinlabs.gimomesh.data.model.ConnectionState.PENDING_APPROVAL,
                com.gredinlabs.gimomesh.data.model.ConnectionState.DISCOVERABLE -> GimoAccents.warning
                com.gredinlabs.gimomesh.data.model.ConnectionState.THERMAL_LOCKOUT,
                com.gredinlabs.gimomesh.data.model.ConnectionState.REFUSED -> GimoAccents.alert
                com.gredinlabs.gimomesh.data.model.ConnectionState.OFFLINE -> GimoText.tertiary
            })
            SettingsRow("Health Score", "${state.healthScore.toInt()}%")
            SettingsRow("Thermal Status", state.thermalStatus, valueColor = when (state.thermalStatus) {
                "OK" -> GimoAccents.trust
                "WARNING" -> GimoAccents.warning
                else -> GimoAccents.alert
            }, isLast = true)
        }

        // About
        SettingsGroup("About") {
            SettingsRow("Version", "1.0.0")
            SettingsRow("Agent", "mesh_agent_lite 0.1")
            SettingsRow("llama.cpp", "b4567", isLast = true)
        }

        Spacer(Modifier.height(20.dp))
    }
}

@Composable
private fun SettingsGroup(
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(modifier = Modifier.padding(bottom = 14.dp)) {
        Text(
            text = title.uppercase(),
            fontFamily = GimoMono,
            fontWeight = FontWeight.Medium,
            fontSize = 7.5.sp,
            letterSpacing = 1.2.sp,
            color = GimoText.tertiary,
            modifier = Modifier.padding(start = 2.dp, bottom = 5.dp),
        )
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(GimoSurfaces.surface1)
                .border(1.dp, GimoBorders.primary, RoundedCornerShape(8.dp)),
            content = content,
        )
    }
}

@Composable
private fun SettingsRow(
    label: String,
    value: String,
    valueColor: Color = GimoText.secondary,
    isMasked: Boolean = false,
    isLast: Boolean = false,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (!isLast) Modifier.borderBottom() else Modifier)
            .padding(horizontal = 10.dp, vertical = 9.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            fontFamily = GimoSans,
            fontSize = 12.sp,
            color = GimoText.primary,
        )
        Text(
            text = value,
            fontFamily = GimoMono,
            fontSize = 11.sp,
            color = valueColor,
            letterSpacing = if (isMasked) 1.2.sp else 0.sp,
            maxLines = 1,
        )
    }
}

@Composable
private fun SettingsRowToggle(
    label: String,
    isOn: Boolean,
    onToggle: (Boolean) -> Unit,
    isLast: Boolean = false,
    enabled: Boolean = true,
) {
    val labelColor = if (enabled) GimoText.primary else GimoText.tertiary.copy(alpha = 0.5f)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (!isLast) Modifier.borderBottom() else Modifier)
            .padding(horizontal = 10.dp, vertical = 9.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            fontFamily = GimoSans,
            fontSize = 12.sp,
            color = labelColor,
        )
        GimoToggle(isOn = isOn, onToggle = { if (enabled) onToggle(!isOn) }, enabled = enabled)
    }
}

@Composable
private fun GimoToggle(isOn: Boolean, onToggle: () -> Unit, enabled: Boolean = true) {
    val bgColor = when {
        !enabled -> GimoSurfaces.surface3.copy(alpha = 0.5f)
        isOn -> GimoAccents.primary
        else -> GimoSurfaces.surface3
    }
    val knobOffset = if (isOn) 16.dp else 0.dp

    Box(
        modifier = Modifier
            .width(38.dp)
            .height(22.dp)
            .clip(RoundedCornerShape(11.dp))
            .background(bgColor)
            .clickable(onClick = onToggle)
            .padding(3.dp),
    ) {
        Box(
            modifier = Modifier
                .size(16.dp)
                .offset(x = knobOffset)
                .clip(CircleShape)
                .background(GimoText.primary)
        )
    }
}

@Composable
private fun HybridCapabilitiesSection(
    settings: SettingsStore.Settings,
    onToggleAuto: (Boolean) -> Unit,
    onToggleInference: (Boolean) -> Unit,
    onToggleUtility: (Boolean) -> Unit,
    onToggleServe: (Boolean) -> Unit,
) {
    val activeCount = listOf(settings.hybridInference, settings.hybridUtility, settings.hybridServe)
        .count { it }
    val isHybrid = activeCount >= 2 && !settings.hybridAuto

    val pillCenters = remember { mutableStateMapOf<Int, Float>() }
    val teal = Color(0xFF5A9F8F)
    val green = Color(0xFF22C55E)

    Column(modifier = Modifier.padding(bottom = 14.dp)) {
        // Title — gradient text when HYBRID or AUTO
        if (isHybrid) {
            Text(
                text = "HYBRID",
                fontFamily = GimoDisplay,
                fontWeight = FontWeight.Bold,
                fontSize = 13.sp,
                letterSpacing = 3.sp,
                style = androidx.compose.ui.text.TextStyle(
                    brush = Brush.horizontalGradient(listOf(teal, green)),
                ),
                modifier = Modifier.padding(start = 2.dp, bottom = 5.dp),
            )
        } else if (settings.hybridAuto) {
            Text(
                text = "AUTO",
                fontFamily = GimoDisplay,
                fontWeight = FontWeight.Bold,
                fontSize = 13.sp,
                letterSpacing = 3.sp,
                style = androidx.compose.ui.text.TextStyle(
                    brush = Brush.horizontalGradient(
                        listOf(GimoAccents.primary, GimoAccents.purple),
                    ),
                ),
                modifier = Modifier.padding(start = 2.dp, bottom = 5.dp),
            )
        } else {
            Text(
                text = "HYBRID CAPABILITIES",
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 7.5.sp,
                letterSpacing = 1.2.sp,
                color = GimoText.tertiary,
                modifier = Modifier.padding(start = 2.dp, bottom = 5.dp),
            )
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(GimoSurfaces.surface1)
                .border(
                    1.dp,
                    when {
                        isHybrid -> teal.copy(alpha = 0.25f)
                        settings.hybridAuto -> GimoAccents.primary.copy(alpha = 0.25f)
                        else -> GimoBorders.primary
                    },
                    RoundedCornerShape(8.dp),
                )
                .then(
                    if (isHybrid) Modifier.drawBehind {
                        drawLine(
                            brush = Brush.horizontalGradient(
                                colors = listOf(
                                    Color.Transparent,
                                    teal.copy(alpha = 0.5f),
                                    lerp(teal, green, 0.5f).copy(alpha = 0.6f),
                                    green.copy(alpha = 0.5f),
                                    Color.Transparent,
                                ),
                            ),
                            start = Offset(size.width * 0.1f, 0f),
                            end = Offset(size.width * 0.9f, 0f),
                            strokeWidth = 1.5.dp.toPx(),
                        )
                    } else if (settings.hybridAuto) Modifier.drawBehind {
                        drawLine(
                            brush = Brush.horizontalGradient(
                                colors = listOf(
                                    Color.Transparent,
                                    GimoAccents.primary.copy(alpha = 0.5f),
                                    GimoAccents.purple.copy(alpha = 0.5f),
                                    Color.Transparent,
                                ),
                            ),
                            start = Offset(size.width * 0.1f, 0f),
                            end = Offset(size.width * 0.9f, 0f),
                            strokeWidth = 1.5.dp.toPx(),
                        )
                    } else Modifier
                )
                .padding(12.dp),
        ) {
            Box(modifier = Modifier.fillMaxWidth()) {
                // ── Gradient connecting line ──
                if (isHybrid) {
                    val activeIndices = mutableListOf<Int>()
                    if (settings.hybridInference) activeIndices.add(1)
                    if (settings.hybridUtility) activeIndices.add(2)
                    if (settings.hybridServe) activeIndices.add(3)

                    if (activeIndices.size >= 2) {
                        val firstX = pillCenters[activeIndices.first()]
                        val lastX = pillCenters[activeIndices.last()]

                        if (firstX != null && lastX != null) {
                            Canvas(modifier = Modifier.matchParentSize()) {
                                val lineY = size.height * 0.22f

                                // Glow
                                drawLine(
                                    brush = Brush.horizontalGradient(
                                        colors = listOf(teal.copy(alpha = 0.15f), green.copy(alpha = 0.15f)),
                                        startX = firstX, endX = lastX,
                                    ),
                                    start = Offset(firstX, lineY),
                                    end = Offset(lastX, lineY),
                                    strokeWidth = 10.dp.toPx(),
                                    cap = StrokeCap.Round,
                                )
                                // Main line
                                drawLine(
                                    brush = Brush.horizontalGradient(
                                        colors = listOf(teal, green),
                                        startX = firstX, endX = lastX,
                                    ),
                                    start = Offset(firstX, lineY),
                                    end = Offset(lastX, lineY),
                                    strokeWidth = 2.dp.toPx(),
                                    cap = StrokeCap.Round,
                                )
                                // Junction dots
                                for (idx in activeIndices) {
                                    val cx = pillCenters[idx] ?: continue
                                    val t = if (lastX > firstX) (cx - firstX) / (lastX - firstX) else 0f
                                    val dotColor = lerp(teal, green, t)
                                    drawCircle(dotColor.copy(alpha = 0.25f), radius = 6.dp.toPx(), center = Offset(cx, lineY))
                                    drawCircle(dotColor, radius = 3.dp.toPx(), center = Offset(cx, lineY))
                                }
                            }
                        }
                    }
                }

                // ── Pills ──
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    CapabilityPill(
                        icon = { s, c -> GimoIcons.Auto(size = s, color = c) },
                        label = "Auto",
                        accentColor = GimoAccents.primary,
                        isOn = settings.hybridAuto,
                        dimmed = isHybrid,
                        onToggle = {
                            onToggleAuto(true)
                            onToggleInference(false)
                            onToggleUtility(false)
                            onToggleServe(false)
                        },
                        modifier = Modifier
                            .weight(1f)
                            .onGloballyPositioned {
                                pillCenters[0] = it.positionInParent().x + it.size.width / 2f
                            },
                    )
                    CapabilityPill(
                        icon = { s, c -> GimoIcons.Brain(size = s, color = c) },
                        label = "Inference",
                        accentColor = MeshModeColors.inference,
                        isOn = settings.hybridInference && !settings.hybridAuto,
                        dimmed = settings.hybridAuto,
                        onToggle = {
                            val newVal = !settings.hybridInference
                            onToggleInference(newVal)
                            if (newVal) onToggleAuto(false)
                            if (!newVal && !settings.hybridUtility && !settings.hybridServe) onToggleAuto(true)
                        },
                        modifier = Modifier
                            .weight(1f)
                            .onGloballyPositioned {
                                pillCenters[1] = it.positionInParent().x + it.size.width / 2f
                            },
                    )
                    CapabilityPill(
                        icon = { s, c -> GimoIcons.Wrench(size = s, color = c) },
                        label = "Utility",
                        accentColor = MeshModeColors.utility,
                        isOn = settings.hybridUtility && !settings.hybridAuto,
                        dimmed = settings.hybridAuto,
                        onToggle = {
                            val newVal = !settings.hybridUtility
                            onToggleUtility(newVal)
                            if (newVal) onToggleAuto(false)
                            if (!newVal && !settings.hybridInference && !settings.hybridServe) onToggleAuto(true)
                        },
                        modifier = Modifier
                            .weight(1f)
                            .onGloballyPositioned {
                                pillCenters[2] = it.positionInParent().x + it.size.width / 2f
                            },
                    )
                    CapabilityPill(
                        icon = { s, c -> GimoIcons.Server(size = s, color = c) },
                        label = "Serve",
                        accentColor = MeshModeColors.server,
                        isOn = settings.hybridServe && !settings.hybridAuto,
                        dimmed = settings.hybridAuto,
                        onToggle = {
                            val newVal = !settings.hybridServe
                            onToggleServe(newVal)
                            if (newVal) onToggleAuto(false)
                            if (!newVal && !settings.hybridInference && !settings.hybridUtility) onToggleAuto(true)
                        },
                        modifier = Modifier
                            .weight(1f)
                            .onGloballyPositioned {
                                pillCenters[3] = it.positionInParent().x + it.size.width / 2f
                            },
                    )
                }
            }

            // ── Status hint ──
            Spacer(Modifier.height(10.dp))
            Text(
                text = when {
                    settings.hybridAuto -> "Auto \u2014 Core adjusts capabilities dynamically"
                    isHybrid -> {
                        val parts = mutableListOf<String>()
                        if (settings.hybridInference) parts.add("Inference")
                        if (settings.hybridUtility) parts.add("Utility")
                        if (settings.hybridServe) parts.add("Serve")
                        parts.joinToString(" + ")
                    }
                    activeCount == 1 -> when {
                        settings.hybridInference -> "Inference \u2014 LLM execution on device"
                        settings.hybridUtility -> "Utility \u2014 Lightweight distributed tasks"
                        settings.hybridServe -> "Serve \u2014 Core API / MCP / CLI endpoints"
                        else -> ""
                    }
                    else -> "No capabilities active"
                },
                fontFamily = GimoMono,
                fontSize = 8.sp,
                letterSpacing = 0.3.sp,
                color = when {
                    settings.hybridAuto -> GimoAccents.primary.copy(alpha = 0.7f)
                    isHybrid -> teal.copy(alpha = 0.8f)
                    else -> GimoText.tertiary
                },
                modifier = Modifier.padding(start = 2.dp),
            )
        }
    }
}

@Composable
private fun CapabilityPill(
    icon: @Composable (Dp, Color) -> Unit,
    label: String,
    accentColor: Color,
    isOn: Boolean,
    dimmed: Boolean = false,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val bgColor = when {
        dimmed -> Color.Transparent
        isOn -> accentColor.copy(alpha = 0.12f)
        else -> Color.Transparent
    }
    val borderColor = when {
        dimmed -> GimoBorders.primary.copy(alpha = 0.4f)
        isOn -> accentColor.copy(alpha = 0.5f)
        else -> GimoBorders.primary
    }
    val textColor = when {
        dimmed -> GimoText.tertiary.copy(alpha = 0.25f)
        isOn -> accentColor
        else -> GimoText.tertiary
    }
    val iconColor = when {
        dimmed -> GimoText.tertiary.copy(alpha = 0.15f)
        isOn -> accentColor
        else -> GimoText.tertiary.copy(alpha = 0.4f)
    }

    Column(
        modifier = modifier
            .clip(RoundedCornerShape(10.dp))
            .background(bgColor)
            .border(1.dp, borderColor, RoundedCornerShape(10.dp))
            .clickable(onClick = onToggle)
            .padding(vertical = 11.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        icon(18.dp, iconColor)
        Spacer(Modifier.height(5.dp))
        Text(
            text = label,
            fontFamily = GimoMono,
            fontWeight = if (isOn) FontWeight.Medium else FontWeight.Normal,
            fontSize = 8.5.sp,
            letterSpacing = 0.3.sp,
            color = textColor,
            maxLines = 1,
        )
    }
}

private fun Modifier.borderBottom() = this.then(
    Modifier.drawBehind {
        drawLine(
            color = GimoBorders.subtle,
            start = Offset(0f, size.height),
            end = Offset(size.width, size.height),
            strokeWidth = 1.dp.toPx(),
        )
    }
)
