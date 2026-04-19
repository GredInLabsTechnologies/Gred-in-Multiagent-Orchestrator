package com.gredinlabs.gimomesh.ui.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.ui.components.GimoCard
import com.gredinlabs.gimomesh.ui.components.GimoIcons
import com.gredinlabs.gimomesh.ui.theme.*

@Composable
fun ThermalStrip(
    cpuTempC: Float,
    gpuTempC: Float,
    batteryTempC: Float,
    thermalStatus: String,
    modifier: Modifier = Modifier,
) {
    GimoCard(
        modifier = modifier.fillMaxWidth(),
        padding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Thermometer icon
            GimoIcons.Thermometer(
                size = 12.dp,
                color = GimoAccents.alert.copy(alpha = 0.7f),
            )
            Spacer(Modifier.width(4.dp))
            Text(
                text = "THERMAL",
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 7.sp,
                letterSpacing = 1.sp,
                color = GimoText.tertiary,
            )

            Spacer(Modifier.weight(1f))

            // Temperature chips
            TempChip("CPU", cpuTempC)
            Spacer(Modifier.width(3.dp))
            TempChip("GPU", gpuTempC)
            Spacer(Modifier.width(3.dp))
            TempChip("BAT", batteryTempC)

            Spacer(Modifier.width(4.dp))

            // Status
            val statusColor = when (thermalStatus) {
                "OK" -> GimoAccents.trust
                "WARNING" -> GimoAccents.warning
                "LOCKOUT" -> GimoAccents.alert
                else -> GimoText.tertiary
            }
            Text(
                text = thermalStatus,
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 7.sp,
                letterSpacing = 0.6.sp,
                color = statusColor,
            )
        }
    }
}

@Composable
private fun TempChip(label: String, tempC: Float) {
    val color = when {
        tempC < 0 -> GimoText.tertiary
        tempC < 50 -> GimoAccents.trust
        tempC < 65 -> GimoAccents.warning
        else -> GimoAccents.alert
    }

    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(4.dp))
            .background(Color.Black.copy(alpha = 0.2f))
            .padding(horizontal = 6.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            fontFamily = GimoMono,
            fontSize = 6.5.sp,
            letterSpacing = 0.6.sp,
            color = GimoText.tertiary,
        )
        Spacer(Modifier.width(3.dp))
        Text(
            text = if (tempC < 0) "—" else "${tempC.toInt()}°",
            fontFamily = GimoMono,
            fontSize = 9.sp,
            color = color,
        )
    }
}
