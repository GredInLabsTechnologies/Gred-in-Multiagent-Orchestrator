package com.gredinlabs.gimomesh.ui.dashboard

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.ui.components.Badge
import com.gredinlabs.gimomesh.ui.components.GimoCard
import com.gredinlabs.gimomesh.ui.theme.*

@Composable
fun ModelCard(
    modelName: String,
    inferenceRunning: Boolean,
    inferencePort: Int,
    endpoint: String,
    params: String,
    quantization: String,
    throughput: String,
    deferredReason: String = "",
    onStartInference: () -> Unit = {},
    onStopInference: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    val deferred = deferredReason.isNotBlank()
    val badgeColor = when {
        inferenceRunning -> GimoAccents.green
        deferred -> GimoAccents.warning
        else -> GimoAccents.alert
    }
    val badgeText = when {
        inferenceRunning -> "running"
        deferred -> "deferred"
        else -> "tap to start"
    }
    val endpointText = when {
        endpoint.isNotBlank() -> endpoint
        else -> "port $inferencePort"
    }
    val throughputText = if (inferenceRunning) throughput else "inactive"

    GimoCard(
        modifier = modifier.fillMaxWidth(),
        padding = PaddingValues(horizontal = 10.dp, vertical = 8.dp),
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = modelName,
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 12.sp,
                color = GimoText.primary,
            )
            Badge(
                text = badgeText,
                color = badgeColor,
                onClick = {
                    if (inferenceRunning) onStopInference() else onStartInference()
                },
            )
        }

        if (deferred) {
            Spacer(Modifier.height(4.dp))
            Text(
                text = "auto-start deferred: $deferredReason".uppercase(),
                fontFamily = GimoMono,
                fontSize = 7.sp,
                letterSpacing = 0.8.sp,
                color = GimoAccents.warning,
            )
        }

        Spacer(Modifier.height(6.dp))

        // 2x2 Grid
        Row(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.weight(1f)) {
                ModelField("Endpoint", endpointText, valueColor = badgeColor)
                Spacer(Modifier.height(4.dp))
                ModelField("Quantization", quantization)
            }
            Column(modifier = Modifier.weight(1f)) {
                ModelField("Parameters", params)
                Spacer(Modifier.height(4.dp))
                ModelField("Throughput", throughputText, valueColor = if (inferenceRunning) GimoAccents.trust else GimoAccents.alert)
            }
        }
    }
}

@Composable
private fun ModelField(
    label: String,
    value: String,
    valueColor: androidx.compose.ui.graphics.Color = GimoText.secondary,
) {
    Text(
        text = label.uppercase(),
        fontFamily = GimoMono,
        fontSize = 6.5.sp,
        letterSpacing = 1.sp,
        color = GimoText.tertiary,
    )
    Text(
        text = value,
        fontFamily = GimoMono,
        fontSize = 9.5.sp,
        color = valueColor,
        lineHeight = 13.sp,
    )
}
