package com.gredinlabs.gimomesh.ui.dashboard

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.ui.components.GimoCard
import com.gredinlabs.gimomesh.ui.theme.GimoAccents
import com.gredinlabs.gimomesh.ui.theme.GimoMono
import com.gredinlabs.gimomesh.ui.theme.GimoText

@Composable
fun HostRuntimeCard(
    status: String,
    available: Boolean,
    lanUrl: String,
    webUrl: String,
    mcpUrl: String,
    error: String,
    modifier: Modifier = Modifier,
) {
    val statusColor = when (status) {
        "ready" -> GimoAccents.green
        "degraded", "starting" -> GimoAccents.warning
        "error", "unavailable" -> GimoAccents.alert
        else -> GimoText.tertiary
    }

    GimoCard(
        modifier = modifier.fillMaxWidth(),
        padding = PaddingValues(horizontal = 10.dp, vertical = 9.dp),
    ) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column {
                Text(
                    text = "LOCAL HOST",
                    fontFamily = GimoMono,
                    fontSize = 7.sp,
                    letterSpacing = 1.sp,
                    color = GimoText.tertiary,
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = status.uppercase(),
                    fontFamily = GimoMono,
                    fontWeight = FontWeight.Bold,
                    fontSize = 12.sp,
                    color = statusColor,
                )
            }
            Column {
                HostRuntimeField("LAN", lanUrl.ifBlank { "not published" })
                Spacer(modifier = Modifier.height(4.dp))
                HostRuntimeField("WEB", webUrl.ifBlank { "unavailable" })
            }
        }

        Spacer(modifier = Modifier.height(10.dp))

        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            HostRuntimeField("MCP", mcpUrl.ifBlank { "unavailable" }, modifier = Modifier.weight(1f))
            Spacer(modifier = Modifier.width(12.dp))
            HostRuntimeField(
                "CONTROL",
                if (available) "127.0.0.1:9325" else "disabled",
                modifier = Modifier.weight(1f),
            )
        }

        if (error.isNotBlank()) {
            Spacer(modifier = Modifier.height(10.dp))
            HostRuntimeField("ERROR", error, valueColor = GimoAccents.alert)
        }
    }
}

@Composable
private fun HostRuntimeField(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: Color = GimoText.secondary,
) {
    Column(modifier = modifier) {
        Text(
            text = label,
            fontFamily = GimoMono,
            fontSize = 6.5.sp,
            letterSpacing = 1.sp,
            color = GimoText.tertiary,
        )
        Spacer(modifier = Modifier.height(2.dp))
        Text(
            text = value,
            fontFamily = GimoMono,
            fontSize = 9.sp,
            color = valueColor,
            lineHeight = 12.sp,
        )
    }
}
