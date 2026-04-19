package com.gredinlabs.gimomesh.ui.agent

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.data.model.AgentTask
import com.gredinlabs.gimomesh.data.model.MeshState
import com.gredinlabs.gimomesh.data.model.PlanNodeStatus
import com.gredinlabs.gimomesh.ui.components.StatusDot
import com.gredinlabs.gimomesh.ui.theme.*

@Composable
fun AgentScreen(
    state: MeshState,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 14.dp)
    ) {
        // Header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "Agent",
                fontFamily = GimoDisplay,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp,
                letterSpacing = 0.5.sp,
                color = GimoText.primary,
            )
            Text(
                text = "${state.tasks.size} tasks",
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 9.sp,
                color = GimoText.tertiary,
                modifier = Modifier
                    .background(GimoSurfaces.surface2, RoundedCornerShape(5.dp))
                    .padding(horizontal = 7.dp, vertical = 2.dp),
            )
        }

        // Current running task (expanded)
        val runningTask = state.tasks.firstOrNull { it.status == PlanNodeStatus.RUNNING }
        if (runningTask != null) {
            CurrentTaskCard(task = runningTask)
            Spacer(Modifier.height(14.dp))
        }

        // History
        val historyTasks = state.tasks.filter { it.status != PlanNodeStatus.RUNNING }
        if (historyTasks.isNotEmpty()) {
            Text(
                text = "HISTORY",
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 7.5.sp,
                letterSpacing = 1.2.sp,
                color = GimoText.tertiary,
                modifier = Modifier.padding(bottom = 7.dp),
            )
            historyTasks.forEach { task ->
                HistoryTaskRow(task)
                Spacer(Modifier.height(5.dp))
            }
        }

        Spacer(Modifier.height(20.dp))
    }
}

@Composable
private fun CurrentTaskCard(task: AgentTask) {
    var schemaExpanded by remember { mutableStateOf(true) }
    var streamExpanded by remember { mutableStateOf(true) }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(GimoSurfaces.surface1)
            .border(1.dp, GimoAccents.primary.copy(alpha = 0.2f), RoundedCornerShape(10.dp))
            .padding(12.dp)
    ) {
        Column {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatusDot(color = GimoAccents.primary, size = 5.dp)
                    Spacer(Modifier.width(5.dp))
                    Text(
                        text = "RUNNING",
                        fontFamily = GimoMono,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 8.sp,
                        letterSpacing = 1.sp,
                        color = GimoAccents.primary,
                    )
                }
                Text(
                    text = task.dispatchedAt,
                    fontFamily = GimoMono,
                    fontSize = 9.sp,
                    color = GimoText.tertiary,
                )
            }

            Spacer(Modifier.height(8.dp))

            // Tags
            Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                TaskTag(task.actionClass, GimoAccents.primary)
                TaskTag(task.target, null)
                TaskTag(task.complexity, GimoAccents.warning)
            }

            Spacer(Modifier.height(10.dp))

            // Prompt Schema section
            CollapsibleSection(
                title = "PROMPT SCHEMA",
                expanded = schemaExpanded,
                onToggle = { schemaExpanded = !schemaExpanded },
            ) {
                JsonViewer(json = task.prompt)
            }

            // Inference Stream section
            CollapsibleSection(
                title = "INFERENCE STREAM",
                expanded = streamExpanded,
                onToggle = { streamExpanded = !streamExpanded },
            ) {
                InferenceStreamView(text = task.inferenceOutput)
            }
        }
    }
}

@Composable
private fun CollapsibleSection(
    title: String,
    expanded: Boolean,
    onToggle: () -> Unit,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 8.dp)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(GimoBorders.subtle)
        )
        Spacer(Modifier.height(8.dp))
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onToggle),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = title,
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 7.5.sp,
                letterSpacing = 1.sp,
                color = GimoText.tertiary,
            )
            Text(
                text = if (expanded) "▾" else "▸",
                fontSize = 12.sp,
                color = GimoText.tertiary,
            )
        }
        if (expanded) {
            Spacer(Modifier.height(6.dp))
            content()
        }
    }
}

@Composable
private fun JsonViewer(json: String) {
    // Simple formatted JSON display with syntax coloring
    val formatted = try {
        val obj = kotlinx.serialization.json.Json.parseToJsonElement(json)
        kotlinx.serialization.json.Json { prettyPrint = true }.encodeToString(
            kotlinx.serialization.json.JsonElement.serializer(), obj
        )
    } catch (_: Exception) { json }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(6.dp))
            .background(GimoSurfaces.surface0)
            .border(1.dp, GimoBorders.subtle, RoundedCornerShape(6.dp))
            .padding(7.dp)
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

@Composable
private fun InferenceStreamView(text: String) {
    val infiniteTransition = rememberInfiniteTransition(label = "cursor")
    val cursorAlpha by infiniteTransition.animateFloat(
        initialValue = 1f, targetValue = 0f,
        animationSpec = infiniteRepeatable(
            tween(500, easing = LinearEasing), RepeatMode.Reverse
        ), label = "cursorBlink",
    )

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(6.dp))
            .background(GimoSurfaces.surface0)
            .border(1.dp, GimoBorders.subtle, RoundedCornerShape(6.dp))
            .padding(7.dp)
    ) {
        Row {
            Text(
                text = text,
                fontFamily = GimoMono,
                fontSize = 9.5.sp,
                lineHeight = 15.sp,
                color = GimoText.primary,
            )
            Box(
                modifier = Modifier
                    .width(6.dp)
                    .height(13.dp)
                    .background(GimoAccents.primary.copy(alpha = cursorAlpha))
            )
        }
    }
}

@Composable
private fun TaskTag(text: String, accentColor: Color?) {
    val bg = accentColor?.copy(alpha = 0.06f) ?: GimoSurfaces.surface2
    val border = accentColor?.copy(alpha = 0.18f) ?: GimoBorders.primary
    val textColor = accentColor ?: GimoText.secondary

    Text(
        text = text,
        modifier = Modifier
            .clip(RoundedCornerShape(4.dp))
            .background(bg)
            .border(1.dp, border, RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 3.dp),
        fontFamily = GimoMono,
        fontWeight = FontWeight.Medium,
        fontSize = 8.sp,
        color = textColor,
    )
}

@Composable
private fun HistoryTaskRow(task: AgentTask) {
    val isDone = task.status == PlanNodeStatus.DONE
    val accentColor = if (isDone) GimoAccents.trust else GimoAccents.alert
    val iconSymbol = if (isDone) "✓" else "✗"

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(GimoSurfaces.surface1)
            .border(1.dp, GimoBorders.primary, RoundedCornerShape(8.dp))
            .drawLeftAccent(accentColor)
            .padding(horizontal = 10.dp, vertical = 9.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = iconSymbol,
                fontSize = 13.sp,
                color = accentColor,
            )
            Spacer(Modifier.width(7.dp))
            Column {
                Text(
                    text = task.actionClass,
                    fontFamily = GimoMono,
                    fontWeight = FontWeight.Medium,
                    fontSize = 10.sp,
                    color = GimoText.primary,
                )
                Text(
                    text = task.target,
                    fontFamily = GimoMono,
                    fontSize = 8.sp,
                    color = GimoText.tertiary,
                )
            }
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = task.dispatchedAt,
                fontFamily = GimoMono,
                fontSize = 8.sp,
                color = GimoText.tertiary,
            )
            Text(
                text = task.duration,
                fontFamily = GimoMono,
                fontSize = 8.sp,
                color = if (isDone) GimoText.tertiary else GimoAccents.alert,
            )
        }
    }
}

private fun Modifier.drawLeftAccent(color: Color) = this.then(
    Modifier.drawBehind {
        drawRect(
            color = color,
            topLeft = Offset.Zero,
            size = Size(3.dp.toPx(), size.height),
        )
    }
)
