package com.gredinlabs.gimomesh

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.gredinlabs.gimomesh.data.store.SettingsStore
import com.gredinlabs.gimomesh.ui.MeshViewModel
import com.gredinlabs.gimomesh.ui.navigation.GimoMeshNavHost
import com.gredinlabs.gimomesh.ui.theme.GimoMeshTheme
import com.gredinlabs.gimomesh.ui.theme.GimoSurfaces
import kotlinx.coroutines.runBlocking

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Accept configuration via intent extras (ADB provisioning)
        intent?.getStringExtra("config_token")?.let { token ->
            val store = (application as GimoMeshApp).settingsStore
            runBlocking { store.updateToken(token) }
        }
        intent?.getStringExtra("config_core_url")?.let { url ->
            val store = (application as GimoMeshApp).settingsStore
            runBlocking { store.updateCoreUrl(url) }
        }
        intent?.getStringExtra("config_device_mode")?.let { mode ->
            val store = (application as GimoMeshApp).settingsStore
            runBlocking { store.updateDeviceMode(mode) }
        }

        // Deep link: gimo://enroll?code=XXXXXX&host=IP&port=9325
        val deepLinkCode = intent?.data?.getQueryParameter("code") ?: ""
        val deepLinkHost = intent?.data?.getQueryParameter("host") ?: ""
        val deepLinkPort = intent?.data?.getQueryParameter("port") ?: "9325"
        if (deepLinkCode.isNotBlank() && deepLinkHost.isNotBlank()) {
            val store = (application as GimoMeshApp).settingsStore
            runBlocking {
                store.updateCoreUrl("http://$deepLinkHost:$deepLinkPort")
            }
        }

        val autoStart = intent?.getBooleanExtra("auto_start_mesh", false) == true

        setContent {
            GimoMeshTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = GimoSurfaces.surface0,
                ) {
                    val viewModel: MeshViewModel = viewModel()

                    // BLE wake auto-start — runs once, not on every recomposition
                    LaunchedEffect(autoStart) {
                        if (autoStart && !viewModel.state.value.isMeshRunning) {
                            viewModel.toggleMesh()
                        }
                    }

                    GimoMeshNavHost(
                        viewModel = viewModel,
                        deepLinkCode = deepLinkCode,
                        deepLinkHost = deepLinkHost,
                        deepLinkPort = deepLinkPort,
                    )
                }
            }
        }
    }
}
