package com.gredinlabs.gimomesh.ui.terminal

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.model.MeshState
import com.gredinlabs.gimomesh.data.model.TerminalLine
import com.gredinlabs.gimomesh.ui.components.StatusDot
import com.gredinlabs.gimomesh.ui.theme.*
import java.text.SimpleDateFormat
import java.util.*

@Composable
fun TerminalScreen(
    state: MeshState,
    onClearTerminal: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    var activeFilter by remember { mutableStateOf<LogSource?>(null) }
    var isPaused by remember { mutableStateOf(false) }
    val pausedLines = remember { mutableStateOf(state.terminalLines) }
    SideEffect { if (!isPaused) pausedLines.value = state.terminalLines }
    val displayLines = pausedLines.value
    val filteredLines = if (activeFilter == null) displayLines
        else displayLines.filter { it.source == activeFilter }

    Column(
        modifier = modifier
            .fillMaxSize()
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
                text = "Terminal",
                fontFamily = GimoDisplay,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp,
                letterSpacing = 0.5.sp,
                color = GimoText.primary,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                StatusDot(color = GimoAccents.green, size = 5.dp)
                Spacer(Modifier.width(4.dp))
                Text(
                    text = "LIVE",
                    fontFamily = GimoMono,
                    fontWeight = FontWeight.Medium,
                    fontSize = 8.sp,
                    letterSpacing = 0.8.sp,
                    color = GimoAccents.green,
                )
            }
        }

        // Filters
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(GimoSurfaces.surface1)
                .border(1.dp, GimoBorders.primary, RoundedCornerShape(8.dp))
                .padding(2.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
        ) {
            FilterTab("ALL", activeFilter == null) { activeFilter = null }
            FilterTab("AGENT", activeFilter == LogSource.AGENT) { activeFilter = LogSource.AGENT }
            FilterTab("INFER", activeFilter == LogSource.INFER) { activeFilter = LogSource.INFER }
            FilterTab("SYS", activeFilter == LogSource.SYS) { activeFilter = LogSource.SYS }
        }

        Spacer(Modifier.height(8.dp))

        // Terminal body
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(GimoSurfaces.surface0)
                .border(1.dp, GimoBorders.subtle, RoundedCornerShape(8.dp))
                .padding(8.dp)
        ) {
            LazyColumn(
                state = rememberLazyListState(),
            ) {
                items(
                    count = filteredLines.size,
                    key = { idx -> "${filteredLines[idx].timestamp}_$idx" },
                ) { idx ->
                    TerminalLineRow(filteredLines[idx])
                }
            }
        }

        Spacer(Modifier.height(8.dp))

        // Action bar
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            ActionButton(
                label = if (isPaused) "Resume" else "Pause",
                modifier = Modifier.weight(1f),
                onClick = { isPaused = !isPaused },
            )
            ActionButton("Copy", Modifier.weight(1f))
            ActionButton(
                label = "Clear",
                modifier = Modifier.weight(1f),
                onClick = onClearTerminal,
            )
        }

        Spacer(Modifier.height(16.dp))
    }
}

@Composable
private fun FilterTab(
    label: String,
    isActive: Boolean,
    onClick: () -> Unit,
) {
    val bgColor = if (isActive) GimoAccents.primary.copy(alpha = 0.1f) else Color.Transparent
    val textColor = if (isActive) GimoAccents.primary else GimoText.tertiary

    Text(
        text = label,
        modifier = Modifier
            .clip(RoundedCornerShape(6.dp))
            .background(bgColor)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 5.dp),
        fontFamily = GimoMono,
        fontWeight = FontWeight.Medium,
        fontSize = 9.sp,
        letterSpacing = 0.4.sp,
        color = textColor,
    )
}

@Composable
private fun TerminalLineRow(line: TerminalLine) {
    val tagColor = when (line.source) {
        LogSource.AGENT -> GimoAccents.primary
        LogSource.INFER -> GimoAccents.trust
        LogSource.SYS -> GimoText.secondary
        LogSource.TASK -> GimoAccents.approval
    }
    val tagLabel = when (line.source) {
        LogSource.AGENT -> "[AGENT]"
        LogSource.INFER -> "[INFER]"
        LogSource.SYS -> "[SYS]  "
        LogSource.TASK -> "[TASK] "
    }
    val timeFormat = remember { SimpleDateFormat("HH:mm:ss", Locale.US) }

    Row(modifier = Modifier.padding(vertical = 1.dp)) {
        Text(
            text = timeFormat.format(Date(line.timestamp)),
            fontFamily = GimoMono,
            fontSize = 9.5.sp,
            lineHeight = 16.sp,
            color = GimoText.tertiary,
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text = tagLabel,
            fontFamily = GimoMono,
            fontWeight = FontWeight.Medium,
            fontSize = 9.5.sp,
            lineHeight = 16.sp,
            color = tagColor,
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text = line.message,
            fontFamily = GimoMono,
            fontSize = 9.5.sp,
            lineHeight = 16.sp,
            color = GimoText.secondary,
        )
    }
}

@Composable
private fun ActionButton(
    label: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit = {},
) {
    Box(
        modifier = modifier
            .height(32.dp)
            .clip(RoundedCornerShape(7.dp))
            .background(GimoSurfaces.surface1)
            .border(1.dp, GimoBorders.primary, RoundedCornerShape(7.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label.uppercase(),
            fontFamily = GimoMono,
            fontWeight = FontWeight.Medium,
            fontSize = 9.sp,
            letterSpacing = 0.5.sp,
            color = GimoText.secondary,
        )
    }
}
