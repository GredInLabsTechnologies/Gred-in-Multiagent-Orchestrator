package com.gredinlabs.gimomesh.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * GIMO Mesh icon system — all icons drawn with Canvas.
 * Zero emoji, zero unicode placeholders. Every visual is ours.
 */
object GimoIcons {

    /** Dashboard — 4 quadrants grid */
    @Composable
    fun Dashboard(size: Dp = 16.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val gap = w * 0.12f
            val cell = (w - gap) / 2f
            val r = CornerRadius(w * 0.08f)

            // Top-left
            drawRoundRect(color, Offset(0f, 0f), Size(cell, cell), r)
            // Top-right
            drawRoundRect(color, Offset(cell + gap, 0f), Size(cell, cell), r)
            // Bottom-left
            drawRoundRect(color, Offset(0f, cell + gap), Size(cell, cell), r)
            // Bottom-right
            drawRoundRect(color, Offset(cell + gap, cell + gap), Size(cell, cell), r)
        }
    }

    /** Terminal — cursor prompt */
    @Composable
    fun Terminal(size: Dp = 16.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val h = this.size.height
            val stroke = w * 0.12f

            // > chevron
            val path = Path().apply {
                moveTo(w * 0.15f, h * 0.2f)
                lineTo(w * 0.45f, h * 0.5f)
                lineTo(w * 0.15f, h * 0.8f)
            }
            drawPath(path, color, style = Stroke(stroke, cap = StrokeCap.Round, join = StrokeJoin.Round))

            // _ cursor line
            drawLine(
                color = color,
                start = Offset(w * 0.55f, h * 0.75f),
                end = Offset(w * 0.85f, h * 0.75f),
                strokeWidth = stroke,
                cap = StrokeCap.Round,
            )
        }
    }

    /** Agent — diamond with center dot (neural node) */
    @Composable
    fun Agent(size: Dp = 16.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val h = this.size.height
            val cx = w / 2f
            val cy = h / 2f
            val r = w * 0.4f
            val stroke = w * 0.1f

            val path = Path().apply {
                moveTo(cx, cy - r)
                lineTo(cx + r, cy)
                lineTo(cx, cy + r)
                lineTo(cx - r, cy)
                close()
            }
            drawPath(path, color, style = Stroke(stroke, join = StrokeJoin.Round))
            drawCircle(color, radius = w * 0.08f, center = Offset(cx, cy))
        }
    }

    /** Config — gear: circle + radiating ticks */
    @Composable
    fun Config(size: Dp = 16.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val cx = w / 2f
            val cy = w / 2f
            val outerR = w * 0.44f
            val innerR = w * 0.28f
            val stroke = w * 0.1f
            val tickCount = 6

            // Inner ring
            drawCircle(color, radius = innerR, center = Offset(cx, cy), style = Stroke(stroke))

            // Gear ticks
            for (i in 0 until tickCount) {
                val angle = Math.toRadians(60.0 * i - 30.0)
                val cos = kotlin.math.cos(angle).toFloat()
                val sin = kotlin.math.sin(angle).toFloat()
                drawLine(
                    color = color,
                    start = Offset(cx + innerR * cos, cy + innerR * sin),
                    end = Offset(cx + outerR * cos, cy + outerR * sin),
                    strokeWidth = stroke * 1.2f,
                    cap = StrokeCap.Round,
                )
            }
        }
    }

    /** Network node — small grid for connection status */
    @Composable
    fun NetworkNode(size: Dp = 12.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val dotR = w * 0.1f
            val stroke = w * 0.07f
            val positions = listOf(
                Offset(w * 0.2f, w * 0.2f),
                Offset(w * 0.8f, w * 0.2f),
                Offset(w * 0.2f, w * 0.8f),
                Offset(w * 0.8f, w * 0.8f),
            )
            // Lines
            drawLine(color.copy(alpha = 0.4f), positions[0], positions[1], stroke)
            drawLine(color.copy(alpha = 0.4f), positions[0], positions[2], stroke)
            drawLine(color.copy(alpha = 0.4f), positions[1], positions[3], stroke)
            drawLine(color.copy(alpha = 0.4f), positions[2], positions[3], stroke)
            drawLine(color.copy(alpha = 0.3f), positions[0], positions[3], stroke)
            // Dots
            positions.forEach { drawCircle(color, dotR, it) }
        }
    }

    /** Play — filled triangle pointing right */
    @Composable
    fun Play(size: Dp = 12.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val h = this.size.height
            val path = Path().apply {
                moveTo(w * 0.2f, h * 0.1f)
                lineTo(w * 0.9f, h * 0.5f)
                lineTo(w * 0.2f, h * 0.9f)
                close()
            }
            drawPath(path, color)
        }
    }

    /** Stop — filled rounded square */
    @Composable
    fun Stop(size: Dp = 12.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val inset = w * 0.18f
            drawRoundRect(
                color = color,
                topLeft = Offset(inset, inset),
                size = Size(w - inset * 2, w - inset * 2),
                cornerRadius = CornerRadius(w * 0.1f),
            )
        }
    }

    /** Expand — 4 outward arrows from center */
    @Composable
    fun Expand(size: Dp = 12.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val stroke = w * 0.1f
            val m = w * 0.15f  // margin
            val a = w * 0.35f  // arm length from corner

            // Top-left corner
            drawLine(color, Offset(m, m), Offset(m + a, m), stroke, cap = StrokeCap.Round)
            drawLine(color, Offset(m, m), Offset(m, m + a), stroke, cap = StrokeCap.Round)
            // Top-right
            drawLine(color, Offset(w - m, m), Offset(w - m - a, m), stroke, cap = StrokeCap.Round)
            drawLine(color, Offset(w - m, m), Offset(w - m, m + a), stroke, cap = StrokeCap.Round)
            // Bottom-left
            drawLine(color, Offset(m, w - m), Offset(m + a, w - m), stroke, cap = StrokeCap.Round)
            drawLine(color, Offset(m, w - m), Offset(m, w - m - a), stroke, cap = StrokeCap.Round)
            // Bottom-right
            drawLine(color, Offset(w - m, w - m), Offset(w - m - a, w - m), stroke, cap = StrokeCap.Round)
            drawLine(color, Offset(w - m, w - m), Offset(w - m, w - m - a), stroke, cap = StrokeCap.Round)
        }
    }

    /** Thermometer — bulb at bottom + column */
    @Composable
    fun Thermometer(size: Dp = 12.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val h = this.size.height
            val stroke = w * 0.12f
            val cx = w / 2f

            // Column (tube)
            val tubeWidth = w * 0.22f
            drawRoundRect(
                color = color,
                topLeft = Offset(cx - tubeWidth / 2f, h * 0.08f),
                size = Size(tubeWidth, h * 0.6f),
                cornerRadius = CornerRadius(tubeWidth / 2f),
                style = Stroke(stroke),
            )

            // Bulb at bottom
            drawCircle(
                color = color,
                radius = w * 0.22f,
                center = Offset(cx, h * 0.78f),
            )

            // Fill line inside tube
            drawLine(
                color = color,
                start = Offset(cx, h * 0.65f),
                end = Offset(cx, h * 0.3f),
                strokeWidth = tubeWidth * 0.4f,
                cap = StrokeCap.Round,
            )
        }
    }

    /** Brain — neural inference icon (circle with 3 inner connections) */
    @Composable
    fun Brain(size: Dp = 16.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val cx = w / 2f
            val cy = w / 2f
            val r = w * 0.4f
            val stroke = w * 0.09f

            // Outer circle
            drawCircle(color, r, Offset(cx, cy), style = Stroke(stroke))

            // 3 internal nodes
            val nodes = listOf(
                Offset(cx, cy - r * 0.45f),
                Offset(cx - r * 0.4f, cy + r * 0.3f),
                Offset(cx + r * 0.4f, cy + r * 0.3f),
            )
            // Connections
            for (i in nodes.indices) {
                drawLine(color.copy(alpha = 0.5f), nodes[i], nodes[(i + 1) % 3], stroke * 0.7f, cap = StrokeCap.Round)
            }
            // Center hub
            drawCircle(color, w * 0.06f, Offset(cx, cy))
            // Nodes
            nodes.forEach { drawCircle(color, w * 0.055f, it) }
        }
    }

    /** Wrench — utility tool icon */
    @Composable
    fun Wrench(size: Dp = 16.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val stroke = w * 0.13f

            // Wrench handle (diagonal line)
            drawLine(
                color = color,
                start = Offset(w * 0.25f, w * 0.75f),
                end = Offset(w * 0.6f, w * 0.4f),
                strokeWidth = stroke,
                cap = StrokeCap.Round,
            )
            // Wrench head (arc)
            drawArc(
                color = color,
                startAngle = -60f,
                sweepAngle = 200f,
                useCenter = false,
                topLeft = Offset(w * 0.42f, w * 0.1f),
                size = Size(w * 0.42f, w * 0.42f),
                style = Stroke(stroke, cap = StrokeCap.Round),
            )
        }
    }

    /** Server — stacked layers icon */
    @Composable
    fun Server(size: Dp = 16.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val h = this.size.height
            val stroke = w * 0.09f
            val layerH = h * 0.2f
            val inset = w * 0.15f

            // 3 horizontal bars stacked
            for (i in 0..2) {
                val y = h * 0.2f + i * (layerH + h * 0.08f)
                drawRoundRect(
                    color = color,
                    topLeft = Offset(inset, y),
                    size = Size(w - inset * 2, layerH),
                    cornerRadius = CornerRadius(w * 0.06f),
                    style = Stroke(stroke),
                )
                // Status dot on each bar
                drawCircle(
                    color = color,
                    radius = w * 0.04f,
                    center = Offset(w - inset - w * 0.1f, y + layerH / 2f),
                )
            }
        }
    }

    /** Auto — circular arrows (sync/dynamic) */
    @Composable
    fun Auto(size: Dp = 16.dp, color: Color, modifier: Modifier = Modifier) {
        Canvas(modifier = modifier.size(size)) {
            val w = this.size.width
            val cx = w / 2f
            val cy = w / 2f
            val r = w * 0.34f
            val stroke = w * 0.1f

            // Arc 1 (top half)
            drawArc(
                color = color,
                startAngle = -30f,
                sweepAngle = 200f,
                useCenter = false,
                topLeft = Offset(cx - r, cy - r),
                size = Size(r * 2, r * 2),
                style = Stroke(stroke, cap = StrokeCap.Round),
            )

            // Arrow head 1 (at end of arc 1)
            val arrowPath = Path().apply {
                moveTo(w * 0.72f, w * 0.18f)
                lineTo(w * 0.82f, w * 0.32f)
                lineTo(w * 0.62f, w * 0.32f)
                close()
            }
            drawPath(arrowPath, color)

            // Arrow head 2 (opposite side)
            val arrowPath2 = Path().apply {
                moveTo(w * 0.28f, w * 0.82f)
                lineTo(w * 0.18f, w * 0.68f)
                lineTo(w * 0.38f, w * 0.68f)
                close()
            }
            drawPath(arrowPath2, color)
        }
    }
}
