package ai.kira.mobile

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/** Thin Android entry point: lifecycle and inbound intents only. */
class MainActivity : ComponentActivity() {
    private var overlayRequest by mutableStateOf<OverlayLaunchRequest?>(null)
    private var overlaySequence = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        submitOverlayIntent(intent)
        val container = (application as KiraMobileApplication).container
        setContent { KiraApp(container, overlayRequest) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        submitOverlayIntent(intent)
    }

    private fun submitOverlayIntent(intent: Intent?) {
        val route = intent?.getStringExtra(EXTRA_OPEN_ROUTE) ?: return
        overlaySequence += 1
        overlayRequest = OverlayLaunchRequest(route, intent.getStringExtra(EXTRA_CHAT_TEXT).orEmpty(), overlaySequence)
    }

    companion object {
        const val EXTRA_OPEN_ROUTE = "ai.kira.mobile.extra.OPEN_ROUTE"
        const val EXTRA_CHAT_TEXT = "ai.kira.mobile.extra.CHAT_TEXT"
    }
}
