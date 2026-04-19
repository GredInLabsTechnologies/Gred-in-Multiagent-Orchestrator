package com.gredinlabs.gimomesh.ui.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.gredinlabs.gimomesh.data.store.SettingsStore
import com.gredinlabs.gimomesh.service.setupRequired
import com.gredinlabs.gimomesh.ui.MeshViewModel
import com.gredinlabs.gimomesh.ui.agent.AgentScreen
import com.gredinlabs.gimomesh.ui.components.GimoIcons
import com.gredinlabs.gimomesh.ui.dashboard.DashboardScreen
import com.gredinlabs.gimomesh.ui.settings.SettingsScreen
import com.gredinlabs.gimomesh.ui.setup.SetupWizardScreen
import com.gredinlabs.gimomesh.ui.terminal.TerminalScreen
import com.gredinlabs.gimomesh.ui.theme.GimoAccents
import com.gredinlabs.gimomesh.ui.theme.GimoText
import com.gredinlabs.gimomesh.ui.theme.GimoTypography
import com.gredinlabs.gimomesh.ui.theme.GlassBackground
import com.gredinlabs.gimomesh.ui.theme.GlassBorder
import java.io.File

enum class Screen(val label: String) {
    SETUP("Setup"),
    DASH("Dash"),
    TERM("Term"),
    AGENT("Agent"),
    CONFIG("Config"),
}

@Composable
fun GimoMeshNavHost(
    viewModel: MeshViewModel = viewModel(),
    deepLinkCode: String = "",
    deepLinkHost: String = "",
    deepLinkPort: String = "9325",
) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsState()
    val settings by viewModel.settingsStore.settings.collectAsState(
        initial = SettingsStore.Settings()
    )

    val requiresModel = remember(settings.downloadedModelPath, settings.model, settings.deviceMode) {
        requiresOnboardingModel(settings, context.filesDir)
    }
    val needsSetup = setupRequired(settings) || requiresModel

    var currentScreen by rememberSaveable {
        mutableStateOf(if (needsSetup) Screen.SETUP else Screen.DASH)
    }

    // The initial `needsSetup` evaluation is based on the DataStore's default
    // (blank) snapshot because the Flow hasn't emitted yet. That forces Screen.SETUP
    // even for a provisioned device. Once the real settings arrive, correct the
    // position — bidirectionally, so re-provisioning after a clear-data also flows.
    LaunchedEffect(needsSetup) {
        currentScreen = when {
            needsSetup -> Screen.SETUP
            currentScreen == Screen.SETUP -> Screen.DASH
            else -> currentScreen
        }
    }

    val showBottomNav = currentScreen != Screen.SETUP

    Box(modifier = Modifier.fillMaxSize()) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .padding(bottom = if (showBottomNav) 64.dp else 0.dp)
        ) {
            when (currentScreen) {
                Screen.SETUP -> SetupWizardScreen(
                    onSetupComplete = {
                        currentScreen = Screen.DASH
                    },
                    onStartMesh = {
                        if (!state.isMeshRunning) {
                            viewModel.toggleMesh()
                        }
                    },
                    settingsStore = viewModel.settingsStore,
                    deepLinkCode = deepLinkCode,
                    deepLinkHost = deepLinkHost,
                    deepLinkPort = deepLinkPort,
                )
                Screen.DASH -> DashboardScreen(
                    state = state,
                    onToggleMesh = viewModel::toggleMesh,
                    onModeChange = viewModel::changeMode,
                    modeLocked = settings.modeLocked,
                    onToggleModeLock = viewModel::toggleModeLock,
                    onStartInference = viewModel::onStartInference,
                    onStopInference = viewModel::onStopInference,
                )
                Screen.TERM -> TerminalScreen(
                    state = state,
                    onClearTerminal = viewModel::clearTerminal,
                )
                Screen.AGENT -> AgentScreen(state = state)
                Screen.CONFIG -> SettingsScreen(
                    state = state,
                    settings = settings,
                    settingsStore = viewModel.settingsStore,
                )
            }
        }

        if (showBottomNav) {
            BottomNavBar(
                currentScreen = currentScreen,
                onScreenSelected = { currentScreen = it },
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }
    }
}

@Composable
private fun BottomNavBar(
    currentScreen: Screen,
    onScreenSelected: (Screen) -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .height(64.dp)
            .background(GlassBackground)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(GlassBorder)
        )

        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 6.dp),
            horizontalArrangement = Arrangement.SpaceAround,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Screen.entries
                .filterNot { it == Screen.SETUP }
                .forEach { screen ->
                    val isSelected = screen == currentScreen
                    NavItem(
                        label = screen.label,
                        isSelected = isSelected,
                        onClick = { onScreenSelected(screen) },
                    )
                }
        }
    }
}

@Composable
private fun NavItem(
    label: String,
    isSelected: Boolean,
    onClick: () -> Unit,
) {
    val color = if (isSelected) GimoAccents.primary else GimoText.tertiary

    Column(
        modifier = Modifier
            .clip(RoundedCornerShape(10.dp))
            .then(
                if (isSelected) {
                    Modifier.background(GimoAccents.primary.copy(alpha = 0.07f))
                } else {
                    Modifier
                }
            )
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
                onClick = onClick,
            )
            // G11 fix: expose the tab to accessibility (TalkBack + automated
            // UI test tools that walk the semantics tree). Previously the
            // whole bottom nav was invisible to mobile-mcp list_elements.
            .semantics(mergeDescendants = true) {
                this.role = androidx.compose.ui.semantics.Role.Tab
                this.contentDescription = "$label tab${if (isSelected) " (selected)" else ""}"
                this.selected = isSelected
            }
            .padding(horizontal = 14.dp, vertical = 5.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        when (label) {
            "Dash" -> GimoIcons.Dashboard(size = 16.dp, color = color)
            "Term" -> GimoIcons.Terminal(size = 16.dp, color = color)
            "Agent" -> GimoIcons.Agent(size = 16.dp, color = color)
            "Config" -> GimoIcons.Config(size = 16.dp, color = color)
        }
        Spacer(modifier = Modifier.height(2.dp))
        Text(
            text = label.uppercase(),
            style = GimoTypography.labelSmall.copy(color = color),
        )
    }
}

private fun requiresOnboardingModel(
    settings: SettingsStore.Settings,
    filesDir: File,
): Boolean {
    val needsInferenceModel = settings.deviceMode == "inference"
    if (!needsInferenceModel) {
        return false
    }

    val downloadedFile = settings.downloadedModelPath
        .takeIf { it.isNotBlank() }
        ?.let(::File)
    if (downloadedFile?.exists() == true) {
        return false
    }

    val legacyModel = File(filesDir, "models/${settings.model.replace(":", "_")}.gguf")
    return !legacyModel.exists()
}
