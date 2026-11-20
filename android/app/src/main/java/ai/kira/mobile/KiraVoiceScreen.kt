package ai.kira.mobile

import android.Manifest
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.kira.mobile.application.voice.VoiceCallState
import ai.kira.mobile.application.KiraContainer
import ai.kira.mobile.ui.theme.KiraPalette
import java.util.concurrent.Executors

@Composable
internal fun KiraVoiceScreen(container: KiraContainer) {
    val context = LocalContext.current
    val handler = remember { Handler(Looper.getMainLooper()) }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val voice = container.voice
    var apiKey by remember { mutableStateOf("") }
    var keySaved by remember { mutableStateOf(voice.hasApiKey()) }
    var status by remember { mutableStateOf("Gemini Live از مکالمه صوتی دوطرفه پشتیبانی می‌کند.") }
    var callActive by remember { mutableStateOf(voice.isActive()) }
    var muted by remember { mutableStateOf(voice.isMuted()) }
    var busy by remember { mutableStateOf(false) }
    val transcript = remember { mutableStateListOf<String>() }

    DisposableEffect(executor, voice) {
        onDispose {
            runCatching { voice.stop() }
            executor.shutdownNow()
        }
    }

    fun applyVoiceState() {
        val current = voice.state
        callActive = current is VoiceCallState.Connecting ||
            current is VoiceCallState.Connected ||
            current is VoiceCallState.Muted
        muted = current is VoiceCallState.Muted
    }

    fun saveKey() {
        val key = apiKey.trim()
        if (busy || key.isBlank()) return
        busy = true
        executor.execute {
            try {
                voice.saveApiKey(key)
                handler.post {
                    apiKey = ""
                    keySaved = true
                    status = "کلید Gemini Live با Android Keystore رمزنگاری شد."
                    busy = false
                }
            } catch (error: Exception) {
                handler.post {
                    status = error.message ?: "ذخیره کلید ناموفق بود."
                    busy = false
                }
            }
        }
    }

    fun clearKey() {
        if (busy || callActive) return
        busy = true
        executor.execute {
            try {
                voice.clearApiKey()
                handler.post {
                    keySaved = false
                    apiKey = ""
                    status = "کلید Gemini Live حذف شد."
                    busy = false
                }
            } catch (error: Exception) {
                handler.post {
                    status = error.message ?: "حذف کلید ناموفق بود."
                    busy = false
                }
            }
        }
    }

    fun stopCall() {
        if (busy) return
        busy = true
        executor.execute {
            try {
                voice.stop()
                handler.post {
                    applyVoiceState()
                    status = "تماس صوتی پایان یافت."
                    busy = false
                }
            } catch (error: Exception) {
                handler.post {
                    status = error.message ?: "پایان تماس ناموفق بود."
                    busy = false
                    applyVoiceState()
                }
            }
        }
    }

    fun startCall() {
        if (busy || callActive) return
        transcript.clear()
        busy = true
        status = "در حال اتصال به Gemini Live…"
        executor.execute {
            try {
                voice.start(
                    onStatus = { message ->
                        handler.post {
                            status = message
                            applyVoiceState()
                        }
                    },
                    onTranscript = { speaker, text ->
                        handler.post {
                            transcript.add(speaker + ": " + text)
                            if (transcript.size > 100) transcript.removeAt(0)
                        }
                    }
                )
                handler.post {
                    applyVoiceState()
                    busy = false
                }
            } catch (error: Exception) {
                handler.post {
                    applyVoiceState()
                    status = error.message ?: "شروع تماس ناموفق بود."
                    busy = false
                }
            }
        }
    }

    fun toggleMute() {
        if (busy || !callActive) return
        val next = !muted
        busy = true
        executor.execute {
            try {
                voice.setMuted(next)
                handler.post {
                    applyVoiceState()
                    status = if (next) "میکروفون بی‌صداست." else "تماس زنده است؛ می‌توانی صحبت کنی."
                    busy = false
                }
            } catch (error: Exception) {
                handler.post {
                    status = error.message ?: "تغییر وضعیت میکروفون ناموفق بود."
                    applyVoiceState()
                    busy = false
                }
            }
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) startCall()
        else status = "برای تماس زنده باید اجازه دسترسی به میکروفون بدهی."
    }

    Column(
        Modifier.fillMaxSize().background(KiraPalette.background)
            .verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("تماس صوتی زنده", color = KiraPalette.onBackground, fontSize = 25.sp, fontWeight = FontWeight.Bold)
        Text(
            "مکالمه دوطرفه مستقیم با Gemini Live؛ صدا به‌صورت PCM زنده ارسال و پاسخ صوتی هم‌زمان پخش می‌شود. هزینه و محدودیت حساب Google را پیش از تماس بررسی کن.",
            color = KiraPalette.muted, fontSize = 12.sp, lineHeight = 18.sp
        )

        Surface(color = KiraPalette.surface, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("اتصال Gemini Live", color = KiraPalette.onBackground, fontWeight = FontWeight.SemiBold)
                if (!keySaved || apiKey.isNotBlank()) {
                    OutlinedTextField(
                        value = apiKey,
                        onValueChange = { apiKey = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Gemini API Key") },
                        visualTransformation = PasswordVisualTransformation(),
                        singleLine = true,
                        enabled = !callActive && !busy
                    )
                    Button(onClick = { saveKey() }, enabled = apiKey.isNotBlank() && !callActive && !busy) {
                        Text(if (busy) "در حال ذخیره…" else "ذخیره امن کلید")
                    }
                } else {
                    Text("کلید ذخیره شده است؛ مقدار آن در صفحه نمایش داده نمی‌شود.", color = KiraPalette.muted, fontSize = 12.sp)
                    OutlinedButton(onClick = { clearKey() }, enabled = !callActive && !busy) { Text("حذف کلید") }
                }
            }
        }

        Surface(color = KiraPalette.surface, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Gemini 3.8 Live", color = KiraPalette.primary, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                Text(status, color = KiraPalette.muted, fontSize = 12.sp, lineHeight = 18.sp)
                if (!callActive) {
                    Button(
                        onClick = {
                            if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                                startCall()
                            } else {
                                permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                            }
                        },
                        enabled = keySaved && !busy,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text(if (busy) "در حال اتصال…" else "شروع تماس زنده") }
                } else {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = { toggleMute() },
                            enabled = !busy,
                            modifier = Modifier.weight(1f)
                        ) { Text(if (muted) "فعال‌کردن میکروفون" else "بی‌صداکردن") }
                        Button(
                            onClick = { stopCall() },
                            enabled = !busy,
                            modifier = Modifier.weight(1f)
                        ) { Text("پایان تماس") }
                    }
                }
            }
        }

        if (transcript.isNotEmpty()) {
            Text("رونوشت زنده", color = KiraPalette.onBackground, fontWeight = FontWeight.SemiBold)
            transcript.forEach { line ->
                Surface(color = KiraPalette.surface, shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
                    Text(line, modifier = Modifier.padding(12.dp), color = KiraPalette.onBackground, fontSize = 13.sp, lineHeight = 19.sp)
                }
            }
        }
    }
}
