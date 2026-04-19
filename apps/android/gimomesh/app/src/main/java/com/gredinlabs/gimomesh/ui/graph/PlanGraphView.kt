package com.gredinlabs.gimomesh.ui.graph

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.data.model.PlanNode
import com.gredinlabs.gimomesh.data.model.PlanNodeStatus
import com.gredinlabs.gimomesh.ui.components.GimoIcons
import com.gredinlabs.gimomesh.ui.theme.*

@Composable
fun PlanGraphView(
    nodes: List<PlanNode>,
    onNodeClick: (PlanNode) -> Unit,
    onExpandClick: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    val dotColor = GimoSurfaces.surface3
    val shape = RoundedCornerShape(10.dp)

    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(shape)
            .background(GimoSurfaces.surface1)
            .border(1.dp, GimoBorders.primary, shape)
            .drawBehind { drawDotGrid(dotColor) }
            .padding(8.dp)
    ) {
        Column {
            // Header
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 2.dp, vertical = 0.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "CURRENT PLAN",
                    fontFamily = GimoMono,
                    fontWeight = FontWeight.Medium,
                    fontSize = 7.5.sp,
                    letterSpacing = 1.2.sp,
                    color = GimoText.tertiary,
                )
                Row(
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "t-0042",
                        fontFamily = GimoMono,
                        fontSize = 8.sp,
                        color = GimoText.tertiary,
                    )
                    // Expand button
                    Box(
                        modifier = Modifier
                            .size(22.dp)
                            .clip(RoundedCornerShape(5.dp))
                            .background(GimoSurfaces.surface2)
                            .border(1.dp, GimoBorders.primary, RoundedCornerShape(5.dp))
                            .clickable(onClick = onExpandClick),
                        contentAlignment = Alignment.Center,
                    ) {
                        GimoIcons.Expand(
                            size = 12.dp,
                            color = GimoText.secondary,
                        )
                    }
                }
            }

            Spacer(Modifier.height(7.dp))

            // Graph canvas — horizontal scroll
            Row(
                modifier = Modifier
                    .horizontalScroll(rememberScrollState())
                    .height(IntrinsicSize.Min),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (nodes.isEmpty()) return@Row

                // Find orchestrator (first node)
                val orch = nodes.firstOrNull() ?: return@Row
                val workers = nodes.filter { it.id in orch.children }
                val deliver = nodes.firstOrNull { it.id == "deliver" }

                // Orchestrator
                GraphNode(node = orch, onClick = { onNodeClick(orch) })

                // Edge
                EdgeLine(status = orch.status)

                // Fork connector
                if (workers.size > 1) {
                    ForkConnector(
                        status = if (workers.all { it.status == PlanNodeStatus.DONE })
                            PlanNodeStatus.DONE else PlanNodeStatus.RUNNING
                    )
                }

                // Workers column
                if (workers.size > 1) {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        workers.forEach { worker ->
                            GraphNode(node = worker, onClick = { onNodeClick(worker) })
                        }
                    }
                } else {
                    workers.firstOrNull()?.let { worker ->
                        GraphNode(node = worker, onClick = { onNodeClick(worker) })
                    }
                }

                // Join connector
                if (workers.size > 1) {
                    ForkConnector(
                        status = if (workers.any { it.status == PlanNodeStatus.RUNNING })
                            PlanNodeStatus.RUNNING else PlanNodeStatus.PENDING
                    )
                }

                // Edge to deliver
                if (deliver != null) {
                    EdgeLine(status = PlanNodeStatus.PENDING)
                    GraphNode(node = deliver, onClick = { onNodeClick(deliver) })
                }
            }
        }
    }
}

@Composable
private fun GraphNode(
    node: PlanNode,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val (borderColor, textColor, bgColor) = nodeColors(node.status)
    val glowModifier = if (node.status == PlanNodeStatus.RUNNING) {
        Modifier.shadow(8.dp, RoundedCornerShape(10.dp), ambientColor = GimoAccents.amber.copy(alpha = 0.18f))
    } else Modifier

    Column(
        modifier = modifier
            .widthIn(min = 96.dp, max = 118.dp)
            .then(glowModifier)
            .clip(RoundedCornerShape(10.dp))
            .background(bgColor)
            .border(1.dp, borderColor, RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .padding(6.dp)
    ) {
        // Header: icon + type
        Row(verticalAlignment = Alignment.CenterVertically) {
            StatusIcon(node.status)
            Spacer(Modifier.width(3.dp))
            Text(
                text = node.role.uppercase(),
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 7.sp,
                letterSpacing = 0.8.sp,
                color = textColor.copy(alpha = 0.55f),
            )
        }
        Spacer(Modifier.height(2.dp))

        // Label
        Text(
            text = node.label,
            fontFamily = GimoMono,
            fontWeight = FontWeight.SemiBold,
            fontSize = 9.sp,
            lineHeight = 11.sp,
            color = textColor,
        )

        // Description
        if (node.description.isNotEmpty()) {
            Text(
                text = node.description,
                fontFamily = GimoMono,
                fontSize = 7.sp,
                lineHeight = 9.sp,
                color = textColor.copy(alpha = 0.45f),
            )
        }

        // Progress bar for running
        if (node.status == PlanNodeStatus.RUNNING && node.progress > 0) {
            Spacer(Modifier.height(4.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(2.dp)
                    .clip(RoundedCornerShape(1.dp))
                    .background(GimoAccents.amber.copy(alpha = 0.12f))
            ) {
                val infiniteTransition = rememberInfiniteTransition(label = "prog")
                val alpha by infiniteTransition.animateFloat(
                    initialValue = 1f, targetValue = 0.35f,
                    animationSpec = infiniteRepeatable(
                        tween(1200, easing = EaseInOut), RepeatMode.Reverse
                    ), label = "progAlpha"
                )
                Box(
                    modifier = Modifier
                        .fillMaxHeight()
                        .fillMaxWidth(fraction = node.progress)
                        .clip(RoundedCornerShape(1.dp))
                        .background(GimoAccents.amber.copy(alpha = alpha))
                )
            }
        }
    }
}

@Composable
private fun StatusIcon(status: PlanNodeStatus) {
    val color = when (status) {
        PlanNodeStatus.DONE -> GimoAccents.trust
        PlanNodeStatus.RUNNING -> GimoAccents.amber
        PlanNodeStatus.PENDING -> GimoText.tertiary
        PlanNodeStatus.ERROR -> GimoAccents.alert
    }
    val symbol = when (status) {
        PlanNodeStatus.DONE -> "✓"
        PlanNodeStatus.RUNNING -> "↻"
        PlanNodeStatus.PENDING -> "◷"
        PlanNodeStatus.ERROR -> "✗"
    }
    Box(
        modifier = Modifier
            .size(14.dp)
            .clip(RoundedCornerShape(3.dp))
            .background(Color.Black.copy(alpha = 0.25f)),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = symbol, fontSize = 8.sp, color = color)
    }
}

@Composable
private fun EdgeLine(status: PlanNodeStatus) {
    val color = when (status) {
        PlanNodeStatus.DONE -> GimoAccents.trust.copy(alpha = 0.35f)
        PlanNodeStatus.RUNNING -> GimoAccents.primary.copy(alpha = 0.5f)
        else -> GimoBorders.primary
    }
    Box(
        modifier = Modifier
            .width(24.dp)
            .height(2.dp)
            .background(color)
    )
}

@Composable
private fun ForkConnector(status: PlanNodeStatus) {
    val color = when (status) {
        PlanNodeStatus.DONE -> GimoAccents.trust.copy(alpha = 0.3f)
        PlanNodeStatus.RUNNING -> GimoAccents.primary.copy(alpha = 0.25f)
        else -> GimoBorders.primary
    }
    Box(
        modifier = Modifier
            .width(22.dp)
            .fillMaxHeight()
            .padding(vertical = 8.dp)
    ) {
        Box(
            modifier = Modifier
                .width(2.dp)
                .fillMaxHeight()
                .align(Alignment.Center)
                .background(color)
        )
    }
}

private fun nodeColors(status: PlanNodeStatus): Triple<Color, Color, Color> = when (status) {
    PlanNodeStatus.DONE -> Triple(
        GimoAccents.trust.copy(alpha = 0.38f),
        GimoAccents.trust,
        GimoAccents.trust.copy(alpha = 0.05f),
    )
    PlanNodeStatus.RUNNING -> Triple(
        GimoAccents.amber.copy(alpha = 0.4f),
        GimoAccents.amber,
        GimoAccents.amber.copy(alpha = 0.05f),
    )
    PlanNodeStatus.PENDING -> Triple(
        GimoBorders.primary,
        GimoText.tertiary,
        Color(0xFF090A0B).copy(alpha = 0.35f),
    )
    PlanNodeStatus.ERROR -> Triple(
        GimoAccents.alert.copy(alpha = 0.4f),
        GimoAccents.alert,
        GimoAccents.alert.copy(alpha = 0.05f),
    )
}

private fun DrawScope.drawDotGrid(color: Color) {
    val spacing = 20.dp.toPx()
    val radius = 0.5.dp.toPx()
    val alpha = 0.25f
    var x = 0f
    while (x < size.width) {
        var y = 0f
        while (y < size.height) {
            drawCircle(color.copy(alpha = alpha), radius, Offset(x, y))
            y += spacing
        }
        x += spacing
    }
}
