package com.gredinlabs.gimomesh.ui.theme

import androidx.compose.ui.graphics.Color

// ═══ GIMO Visual Identity — replicated from web frontend ═══

object GimoSurfaces {
    val surface0 = Color(0xFF080C14)
    val surface1 = Color(0xFF0C1222)
    val surface2 = Color(0xFF141C2E)
    val surface3 = Color(0xFF1C2640)
}

object GimoAccents {
    val primary = Color(0xFF3B82F6)   // Blue — primary actions
    val approval = Color(0xFFD4A574)  // Gold — approvals
    val trust = Color(0xFF5A9F8F)     // Teal — success, health
    val alert = Color(0xFFC85450)     // Red — errors, danger
    val warning = Color(0xFFD4975A)   // Orange — caution
    val purple = Color(0xFF8B7EC8)    // Purple — secondary accent
    val amber = Color(0xFFF59E0B)     // Amber — running state
    val green = Color(0xFF22C55E)     // Green — connected
}

object GimoText {
    val primary = Color(0xFFE8ECF4)
    val secondary = Color(0xFF7D8A99)
    val tertiary = Color(0xFF5A6A7C)
}

object GimoBorders {
    val primary = Color(0xFF1E2A3E)
    val subtle = Color(0xFF141C2E)
    val focus = Color(0xFF3B82F6)
}

object MeshStateColors {
    val connected = Color(0xFF22C55E)
    val approved = Color(0xFF4ADE80)
    val pendingApproval = Color(0xFFEAB308)
    val reconnecting = Color(0xFFFACC15)
    val thermalLockout = Color(0xFFEF4444)
    val refused = Color(0xFFF87171)
    val offline = Color(0xFF71717A)
    val discoverable = Color(0xFF60A5FA)
}

object MeshModeColors {
    val inference = Color(0xFF5A9F8F)   // Teal — primary mode, trust/brain
    val utility = Color(0xFF60A5FA)     // Light blue — lightweight worker
    val server = Color(0xFF94A3B8)      // Slate — infrastructure backbone
    val hybrid = Color(0xFF3B82F6)      // Primary blue — full capability
}

// Glass effect
val GlassBackground = Color(0xFF0C1222).copy(alpha = 0.82f)
val GlassBorder = Color.White.copy(alpha = 0.06f)
