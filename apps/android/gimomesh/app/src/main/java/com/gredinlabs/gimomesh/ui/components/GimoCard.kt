package com.gredinlabs.gimomesh.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gredinlabs.gimomesh.ui.theme.GimoBorders
import com.gredinlabs.gimomesh.ui.theme.GimoSurfaces

@Composable
fun GimoCard(
    modifier: Modifier = Modifier,
    radius: Dp = 8.dp,
    padding: PaddingValues = PaddingValues(horizontal = 10.dp, vertical = 7.dp),
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(radius)
    Column(
        modifier = modifier
            .clip(shape)
            .background(GimoSurfaces.surface1)
            .border(1.dp, GimoBorders.primary, shape)
            .padding(padding),
        content = content,
    )
}
