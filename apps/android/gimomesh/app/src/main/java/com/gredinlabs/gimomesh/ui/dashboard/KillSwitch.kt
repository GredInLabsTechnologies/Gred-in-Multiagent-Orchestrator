package com.gredinlabs.gimomesh.ui.dashboard

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import com.gredinlabs.gimomesh.ui.components.GimoIcons
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.ui.theme.*

@Composable
fun KillSwitch(
    isMeshRunning: Boolean,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var isHolding by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(10.dp)

    val borderColor = if (isMeshRunning) GimoAccents.alert.copy(alpha = 0.3f)
        else GimoAccents.trust.copy(alpha = 0.3f)
    val textColor = if (isMeshRunning) GimoAccents.alert else GimoAccents.trust
    val bgColor by animateColorAsState(
        targetValue = if (isHolding) GimoAccents.alert.copy(alpha = 0.2f)
            else if (isMeshRunning) GimoAccents.alert.copy(alpha = 0.04f)
            else GimoAccents.trust.copy(alpha = 0.04f),
        animationSpec = tween(if (isHolding) 2000 else 200),
        label = "killBg",
    )

    Column(
        modifier = modifier.padding(top = 4.dp, bottom = 2.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(42.dp)
                .clip(shape)
                .background(bgColor)
                .border(1.5.dp, borderColor, shape)
                .pointerInput(isMeshRunning) {
                    detectTapGestures(
                        onPress = {
                            isHolding = true
                            tryAwaitRelease()
                            isHolding = false
                        },
                        onLongPress = {
                            onToggle()
                        },
                    )
                },
            contentAlignment = Alignment.Center,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center,
            ) {
                if (isMeshRunning) {
                    GimoIcons.Stop(size = 11.dp, color = textColor)
                } else {
                    GimoIcons.Play(size = 11.dp, color = textColor)
                }
                Spacer(Modifier.width(6.dp))
                Text(
                    text = if (isMeshRunning) "STOP MESH NODE" else "START MESH NODE",
                    fontFamily = GimoMono,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 10.sp,
                    letterSpacing = 1.sp,
                    color = textColor,
                )
            }
        }

        Spacer(Modifier.height(3.dp))
        Text(
            text = "hold 2 seconds to confirm",
            fontFamily = GimoMono,
            fontSize = 7.sp,
            letterSpacing = 0.6.sp,
            color = GimoText.tertiary,
            textAlign = TextAlign.Center,
        )
    }
}
