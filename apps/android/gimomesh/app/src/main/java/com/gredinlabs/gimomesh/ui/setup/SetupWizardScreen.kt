package com.gredinlabs.gimomesh.ui.setup

import android.os.Build
import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.ui.res.stringResource
import androidx.compose.runtime.Composable
import com.gredinlabs.gimomesh.R
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gredinlabs.gimomesh.data.api.OnboardingApiResult
import com.gredinlabs.gimomesh.data.api.OnboardingClient
import com.gredinlabs.gimomesh.data.model.CoreDiscovery
import com.gredinlabs.gimomesh.data.model.ModelInfo
import com.gredinlabs.gimomesh.data.network.CoreDiscoveryManager
import com.gredinlabs.gimomesh.data.store.SettingsStore
import com.gredinlabs.gimomesh.service.isServeMode
import com.gredinlabs.gimomesh.ui.theme.GimoAccents
import com.gredinlabs.gimomesh.ui.theme.GimoBorders
import com.gredinlabs.gimomesh.ui.theme.GimoDisplay
import com.gredinlabs.gimomesh.ui.theme.GimoMono
import com.gredinlabs.gimomesh.ui.theme.MeshModeColors
import com.gredinlabs.gimomesh.ui.theme.GimoSurfaces
import com.gredinlabs.gimomesh.ui.theme.GimoText
import com.gredinlabs.gimomesh.ui.theme.GimoTypography
import com.gredinlabs.gimomesh.ui.theme.MeshStateColors
import java.io.File
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val SetupAccent = MeshStateColors.approved
private val ErrorAccent = Color(0xFFEF4444)

sealed class SetupStep {
    object Welcome : SetupStep()
    object QRScanner : SetupStep()
    object CoreUrl : SetupStep()
    object ManualCode : SetupStep()
    object Enrolling : SetupStep()
    object WaitApproval : SetupStep()
    object ModelSelect : SetupStep()
    object Downloading : SetupStep()
    object Done : SetupStep()
}

@Composable
fun SetupWizardScreen(
    onSetupComplete: () -> Unit,
    onStartMesh: () -> Unit,
    settingsStore: SettingsStore,
    modifier: Modifier = Modifier,
    deepLinkCode: String = "",
    deepLinkHost: String = "",
    deepLinkPort: String = "9325",
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val settings by settingsStore.settings.collectAsState(initial = SettingsStore.Settings())
    val serveMode = remember(settings.deviceMode, settings.hybridAuto, settings.hybridServe) {
        isServeMode(settings)
    }
    val onboardingMode = !serveMode

    // If deep link provided, skip straight to enrolling
    val hasDeepLink = deepLinkCode.length == 6 && deepLinkHost.isNotBlank()
    val initialStep = if (hasDeepLink) SetupStep.Enrolling else SetupStep.Welcome
    // G26: on emulators, mDNS discovery does not cross the NAT to the host,
    // so we pre-populate Core URL with the emulator's host-loopback alias
    // (10.0.2.2 → host's localhost:9325). Real devices leave it blank for
    // mDNS / manual entry.
    val initialCoreUrl = when {
        hasDeepLink -> "http://$deepLinkHost:$deepLinkPort"
        settings.coreUrl.isNotBlank() -> settings.coreUrl
        isAndroidEmulator() -> "http://10.0.2.2:9325"
        else -> ""
    }

    var step by remember { mutableStateOf<SetupStep>(initialStep) }
    var coreUrlInput by rememberSaveable { mutableStateOf(initialCoreUrl) }
    var connectedCoreUrl by rememberSaveable { mutableStateOf(if (hasDeepLink) initialCoreUrl else "") }
    var code by rememberSaveable { mutableStateOf(if (hasDeepLink) deepLinkCode else "") }
    var lastSubmittedCode by rememberSaveable { mutableStateOf("") }
    var error by rememberSaveable { mutableStateOf("") }
    var bearerToken by rememberSaveable { mutableStateOf("") }
    var workspaceName by rememberSaveable { mutableStateOf("") }
    var onboardingStatus by rememberSaveable { mutableStateOf("pending_approval") }
    var isConnecting by remember { mutableStateOf(false) }
    var catalogLoaded by rememberSaveable { mutableStateOf(false) }
    var isCatalogLoading by remember { mutableStateOf(false) }
    var catalogRetryNonce by rememberSaveable { mutableStateOf(0) }
    var approvalRetryNonce by rememberSaveable { mutableStateOf(0) }
    var meshAutoStarted by rememberSaveable { mutableStateOf(false) }
    var coreDiscovery by remember { mutableStateOf<CoreDiscovery?>(null) }
    val discoveryManager = remember(context) { CoreDiscoveryManager(context) }
    var discoveredLanCore by remember { mutableStateOf<CoreDiscoveryManager.DiscoveredCore?>(null) }
    var models by remember { mutableStateOf<List<ModelInfo>>(emptyList()) }
    var selectedModel by remember { mutableStateOf<ModelInfo?>(null) }
    var downloadProgress by remember { mutableFloatStateOf(0f) }
    var downloadBytes by remember { mutableStateOf(0L) }
    var downloadTotalBytes by remember { mutableStateOf(-1L) }

    // Auto-enrollment: on first launch, try to fetch pending code from Core on LAN
    var autoEnrollAttempted by remember { mutableStateOf(false) }
    LaunchedEffect(step, hasDeepLink, autoEnrollAttempted, onboardingMode) {
        if (step == SetupStep.Welcome && onboardingMode && !hasDeepLink && !autoEnrollAttempted) {
            autoEnrollAttempted = true
            // Try the default Core URL first, then any mDNS-discovered Core
            val urlsToTry = listOfNotNull(
                settings.coreUrl.takeIf { it.isNotBlank() },
                discoveredLanCore?.url,
            ).distinct()
            for (url in urlsToTry) {
                val client = OnboardingClient(url)
                try {
                    when (val result = client.fetchPendingCode()) {
                        is OnboardingApiResult.Success -> {
                            val pending = result.value
                            val c = pending.code
                            if (c.length == 6 && c.all { ch -> ch.isDigit() }) {
                                connectedCoreUrl = pending.coreUrl.ifBlank { url }
                                coreUrlInput = connectedCoreUrl
                                code = c
                                step = SetupStep.Enrolling
                                return@LaunchedEffect
                            }
                        }
                        is OnboardingApiResult.Error -> { /* try next URL */ }
                    }
                } finally {
                    client.shutdown()
                }
            }
        }
    }

    val deviceId = remember(settings.deviceId) {
        settings.deviceId.ifEmpty { "${Build.MODEL.replace(" ", "-").lowercase()}-${UUID.randomUUID().toString().take(8)}" }
    }
    val deviceName = remember(settings.deviceName) { settings.deviceName.ifEmpty { Build.MODEL } }

    fun finishLocalHostSetup() {
        scope.launch {
            error = ""
            settingsStore.updateDeviceId(deviceId)
            settingsStore.updateDeviceName(deviceName)
            step = SetupStep.Done
        }
    }

    fun connectToCore() {
        val normalized = normalizeCoreUrl(coreUrlInput)
        if (normalized.isBlank() || isConnecting) {
            if (normalized.isBlank()) error = "Enter a valid Core URL"
            return
        }
        scope.launch {
            isConnecting = true
            error = ""
            coreDiscovery = null
            val client = OnboardingClient(normalized)
            try {
                when (val result = client.discoverCore()) {
                    is OnboardingApiResult.Success -> {
                        connectedCoreUrl = normalized
                        coreDiscovery = result.value
                        settingsStore.updateCoreUrl(normalized)
                        step = SetupStep.ManualCode
                    }
                    is OnboardingApiResult.Error -> error = result.message
                }
            } finally {
                isConnecting = false
                client.shutdown()
            }
        }
    }

    fun submitCode() {
        if (connectedCoreUrl.isBlank()) {
            error = "Connect to a Core before redeeming a code"
            step = SetupStep.CoreUrl
            return
        }
        if (code.length != 6) {
            error = "Enter a 6-digit code"
            return
        }
        lastSubmittedCode = code
        error = ""
        step = SetupStep.Enrolling
    }

    LaunchedEffect(bearerToken) {
        models = emptyList()
        selectedModel = null
        catalogLoaded = false
    }

    LaunchedEffect(code, step, connectedCoreUrl) {
        if (step == SetupStep.ManualCode && connectedCoreUrl.isNotBlank() && code.length == 6 && code != lastSubmittedCode) submitCode()
    }

    // F-11 fix (2026-04-19): redeem must fire EXACTLY ONCE when entering Enrolling.
    // Previously this effect keyed on (step, connectedCoreUrl, code); a change to
    // `code` mid-flight (focus loss, IME re-render) cancelled the coroutine after
    // the POST had been sent, then a relaunch fired a SECOND redeem which the
    // server rightly rejected with 403 "already used", sending the UI back to
    // ManualCode even though the device was successfully enrolled.
    LaunchedEffect(step) {
        if (step != SetupStep.Enrolling) return@LaunchedEffect
        if (connectedCoreUrl.isBlank() || code.length != 6) {
            error = "Invalid state — reconnect to the Core and retype the code"
            step = SetupStep.ManualCode
            return@LaunchedEffect
        }
        val client = OnboardingClient(connectedCoreUrl)
        try {
            when (
                val result = client.redeemCode(
                    code = code,
                    deviceId = deviceId,
                    name = deviceName,
                    deviceMode = settings.deviceMode,
                )
            ) {
                is OnboardingApiResult.Success -> {
                    val onboard = result.value
                    error = ""
                    bearerToken = onboard.bearerToken
                    workspaceName = onboard.workspaceName
                    onboardingStatus = onboard.status
                    meshAutoStarted = false
                    settingsStore.updateCoreUrl(connectedCoreUrl)
                    settingsStore.updateToken(onboard.bearerToken)
                    settingsStore.updateDeviceId(onboard.deviceId)
                    settingsStore.updateDeviceName(deviceName)
                    settingsStore.updateActiveWorkspace(onboard.workspaceId, onboard.workspaceName)
                    step = if (settings.deviceMode == "inference") {
                        SetupStep.ModelSelect
                    } else {
                        SetupStep.Done
                    }
                }
                is OnboardingApiResult.Error -> {
                    error = result.message
                    step = SetupStep.ManualCode
                }
            }
        } finally {
            client.shutdown()
        }
    }

    LaunchedEffect(step, bearerToken, connectedCoreUrl, catalogRetryNonce) {
        if (step != SetupStep.ModelSelect || bearerToken.isBlank() || connectedCoreUrl.isBlank() || catalogLoaded) return@LaunchedEffect
        isCatalogLoading = true
        val client = OnboardingClient(connectedCoreUrl)
        try {
            when (val result = client.listModels(bearerToken, deviceId)) {
                is OnboardingApiResult.Success -> {
                    models = result.value
                    catalogLoaded = true
                    error = ""
                }
                is OnboardingApiResult.Error -> {
                    if (result.code in listOf(401, 403) && onboardingStatus == "pending_approval") {
                        error = ""
                        step = SetupStep.WaitApproval
                    } else {
                        error = result.message
                    }
                }
            }
        } finally {
            isCatalogLoading = false
            client.shutdown()
        }
    }

    LaunchedEffect(step, bearerToken, connectedCoreUrl, approvalRetryNonce) {
        if (step != SetupStep.WaitApproval || bearerToken.isBlank() || connectedCoreUrl.isBlank()) return@LaunchedEffect
        val client = OnboardingClient(connectedCoreUrl)
        try {
            while (true) {
                when (val result = client.listModels(bearerToken, deviceId)) {
                    is OnboardingApiResult.Success -> {
                        models = result.value
                        catalogLoaded = true
                        error = ""
                        step = SetupStep.ModelSelect
                        return@LaunchedEffect
                    }
                    is OnboardingApiResult.Error -> if (result.code !in listOf(401, 403)) {
                        error = result.message
                        return@LaunchedEffect
                    }
                }
                delay(5_000)
            }
        } finally {
            client.shutdown()
        }
    }

    LaunchedEffect(step, bearerToken, connectedCoreUrl, selectedModel?.modelId) {
        val model = selectedModel
        if (step != SetupStep.Downloading || model == null || bearerToken.isBlank() || connectedCoreUrl.isBlank()) return@LaunchedEffect
        error = ""
        downloadProgress = 0f
        downloadBytes = 0L
        downloadTotalBytes = -1L
        val targetFile = File(context.filesDir, "models/${model.filename.ifBlank { "${model.modelId}.gguf" }}")
        val client = OnboardingClient(connectedCoreUrl)
        try {
            when (val result = client.downloadModel(bearerToken, model.modelId, targetFile) { downloaded, total ->
                scope.launch {
                    downloadBytes = downloaded
                    downloadTotalBytes = total
                    downloadProgress = if (total > 0) (downloaded.toFloat() / total.toFloat()).coerceIn(0f, 1f) else 0f
                }
            }) {
                is OnboardingApiResult.Success -> {
                    settingsStore.updateModel(model.modelId)
                    settingsStore.updateDownloadedModelPath(targetFile.absolutePath)
                    step = SetupStep.Done
                }
                is OnboardingApiResult.Error -> {
                    error = result.message
                    step = SetupStep.ModelSelect
                }
            }
        } finally {
            client.shutdown()
        }
    }

    // Mesh starts OFF — user activates from Dashboard, or Core requests it
    // LaunchedEffect(step) { if (step == SetupStep.Done) onStartMesh() }  // REMOVED

    LaunchedEffect(step) {
        if (step != SetupStep.CoreUrl) {
            discoveryManager.stopDiscovery()
            return@LaunchedEffect
        }
        discoveredLanCore = null
        discoveryManager.startDiscovery(onFound = { core ->
            if (discoveredLanCore == null) discoveredLanCore = core
            if (normalizeCoreUrl(coreUrlInput).isBlank()) coreUrlInput = core.url
        })
    }

    DisposableEffect(Unit) {
        onDispose { discoveryManager.stopDiscovery() }
    }

    Box(modifier = modifier.fillMaxSize().background(Color(0xFF0A0A0A)).padding(24.dp)) {
        Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.SpaceBetween) {
            Column {
                Header(step)
                Spacer(modifier = Modifier.height(18.dp))
                AnimatedContent(targetState = step, label = "setupStep") { current ->
                    when (current) {
                        SetupStep.Welcome -> StepCard {
                            StepTitle(
                                title = if (serveMode) "Run GIMO locally" else "Join the mesh",
                                body = when {
                                    serveMode -> "This device will host the authoritative GIMO Core locally. The Dashboard will show whether the embedded Core runtime is actually packaged in the APK."
                                    settings.deviceMode == "utility" -> "Connect to your Core, redeem a 6-digit code, and register this phone as a utility worker. No GGUF download is required."
                                    else -> "Connect to your Core, redeem a 6-digit code, pick a GGUF, and boot this device without ADB or cables."
                                },
                            )
                            Spacer(modifier = Modifier.height(18.dp))
                            SetupModeSelector(
                                selectedMode = settings.deviceMode,
                                onSelect = { mode ->
                                    scope.launch { settingsStore.updateDeviceMode(mode) }
                                },
                            )
                            Spacer(modifier = Modifier.height(18.dp))
                            if (serveMode) {
                                Banner(
                                    "Server and hybrid modes do not require a remote Core URL. If the embedded runtime payload is missing, host runtime will remain unavailable until the APK bundles it.",
                                    SetupAccent,
                                )
                                Spacer(modifier = Modifier.height(16.dp))
                                PrimaryAction("Finish local setup", true, ::finishLocalHostSetup)
                            } else {
                                Pill(
                                    if (settings.deviceMode == "utility") "Utility worker setup" else "30-60 sec setup",
                                    SetupAccent,
                                )
                                Spacer(modifier = Modifier.height(18.dp))
                                PrimaryAction("Scan QR Code", true) { step = SetupStep.QRScanner }
                                Spacer(modifier = Modifier.height(10.dp))
                                SecondaryAction("Enter code manually") { step = SetupStep.CoreUrl }
                            }
                        }
                        SetupStep.QRScanner -> QrScannerScreen(
                            onQrScanned = { result ->
                                coreUrlInput = result.coreUrl
                                connectedCoreUrl = result.coreUrl
                                code = result.code
                                lastSubmittedCode = result.code
                                error = ""
                                step = SetupStep.Enrolling
                            },
                            onCancel = { step = SetupStep.CoreUrl },
                        )
                        SetupStep.CoreUrl -> StepCard {
                            StepTitle("Locate the Core", "Enter the Core URL on your LAN. The wizard verifies that mesh onboarding is enabled before asking for a code.")
                            Spacer(modifier = Modifier.height(16.dp))
                            discoveredLanCore?.let {
                                Banner("Core auto-discovered at ${it.url} (${if (it.verified) "verified" else "unverified"})", SetupAccent)
                                Spacer(modifier = Modifier.height(12.dp))
                            }
                            InputField(coreUrlInput, { coreUrlInput = it; error = "" }, "http://192.168.0.49:9325", ::connectToCore)
                            Spacer(modifier = Modifier.height(12.dp))
                            coreDiscovery?.let { Banner("Core found: ${it.coreId.ifBlank { "mesh-enabled core" }} · v${it.version}", SetupAccent) }
                            if (error.isNotBlank()) { Spacer(modifier = Modifier.height(12.dp)); Banner(error, ErrorAccent) }
                            Spacer(modifier = Modifier.height(16.dp))
                            PrimaryAction(if (isConnecting) "Connecting..." else "Connect", !isConnecting && normalizeCoreUrl(coreUrlInput).isNotBlank(), ::connectToCore)
                            Spacer(modifier = Modifier.height(10.dp))
                            SecondaryAction("Back") { step = SetupStep.Welcome }
                        }
                        SetupStep.ManualCode -> StepCard {
                            StepTitle("Redeem your code", "Ask an admin for a 6-digit onboarding code. The code itself authorizes this pre-enrollment request.")
                            Spacer(modifier = Modifier.height(14.dp))
                            Pill(connectedCoreUrl.removePrefix("http://").removePrefix("https://"), SetupAccent)
                            Spacer(modifier = Modifier.height(16.dp))
                            CodeField(code) {
                                code = it
                                error = ""
                                if (it.length < 6 && it != lastSubmittedCode) lastSubmittedCode = ""
                            }
                            Spacer(modifier = Modifier.height(12.dp))
                            Text("Device ID: $deviceId", style = GimoTypography.labelLarge.copy(color = GimoText.tertiary))
                            if (error.isNotBlank()) { Spacer(modifier = Modifier.height(12.dp)); Banner(error, ErrorAccent) }
                            Spacer(modifier = Modifier.height(16.dp))
                            PrimaryAction("Redeem", code.length == 6 && connectedCoreUrl.isNotBlank(), ::submitCode)
                            Spacer(modifier = Modifier.height(10.dp))
                            SecondaryAction("Change Core URL") { step = SetupStep.CoreUrl }
                        }
                        SetupStep.Enrolling -> LoadingCard("Registering device...", "Redeeming the onboarding code and storing the bearer token locally.")
                        SetupStep.WaitApproval -> StepCard {
                            StepTitle("Waiting for approval", "The device is enrolled and the wizard is polling the Core until the model catalog becomes available.")
                            Spacer(modifier = Modifier.height(18.dp))
                            if (error.isBlank()) {
                                CircularProgressIndicator(color = SetupAccent, modifier = Modifier.align(Alignment.CenterHorizontally))
                                Spacer(modifier = Modifier.height(16.dp))
                                Text(workspaceName.ifBlank { "Pending workspace approval" }, style = GimoTypography.bodyMedium.copy(color = GimoText.secondary), textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                            } else {
                                Banner(error, ErrorAccent)
                                Spacer(modifier = Modifier.height(12.dp))
                                PrimaryAction("Retry", true) { error = ""; approvalRetryNonce += 1 }
                            }
                            Spacer(modifier = Modifier.height(10.dp))
                            SecondaryAction("Back to code") { error = ""; step = SetupStep.ManualCode }
                        }
                        SetupStep.ModelSelect -> StepCard {
                            StepTitle("Choose a GGUF", "Models are listed directly from the Core. Downloads stream over LAN and resume with HTTP Range if interrupted.")
                            if (error.isNotBlank()) { Spacer(modifier = Modifier.height(12.dp)); Banner(error, ErrorAccent) }
                            Spacer(modifier = Modifier.height(16.dp))
                            when {
                                isCatalogLoading && !catalogLoaded -> LoadingBody("Loading model catalog...")
                                models.isEmpty() -> {
                                    Text("No models are currently exposed by the Core.", style = GimoTypography.bodyMedium.copy(color = GimoText.secondary))
                                    Spacer(modifier = Modifier.height(16.dp))
                                    PrimaryAction("Retry catalog", true) { error = ""; catalogLoaded = false; catalogRetryNonce += 1 }
                                }
                                else -> Column(modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                    models.forEach { model ->
                                        ModelCard(model) { selectedModel = model; error = ""; step = SetupStep.Downloading }
                                    }
                                }
                            }
                            Spacer(modifier = Modifier.height(10.dp))
                            SecondaryAction("Back to code") { error = ""; step = SetupStep.ManualCode }
                        }
                        SetupStep.Downloading -> StepCard {
                            StepTitle("Downloading model", selectedModel?.let { "Streaming ${it.name} from the Core into local storage." } ?: "Preparing download...")
                            Spacer(modifier = Modifier.height(16.dp))
                            selectedModel?.let {
                                Pill("${it.name} ${it.params.ifBlank { it.quantization }}".trim(), SetupAccent)
                                Spacer(modifier = Modifier.height(16.dp))
                            }
                            if (downloadTotalBytes > 0) {
                                LinearProgressIndicator(progress = { downloadProgress }, color = SetupAccent, trackColor = GimoSurfaces.surface3, modifier = Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(999.dp)))
                                Spacer(modifier = Modifier.height(10.dp))
                                Text("${(downloadProgress * 100).toInt()}% · ${formatBytes(downloadBytes)} / ${formatBytes(downloadTotalBytes)}", style = GimoTypography.bodyMedium.copy(color = GimoText.secondary))
                            } else {
                                LinearProgressIndicator(color = SetupAccent, trackColor = GimoSurfaces.surface3, modifier = Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(999.dp)))
                                Spacer(modifier = Modifier.height(10.dp))
                                Text("Downloaded ${formatBytes(downloadBytes)}", style = GimoTypography.bodyMedium.copy(color = GimoText.secondary))
                            }
                        }
                        SetupStep.Done -> StepCard {
                            StepTitle(
                                "Ready",
                                when {
                                    serveMode -> "Device identity is stored locally. Activate the mesh from the Dashboard to start the embedded Core host."
                                    settings.deviceMode == "utility" -> "Token and workspace are stored locally. Activate the mesh from the Dashboard when ready."
                                    else -> "Token, workspace, and model are stored locally. Activate the mesh from the Dashboard when ready."
                                },
                            )
                            Spacer(modifier = Modifier.height(18.dp))
                            Box(modifier = Modifier.size(84.dp).clip(CircleShape).background(SetupAccent.copy(alpha = 0.14f)).border(1.dp, SetupAccent.copy(alpha = 0.45f), CircleShape).align(Alignment.CenterHorizontally), contentAlignment = Alignment.Center) {
                                Text("OK", fontFamily = GimoMono, fontWeight = FontWeight.Bold, fontSize = 22.sp, color = SetupAccent)
                            }
                            Spacer(modifier = Modifier.height(18.dp))
                            Text(buildString {
                                append("Mode: ")
                                append(settings.deviceMode.uppercase())
                                append("\nDevice: ")
                                append(deviceName)
                                if (!serveMode) {
                                    append("\nWorkspace: ")
                                    append(workspaceName.ifBlank { "Default" })
                                }
                                selectedModel?.let { append("\nModel: ${it.modelId}") }
                            }, style = GimoTypography.bodyMedium.copy(color = GimoText.secondary), textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                            Spacer(modifier = Modifier.height(24.dp))
                            PrimaryAction("Open Dashboard", true, onSetupComplete)
                        }
                    }
                }
            }
            Text("Core LAN only. No ADB. No cables.", style = GimoTypography.labelLarge.copy(color = GimoText.tertiary), textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun Header(step: SetupStep) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column {
                Text("GIMO", fontFamily = GimoDisplay, fontWeight = FontWeight.Bold, fontSize = 24.sp, letterSpacing = 2.sp, color = GimoText.primary)
                Text("MESH / ZERO-ADB SETUP", style = GimoTypography.labelLarge.copy(color = GimoText.tertiary))
            }
            Pill(stepLabel(step), SetupAccent)
        }
        Spacer(modifier = Modifier.height(12.dp))
        Box(modifier = Modifier.fillMaxWidth().height(1.dp).background(GimoBorders.primary))
    }
}

@Composable
private fun StepCard(content: @Composable ColumnScope.() -> Unit) {
    Column(modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(GimoSurfaces.surface1).border(1.dp, GimoBorders.primary, RoundedCornerShape(20.dp)).padding(20.dp), content = content)
}

@Composable
private fun StepTitle(title: String, body: String) {
    Text(title, fontFamily = GimoDisplay, fontWeight = FontWeight.Bold, fontSize = 20.sp, color = GimoText.primary)
    Spacer(modifier = Modifier.height(8.dp))
    Text(body, style = GimoTypography.bodyMedium.copy(color = GimoText.secondary))
}

@Composable
private fun LoadingCard(title: String, body: String) = StepCard {
    StepTitle(title, body)
    Spacer(modifier = Modifier.height(18.dp))
    LoadingBody(title)
}

@Composable
private fun LoadingBody(text: String) {
    Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator(color = SetupAccent)
        Spacer(modifier = Modifier.height(16.dp))
        Text(text, style = GimoTypography.bodyMedium.copy(color = GimoText.secondary), textAlign = TextAlign.Center)
    }
}

@Composable
private fun InputField(value: String, onValueChange: (String) -> Unit, placeholder: String, onDone: () -> Unit) {
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        singleLine = true,
        textStyle = GimoTypography.bodyLarge.copy(color = GimoText.primary),
        cursorBrush = SolidColor(SetupAccent),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { onDone() }),
        modifier = Modifier.fillMaxWidth(),
        decorationBox = { inner ->
            Box(modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(GimoSurfaces.surface0).border(1.dp, GimoBorders.primary, RoundedCornerShape(14.dp)).padding(horizontal = 16.dp, vertical = 14.dp)) {
                if (value.isBlank()) Text(placeholder, style = GimoTypography.bodyLarge.copy(color = GimoText.tertiary))
                inner()
            }
        },
    )
}

@Composable
private fun CodeField(code: String, onCodeChange: (String) -> Unit) {
    BasicTextField(
        value = code,
        onValueChange = { onCodeChange(it.filter(Char::isDigit).take(6)) },
        singleLine = true,
        textStyle = GimoTypography.headlineLarge.copy(color = Color.Transparent),
        cursorBrush = SolidColor(SetupAccent),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
        modifier = Modifier.fillMaxWidth(),
        decorationBox = { inner ->
            Box(modifier = Modifier.fillMaxWidth()) {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    repeat(6) { index ->
                        val char = code.getOrNull(index)?.toString().orEmpty()
                        val active = code.length == index || (code.length == 6 && index == 5)
                        Box(modifier = Modifier.weight(1f).clip(RoundedCornerShape(14.dp)).background(GimoSurfaces.surface0).border(1.dp, if (active) SetupAccent else GimoBorders.primary, RoundedCornerShape(14.dp)).padding(vertical = 18.dp), contentAlignment = Alignment.Center) {
                            Text(char.ifBlank { "•" }, fontFamily = GimoMono, fontWeight = FontWeight.Bold, fontSize = 20.sp, color = if (char.isBlank()) GimoText.tertiary else GimoText.primary)
                        }
                    }
                }
                Box(modifier = Modifier.fillMaxSize().background(Color.Transparent.copy(alpha = 0.01f))) { inner() }
            }
        },
    )
}

private val FitOptimal = Color(0xFF4ADE80)
private val FitComfortable = Color(0xFF60A5FA)
private val FitTight = Color(0xFFEAB308)
private val FitOverload = Color(0xFFEF4444)

private fun fitColor(level: String): Color = when (level) {
    "optimal" -> FitOptimal
    "comfortable" -> FitComfortable
    "tight" -> FitTight
    "overload" -> FitOverload
    else -> FitComfortable
}

/** Resource ID del label localizado para el nivel de encaje del modelo.
 *  ``null`` si el level no está en el catálogo (caller fallback a ``level.uppercase()``). */
private fun fitLabelResId(level: String): Int? = when (level) {
    "optimal" -> R.string.rec_fit_optimal
    "comfortable" -> R.string.rec_fit_comfortable
    "tight" -> R.string.rec_fit_tight
    "overload" -> R.string.rec_fit_overload
    else -> null
}

@Composable
private fun ModelCard(model: ModelInfo, onClick: () -> Unit) {
    val rec = model.recommendation
    val accent = if (rec != null) fitColor(rec.fitLevel) else SetupAccent
    val isRecommended = rec?.recommended == true
    val isOverload = rec?.fitLevel == "overload"

    Column(modifier = Modifier
        .fillMaxWidth()
        .clip(RoundedCornerShape(16.dp))
        .background(GimoSurfaces.surface0)
        .border(
            width = if (isRecommended) 2.dp else 1.dp,
            color = if (isRecommended) accent.copy(alpha = 0.7f) else GimoBorders.primary,
            shape = RoundedCornerShape(16.dp),
        )
        .clickable(onClick = onClick)
        .padding(16.dp)
    ) {
        // Header: name + recommended badge
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(model.name, fontFamily = GimoDisplay, fontWeight = FontWeight.Bold, fontSize = 16.sp, color = GimoText.primary, modifier = Modifier.weight(1f))
            if (isRecommended) {
                Pill(stringResource(R.string.rec_badge_recommended), accent)
            }
        }

        Spacer(modifier = Modifier.height(6.dp))

        // Tags: params + quant + fit level
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Pill(model.params.ifBlank { "?" }, SetupAccent)
            Pill(model.quantization.ifBlank { "gguf" }, GimoAccents.green)
            if (rec != null) {
                val fitResId = fitLabelResId(rec.fitLevel)
                val fitText = if (fitResId != null) stringResource(fitResId) else rec.fitLevel.uppercase()
                Pill(fitText, accent)
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Resource bar: RAM usage vs device RAM
        if (rec != null && rec.deviceRamGb > 0) {
            Text(stringResource(R.string.rec_device_load), style = GimoTypography.labelLarge.copy(color = GimoText.tertiary))
            Spacer(modifier = Modifier.height(6.dp))
            // Bar
            val ratio = (rec.estimatedRamGb / rec.deviceRamGb).coerceIn(0f, 1f)
            Box(modifier = Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(999.dp)).background(GimoSurfaces.surface3)) {
                Box(modifier = Modifier.fillMaxWidth(ratio).height(10.dp).clip(RoundedCornerShape(999.dp)).background(accent))
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                stringResource(
                    R.string.rec_ram_format,
                    String.format("%.1f", rec.estimatedRamGb),
                    String.format("%.0f", rec.deviceRamGb),
                ),
                style = GimoTypography.labelLarge.copy(color = accent),
            )

            Spacer(modifier = Modifier.height(10.dp))

            // Stats row
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    Text("~${rec.estimatedTokensPerSec.toInt()} tok/s", style = GimoTypography.bodyMedium.copy(color = GimoText.primary, fontWeight = FontWeight.Bold))
                    Text(stringResource(R.string.rec_stat_speed), style = GimoTypography.labelLarge.copy(color = GimoText.tertiary))
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("~${rec.estimatedBatteryDrainPctHr.toInt()}%/h", style = GimoTypography.bodyMedium.copy(color = if (rec.estimatedBatteryDrainPctHr > 20) FitOverload else GimoText.primary, fontWeight = FontWeight.Bold))
                    Text(stringResource(R.string.rec_stat_battery), style = GimoTypography.labelLarge.copy(color = GimoText.tertiary))
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text(rec.recommendedMode.uppercase(), style = GimoTypography.bodyMedium.copy(color = accent, fontWeight = FontWeight.Bold))
                    Text(stringResource(R.string.rec_stat_mode), style = GimoTypography.labelLarge.copy(color = GimoText.tertiary))
                }
            }

            // Impact text
            if (rec.impact.isNotBlank()) {
                Spacer(modifier = Modifier.height(10.dp))
                Text(rec.impact, style = GimoTypography.bodySmall.copy(color = GimoText.secondary, lineHeight = 16.sp))
            }

            // Warnings
            if (rec.warnings.isNotEmpty()) {
                Spacer(modifier = Modifier.height(8.dp))
                rec.warnings.forEach { warning ->
                    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                        Text("!", style = GimoTypography.labelLarge.copy(color = FitOverload, fontWeight = FontWeight.Bold))
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(warning, style = GimoTypography.bodySmall.copy(color = FitOverload.copy(alpha = 0.8f)))
                    }
                }
            }

            // Overload disclaimer
            if (isOverload) {
                Spacer(modifier = Modifier.height(8.dp))
                Box(modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(FitOverload.copy(alpha = 0.1f)).border(1.dp, FitOverload.copy(alpha = 0.3f), RoundedCornerShape(10.dp)).padding(10.dp)) {
                    Text(stringResource(R.string.rec_run_at_your_own_risk), style = GimoTypography.labelLarge.copy(color = FitOverload, fontWeight = FontWeight.Bold), textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                }
            }
        } else {
            // No recommendation data — basic info only
            Text(formatBytes(model.sizeBytes), style = GimoTypography.bodyMedium.copy(color = GimoText.secondary))
        }
    }
}

@Composable
private fun PrimaryAction(text: String, enabled: Boolean, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = enabled, shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = SetupAccent, contentColor = Color(0xFF07140C), disabledContainerColor = SetupAccent.copy(alpha = 0.35f), disabledContentColor = Color(0xFF07140C).copy(alpha = 0.5f)), modifier = Modifier.fillMaxWidth()) {
        Text(text.uppercase(), fontFamily = GimoMono, fontWeight = FontWeight.Bold, fontSize = 11.sp, letterSpacing = 1.sp)
    }
}

@Composable
private fun SecondaryAction(text: String, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, shape = RoundedCornerShape(14.dp), border = BorderStroke(1.dp, GimoBorders.primary), colors = ButtonDefaults.outlinedButtonColors(contentColor = GimoText.secondary), modifier = Modifier.fillMaxWidth()) {
        Text(text.uppercase(), fontFamily = GimoMono, fontWeight = FontWeight.Medium, fontSize = 10.sp, letterSpacing = 0.8.sp)
    }
}

@Composable
private fun Pill(text: String, accent: Color) {
    Row(modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(accent.copy(alpha = 0.12f)).border(1.dp, accent.copy(alpha = 0.35f), RoundedCornerShape(999.dp)).padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(modifier = Modifier.size(6.dp).clip(CircleShape).background(accent))
        Text(text, style = GimoTypography.labelLarge.copy(color = accent))
    }
}

@Composable
private fun Banner(message: String, accent: Color) {
    Box(modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(accent.copy(alpha = 0.08f)).border(1.dp, accent.copy(alpha = 0.3f), RoundedCornerShape(14.dp)).padding(14.dp)) {
        Text(message, style = GimoTypography.bodyMedium.copy(color = if (accent == ErrorAccent) accent else GimoText.primary))
    }
}

@Composable
private fun SetupModeSelector(
    selectedMode: String,
    onSelect: (String) -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            "DEVICE MODE",
            style = GimoTypography.labelLarge.copy(color = GimoText.tertiary),
        )
        Spacer(modifier = Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
            SetupModeChip(
                label = "INFERENCE",
                accent = MeshModeColors.inference,
                selected = selectedMode == "inference",
                onClick = { onSelect("inference") },
                modifier = Modifier.weight(1f),
            )
            SetupModeChip(
                label = "UTILITY",
                accent = MeshModeColors.utility,
                selected = selectedMode == "utility",
                onClick = { onSelect("utility") },
                modifier = Modifier.weight(1f),
            )
        }
        Spacer(modifier = Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
            SetupModeChip(
                label = "SERVER",
                accent = MeshModeColors.server,
                selected = selectedMode == "server",
                onClick = { onSelect("server") },
                modifier = Modifier.weight(1f),
            )
            SetupModeChip(
                label = "HYBRID",
                accent = MeshModeColors.hybrid,
                selected = selectedMode == "hybrid",
                onClick = { onSelect("hybrid") },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun SetupModeChip(
    label: String,
    accent: Color,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(if (selected) accent.copy(alpha = 0.14f) else GimoSurfaces.surface0)
            .border(
                width = if (selected) 2.dp else 1.dp,
                color = if (selected) accent.copy(alpha = 0.7f) else GimoBorders.primary,
                shape = RoundedCornerShape(14.dp),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 14.dp),
    ) {
        Text(
            text = label,
            style = GimoTypography.labelLarge.copy(
                color = if (selected) accent else GimoText.secondary,
                fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
            ),
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

private fun formatBytes(bytes: Long): String {
    if (bytes <= 0) return "0 B"
    val units = listOf("B", "KB", "MB", "GB", "TB")
    var value = bytes.toDouble()
    var index = 0
    while (value >= 1024 && index < units.lastIndex) {
        value /= 1024
        index += 1
    }
    return if (value >= 10 || index == 0) "${value.toInt()} ${units[index]}" else String.format("%.1f %s", value, units[index])
}

private fun stepLabel(step: SetupStep): String = when (step) {
    SetupStep.Welcome -> "WELCOME"
    SetupStep.QRScanner -> "SCAN QR"
    SetupStep.CoreUrl -> "CORE URL"
    SetupStep.ManualCode -> "REDEEM CODE"
    SetupStep.Enrolling -> "ENROLLING"
    SetupStep.WaitApproval -> "WAITING"
    SetupStep.ModelSelect -> "MODEL CATALOG"
    SetupStep.Downloading -> "DOWNLOADING"
    SetupStep.Done -> "COMPLETE"
}

private fun normalizeCoreUrl(raw: String): String {
    val trimmed = raw.trim().trimEnd('/')
    if (trimmed.isBlank()) return ""
    return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "http://$trimmed"
}

/**
 * G26: detect Android emulator to pre-populate the wizard's Core URL with
 * the emulator's loopback-to-host alias (10.0.2.2). Real hardware relies on
 * mDNS discovery / manual entry because the host's LAN IP is unpredictable.
 */
private fun isAndroidEmulator(): Boolean {
    val fp = android.os.Build.FINGERPRINT.orEmpty().lowercase()
    val hw = android.os.Build.HARDWARE.orEmpty().lowercase()
    val product = android.os.Build.PRODUCT.orEmpty().lowercase()
    val model = android.os.Build.MODEL.orEmpty().lowercase()
    return fp.startsWith("generic") ||
        fp.startsWith("unknown") ||
        hw == "goldfish" || hw == "ranchu" ||
        product.contains("sdk") ||
        product.contains("emulator") ||
        model.contains("emulator") ||
        model.contains("android sdk")
}
