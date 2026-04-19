package com.gredinlabs.gimomesh.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.ui.theme.GimoMono

@Composable
fun Badge(
    text: String,
    color: Color,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(5.dp)
    Text(
        text = text.uppercase(),
        modifier = modifier
            .clip(shape)
            .background(color.copy(alpha = 0.1f))
            .border(1.dp, color.copy(alpha = 0.18f), shape)
            .padding(horizontal = 7.dp, vertical = 3.dp),
        fontFamily = GimoMono,
        fontWeight = FontWeight.Medium,
        fontSize = 8.sp,
        letterSpacing = 0.7.sp,
        color = color,
    )
}
