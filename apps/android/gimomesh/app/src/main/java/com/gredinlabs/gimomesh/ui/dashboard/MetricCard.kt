package com.gredinlabs.gimomesh.ui.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.ui.components.GimoCard
import com.gredinlabs.gimomesh.ui.theme.*

@Composable
fun MetricCard(
    label: String,
    value: Float,
    active: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val hasData = active && value >= 0f
    val displayValue = if (hasData) value else 0f
    val color = when {
        !hasData -> GimoText.tertiary
        displayValue < 50f -> GimoAccents.trust
        displayValue < 80f -> GimoAccents.warning
        else -> GimoAccents.alert
    }

    GimoCard(
        modifier = modifier,
        padding = PaddingValues(horizontal = 8.dp, vertical = 7.dp),
    ) {
        // Label
        Text(
            text = label.uppercase(),
            fontFamily = GimoMono,
            fontWeight = FontWeight.Medium,
            fontSize = 7.sp,
            letterSpacing = 1.2.sp,
            color = GimoText.tertiary,
        )
        Spacer(Modifier.height(3.dp))

        // Value
        Row {
            Text(
                text = if (hasData) "${displayValue.toInt()}" else "—",
                fontFamily = GimoMono,
                fontSize = 18.sp,
                letterSpacing = (-0.5).sp,
                color = color,
            )
            if (hasData) {
                Text(
                    text = "%",
                    fontFamily = GimoMono,
                    fontSize = 10.sp,
                    color = GimoText.tertiary,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }

        Spacer(Modifier.height(4.dp))

        // Progress bar
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(2.dp)
                .clip(RoundedCornerShape(1.dp))
                .background(GimoSurfaces.surface3)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(fraction = (displayValue / 100f).coerceIn(0f, 1f))
                    .clip(RoundedCornerShape(1.dp))
                    .background(color)
            )
        }
    }
}

@Composable
fun MetricsRow(
    cpuPercent: Float,
    ramPercent: Float,
    batteryPercent: Float,
    isMeshRunning: Boolean = false,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        MetricCard(
            label = "CPU",
            value = cpuPercent,
            active = isMeshRunning,
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            label = "RAM",
            value = ramPercent,
            active = isMeshRunning,
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            label = "Battery",
            value = batteryPercent,
            active = isMeshRunning,
            modifier = Modifier.weight(1f),
        )
    }
}
