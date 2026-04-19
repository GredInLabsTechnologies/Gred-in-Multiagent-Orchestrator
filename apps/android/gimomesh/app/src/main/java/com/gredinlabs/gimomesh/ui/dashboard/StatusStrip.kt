package com.gredinlabs.gimomesh.ui.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.ui.components.GimoCard
import com.gredinlabs.gimomesh.ui.components.GimoIcons
import com.gredinlabs.gimomesh.ui.components.StatusDot
import com.gredinlabs.gimomesh.ui.theme.*

/**
 * Merged Core Connection + Health bar in a single row.
 */
@Composable
fun StatusStrip(
    coreUrl: String,
    isLinked: Boolean,
    healthScore: Float,
    modifier: Modifier = Modifier,
) {
    GimoCard(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Core connection: icon + IP + dot
            GimoIcons.NetworkNode(
                size = 12.dp,
                color = GimoText.tertiary,
            )
            Spacer(Modifier.width(5.dp))
            Text(
                text = coreUrl.replace(Regex("\\d+\\.\\d+\\.\\d+"), "•••.•••.•"),
                fontFamily = GimoMono,
                fontSize = 9.5.sp,
                color = GimoText.secondary,
            )
            Spacer(Modifier.width(4.dp))
            StatusDot(
                color = if (isLinked) GimoAccents.green else GimoAccents.alert,
                size = 4.dp,
            )

            // Separator
            Spacer(Modifier.width(8.dp))
            Box(
                modifier = Modifier
                    .width(1.dp)
                    .height(14.dp)
                    .background(GimoBorders.primary)
            )
            Spacer(Modifier.width(8.dp))

            // Health bar
            Text(
                text = "HEALTH",
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 7.5.sp,
                letterSpacing = 1.sp,
                color = GimoText.tertiary,
            )
            Spacer(Modifier.width(6.dp))

            val healthColor = when {
                healthScore > 70f -> GimoAccents.trust
                healthScore > 40f -> GimoAccents.warning
                else -> GimoAccents.alert
            }

            // Progress bar
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(GimoSurfaces.surface3)
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxHeight()
                        .fillMaxWidth(fraction = (healthScore / 100f).coerceIn(0f, 1f))
                        .clip(RoundedCornerShape(2.dp))
                        .background(healthColor)
                        .shadow(4.dp, ambientColor = healthColor.copy(alpha = 0.3f))
                )
            }

            Spacer(Modifier.width(6.dp))
            Text(
                text = "${healthScore.toInt()}%",
                fontFamily = GimoMono,
                fontWeight = FontWeight.Medium,
                fontSize = 11.sp,
                letterSpacing = (-0.2).sp,
                color = healthColor,
            )
        }
    }
}
