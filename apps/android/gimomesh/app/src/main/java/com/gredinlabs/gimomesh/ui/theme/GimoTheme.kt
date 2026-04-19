package com.gredinlabs.gimomesh.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val GimoDarkColorScheme = darkColorScheme(
    primary = GimoAccents.primary,
    onPrimary = GimoText.primary,
    secondary = GimoAccents.trust,
    onSecondary = GimoText.primary,
    tertiary = GimoAccents.approval,
    background = GimoSurfaces.surface0,
    onBackground = GimoText.primary,
    surface = GimoSurfaces.surface1,
    onSurface = GimoText.primary,
    surfaceVariant = GimoSurfaces.surface2,
    onSurfaceVariant = GimoText.secondary,
    outline = GimoBorders.primary,
    outlineVariant = GimoBorders.subtle,
    error = GimoAccents.alert,
    onError = GimoText.primary,
)

@Composable
fun GimoMeshTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = GimoDarkColorScheme,
        typography = GimoTypography,
        shapes = GimoShapes,
        content = content,
    )
}
