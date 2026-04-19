package com.gredinlabs.gimomesh.ui.graph

import androidx.compose.animation.*
import androidx.compose.animation.core.tween
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.data.model.PlanNode
import com.gredinlabs.gimomesh.data.model.PlanNodeStatus
import com.gredinlabs.gimomesh.ui.theme.*
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/**
 * Fullscreen graph overlay with zoom controls and node detail panel.
 * Mirrors the HTML mockup's graph overlay behavior.
 */
@Composable
fun GraphOverlay(
    nodes: List<PlanNode>,
    visible: Boolean,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var zoomLevel by remember { mutableFloatStateOf(1f) }
    var selectedNode by remember { mutableStateOf<PlanNode?>(null) }

    AnimatedVisibility(
        visible = visible,
        enter = fadeIn(tween(200)),
        exit = fadeOut(tween(200)),
    ) {
        Box(
            modifier = modifier
                .fillMaxSize()
                .background(GimoSurfaces.surface0)
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // Top bar
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 20.dp, vertical = 14.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(
                            text = "Plan Graph",
                            fontFamily = GimoDisplay,
                            fontWeight = FontWeight.Bold,
                            fontSize = 14.sp,
                            letterSpacing = 0.5.sp,
                            color = GimoText.primary,
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            text = "t-0042",
                            fontFamily = GimoMono,
                            fontSize = 9.sp,
                            color = GimoText.tertiary,
                        )
                    }

                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        ZoomButton("−") { zoomLevel = (zoomLevel - 0.25f).coerceAtLeast(0.5f) }
                        Text(
                            text = "${(zoomLevel * 100).toInt()}%",
                            fontFamily = GimoMono,
                            fontWeight = FontWeight.Medium,
                            fontSize = 10.sp,
                            color = GimoText.tertiary,
                            modifier = Modifier.width(36.dp),
                        )
                        ZoomButton("+") { zoomLevel = (zoomLevel + 0.25f).coerceAtMost(2f) }
                        Spacer(Modifier.width(6.dp))
                        ZoomButton("✕", onClick = onDismiss)
                    }
                }

                // Zoomable graph viewport
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState())
                        .verticalScroll(rememberScrollState())
                        .drawBehind { drawDotGrid(GimoSurfaces.surface3) }
                ) {
                    Box(
                        modifier = Modifier
                            .padding(30.dp)
                            .scale(zoomLevel)
                    ) {
                        // Larger graph nodes
                        Row(
                            modifier = Modifier.height(IntrinsicSize.Min),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            val orch = nodes.firstOrNull() ?: return@Row
                            val workers = nodes.filter { it.id in orch.children }
                            val deliver = nodes.firstOrNull { it.id == "deliver" }

                            ExpandedGraphNode(orch, selectedNode?.id == orch.id) {
                                selectedNode = if (selectedNode?.id == orch.id) null else orch
                            }
                            EdgeLine(orch.status)
                            if (workers.size > 1) ForkConnector(PlanNodeStatus.DONE)

                            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                                workers.forEach { w ->
                                    ExpandedGraphNode(w, selectedNode?.id == w.id) {
                                        selectedNode = if (selectedNode?.id == w.id) null else w
                                    }
                                }
                            }

                            if (workers.size > 1) ForkConnector(PlanNodeStatus.RUNNING)
                            if (deliver != null) {
                                EdgeLine(PlanNodeStatus.PENDING)
                                ExpandedGraphNode(deliver, selectedNode?.id == deliver.id) {
                                    selectedNode = if (selectedNode?.id == deliver.id) null else deliver
                                }
                            }
                        }
                    }
                }
            }

            // Node detail panel (slide up from bottom)
            AnimatedVisibility(
                visible = selectedNode != null,
                enter = slideInVertically(tween(250)) { it },
                exit = slideOutVertically(tween(200)) { it },
                modifier = Modifier.align(Alignment.BottomCenter),
            ) {
                selectedNode?.let { node ->
                    NodeDetailPanel(
                        node = node,
                        onDismiss = { selectedNode = null },
                    )
                }
            }
        }
    }
}

@Composable
private fun ExpandedGraphNode(
    node: PlanNode,
    isSelected: Boolean,
    onClick: () -> Unit,
) {
    val (borderColor, textColor, bgColor) = expandedNodeColors(node.status)
    val selectedBorder = if (isSelected) GimoAccents.primary else borderColor

    Column(
        modifier = Modifier
            .widthIn(min = 130.dp, max = 160.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(bgColor)
            .border(
                if (isSelected) 2.dp else 1.dp,
                selectedBorder,
                RoundedCornerShape(12.dp),
            )
            .clickable(onClick = onClick)
            .padding(10.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = when (node.status) {
                    PlanNodeStatus.DONE -> "✓"
                    PlanNodeStatus.RUNNING -> "↻"
                    PlanNodeStatus.PENDING -> "◷"
                    PlanNodeStatus.ERROR -> "✗"
                },
                fontSize = 10.sp,
                color = textColor,
                modifier = Modifier
                    .size(18.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(Color.Black.copy(alpha = 0.25f))
                    .wrapContentSize(Alignment.Center),
            )
            Spacer(Modifier.width(5.dp))
            Text(
                text = node.role.uppercase(),
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 8.sp,
                letterSpacing = 0.8.sp,
                color = textColor.copy(alpha = 0.55f),
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            text = node.label,
            fontFamily = GimoMono,
            fontWeight = FontWeight.SemiBold,
            fontSize = 11.sp,
            color = textColor,
        )
        if (node.description.isNotEmpty()) {
            Text(
                text = node.description,
                fontFamily = GimoMono,
                fontSize = 8.5.sp,
                color = textColor.copy(alpha = 0.45f),
            )
        }
    }
}

@Composable
private fun EdgeLine(status: PlanNodeStatus) {
    val color = when (status) {
        PlanNodeStatus.DONE -> GimoAccents.trust.copy(alpha = 0.35f)
        PlanNodeStatus.RUNNING -> GimoAccents.primary.copy(alpha = 0.5f)
        else -> GimoBorders.primary
    }
    Box(Modifier.width(36.dp).height(2.dp).background(color))
}

@Composable
private fun ForkConnector(status: PlanNodeStatus) {
    val color = when (status) {
        PlanNodeStatus.DONE -> GimoAccents.trust.copy(alpha = 0.3f)
        PlanNodeStatus.RUNNING -> GimoAccents.primary.copy(alpha = 0.25f)
        else -> GimoBorders.primary
    }
    Box(Modifier.width(30.dp).fillMaxHeight().padding(vertical = 8.dp)) {
        Box(Modifier.width(2.dp).fillMaxHeight().align(Alignment.Center).background(color))
    }
}

@Composable
private fun ZoomButton(label: String, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(32.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(GimoSurfaces.surface1)
            .border(1.dp, GimoBorders.primary, RoundedCornerShape(8.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            fontSize = 14.sp,
            color = GimoText.secondary,
        )
    }
}

@Composable
private fun NodeDetailPanel(
    node: PlanNode,
    onDismiss: () -> Unit,
) {
    val statusColor = when (node.status) {
        PlanNodeStatus.DONE -> GimoAccents.trust
        PlanNodeStatus.RUNNING -> GimoAccents.amber
        PlanNodeStatus.PENDING -> GimoText.tertiary
        PlanNodeStatus.ERROR -> GimoAccents.alert
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp))
            .background(GlassBackground)
            .border(1.dp, GlassBorder, RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp))
            .padding(18.dp)
            .padding(bottom = 20.dp)
    ) {
        // Handle
        Box(
            modifier = Modifier
                .width(32.dp)
                .height(3.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(GimoSurfaces.surface3)
                .align(Alignment.CenterHorizontally),
        )
        Spacer(Modifier.height(12.dp))

        // Header
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(6.dp)
                        .clip(RoundedCornerShape(50))
                        .background(statusColor),
                )
                Spacer(Modifier.width(5.dp))
                Text(
                    text = node.status.name,
                    fontFamily = GimoMono,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 9.sp,
                    letterSpacing = 1.sp,
                    color = statusColor,
                )
            }
            Box(
                modifier = Modifier
                    .size(24.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(GimoSurfaces.surface2)
                    .border(1.dp, GimoBorders.primary, RoundedCornerShape(6.dp))
                    .clickable(onClick = onDismiss),
                contentAlignment = Alignment.Center,
            ) {
                Text("✕", fontSize = 12.sp, color = GimoText.tertiary)
            }
        }

        Spacer(Modifier.height(8.dp))
        Text(
            text = node.label,
            fontFamily = GimoMono,
            fontWeight = FontWeight.SemiBold,
            fontSize = 14.sp,
            color = GimoText.primary,
        )
        Text(
            text = node.role.uppercase(),
            fontFamily = GimoMono,
            fontWeight = FontWeight.Medium,
            fontSize = 8.sp,
            letterSpacing = 1.sp,
            color = GimoText.tertiary,
        )

        // Prompt
        if (node.prompt.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text(
                text = "TASK PROMPT",
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 7.5.sp,
                letterSpacing = 1.sp,
                color = GimoText.tertiary,
            )
            Spacer(Modifier.height(5.dp))

            val formatted = try {
                Json { prettyPrint = true }.encodeToString(
                    JsonElement.serializer(),
                    Json.parseToJsonElement(node.prompt),
                )
            } catch (_: Exception) { node.prompt }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 120.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(GimoSurfaces.surface0)
                    .border(1.dp, GimoBorders.subtle, RoundedCornerShape(6.dp))
                    .verticalScroll(rememberScrollState())
                    .padding(8.dp)
            ) {
                Text(
                    text = formatted,
                    fontFamily = GimoMono,
                    fontSize = 9.sp,
                    lineHeight = 14.sp,
                    color = GimoText.secondary,
                )
            }
        }
    }
}

private fun expandedNodeColors(status: PlanNodeStatus): Triple<Color, Color, Color> = when (status) {
    PlanNodeStatus.DONE -> Triple(
        GimoAccents.trust.copy(alpha = 0.38f), GimoAccents.trust, GimoAccents.trust.copy(alpha = 0.05f),
    )
    PlanNodeStatus.RUNNING -> Triple(
        GimoAccents.amber.copy(alpha = 0.4f), GimoAccents.amber, GimoAccents.amber.copy(alpha = 0.05f),
    )
    PlanNodeStatus.PENDING -> Triple(
        GimoBorders.primary, GimoText.tertiary, Color(0xFF090A0B).copy(alpha = 0.35f),
    )
    PlanNodeStatus.ERROR -> Triple(
        GimoAccents.alert.copy(alpha = 0.4f), GimoAccents.alert, GimoAccents.alert.copy(alpha = 0.05f),
    )
}

private fun DrawScope.drawDotGrid(color: Color) {
    val spacing = 20.dp.toPx()
    val radius = 0.5.dp.toPx()
    var x = 0f
    while (x < size.width) {
        var y = 0f
        while (y < size.height) {
            drawCircle(color.copy(alpha = 0.2f), radius, Offset(x, y))
            y += spacing
        }
        x += spacing
    }
}
