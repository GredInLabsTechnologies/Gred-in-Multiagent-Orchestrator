package com.gredinlabs.gimomesh.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Monospace: JetBrains Mono — falls back to system monospace until .ttf bundled
// To bundle: place jetbrains_mono_*.ttf in res/font/ and use Font(R.font.*)
val GimoMono = FontFamily.Monospace

// Display font for "GIMO" wordmark — Outfit (geometric sans-serif)
// To bundle: place outfit_*.ttf in res/font/ and use Font(R.font.*)
val GimoDisplay = FontFamily.SansSerif

val GimoSans = FontFamily.Default // System Roboto/SF Pro

val GimoTypography = Typography(
    // Display — "GIMO" wordmark
    displayLarge = TextStyle(
        fontFamily = GimoDisplay,
        fontWeight = FontWeight.Bold,
        fontSize = 28.sp,
        letterSpacing = 2.sp,
    ),
    // Screen titles
    titleLarge = TextStyle(
        fontFamily = GimoDisplay,
        fontWeight = FontWeight.Bold,
        fontSize = 16.sp,
        letterSpacing = 0.5.sp,
        color = GimoText.primary,
    ),
    // Section headers
    titleMedium = TextStyle(
        fontFamily = GimoMono,
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        letterSpacing = 0.sp,
        color = GimoText.primary,
    ),
    // Card labels (CPU, RAM, HEALTH, etc.)
    labelLarge = TextStyle(
        fontFamily = GimoMono,
        fontWeight = FontWeight.Medium,
        fontSize = 9.sp,
        letterSpacing = 1.2.sp,
        color = GimoText.tertiary,
    ),
    // Small labels
    labelSmall = TextStyle(
        fontFamily = GimoMono,
        fontWeight = FontWeight.Normal,
        fontSize = 7.sp,
        letterSpacing = 0.8.sp,
        color = GimoText.tertiary,
    ),
    // Metric values (23%, 87%, etc.)
    headlineLarge = TextStyle(
        fontFamily = GimoMono,
        fontWeight = FontWeight.Normal,
        fontSize = 20.sp,
        letterSpacing = (-0.5).sp,
    ),
    // Body text (settings labels)
    bodyLarge = TextStyle(
        fontFamily = GimoSans,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        color = GimoText.primary,
    ),
    // Body secondary
    bodyMedium = TextStyle(
        fontFamily = GimoMono,
        fontWeight = FontWeight.Normal,
        fontSize = 11.sp,
        color = GimoText.secondary,
    ),
    // Terminal text
    bodySmall = TextStyle(
        fontFamily = GimoMono,
        fontWeight = FontWeight.Normal,
        fontSize = 10.sp,
        lineHeight = 16.sp,
        color = GimoText.secondary,
    ),
)
