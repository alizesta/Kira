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
import ai.kira.mobile.core.KiraContainer
import ai.kira.mobile.data.voice.GeminiLiveVoiceSession
import ai.kira.mobile.ui.theme.KiraPalette

@Composable
internal fun KiraVoiceScreen() {
    val context = LocalContext.current
    val container = remember { KiraContainer(context) }
    val handler = remember { Handler(Looper.getMainLooper()) }
    var apiKey by remember { mutableStateOf("") }
    var keySaved by remember { mutableStateOf(container.voiceCredentials.hasApiKey()) }
    var status by remember { mutableStateOf("Gemini Live از مکالمه صوتی دوطرفه پشتیبانی می‌کند.") }
    var callActive by remember { mutableStateOf(false) }
    var muted by remember { mutableStateOf(false) }
    var session by remember { mutableStateOf<GeminiLiveVoiceSession?>(null) }
    val transcript = remember { mutableStateListOf<String>() }

    fun stopCall() {
        val current = session
        session = null
        callActive = false
        muted = false
        current?.stop()
    }

    fun startCall() {
        if (callActive) return
        val key = runCatching { container.voiceCredentials.readApiKey() }.getOrElse {
            status = it.message ?: "کلید Gemini Live ذخیره نشده است."
            return
        }
        transcript.clear()
        val live = container.createGeminiLiveSession(
            apiKey = key,
            onStatus = { message ->
                handler.post {
                    status = message
                    if (message.contains("قطع شد") || message.contains("ناموفق") || message.contains("بسته شد") || message.contains("متوقف شد")) {
                        callActive = false
                        muted = false
                        session = null
                    }
                }
            },
            onTranscript = { speaker, text ->
                handler.post {
                    transcript.add(speaker + ": " + text)
                    if (transcript.size > 100) transcript.removeAt(0)
                }
            }
        )
        session = live
        callActive = true
        muted = false
        try {
            live.start()
        } catch (error: Exception) {
            session = null
            callActive = false
            status = error.message ?: "شروع تماس ناموفق بود."
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) startCall() else status = "برای تماس زنده باید اجازه دسترسی به میکروفون بدهی."
    }

    DisposableEffect(session) {
        onDispose { session?.stop() }
    }

    Column(
        Modifier.fillMaxSize().background(KiraPalette.background)
            .verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("تماس صوتی زنده", color = KiraPalette.onBackground, fontSize = 25.sp, fontWeight = FontWeight.Bold)
        Text(
            "مکالمه دوطرفه مستقیم با Gemini Live؛ صدا به‌صورت PCM زنده ارسال و پاسخ صوتی هم‌زمان پخش می‌شود. هزینه و محدودیت حساب Google را بررسی کن.",
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
                        enabled = !callActive
                    )
                    Button(
                        onClick = {
                            runCatching { container.voiceCredentials.saveApiKey(apiKey) }
                                .onSuccess {
                                    apiKey = ""
                                    keySaved = true
                                    status = "کلید Gemini Live با Android Keystore رمزنگاری شد."
                                }
                                .onFailure { status = it.message ?: "ذخیره کلید ناموفق بود." }
                        },
                        enabled = apiKey.isNotBlank() && !callActive
                    ) { Text("ذخیره امن کلید") }
                } else {
                    Text("کلید ذخیره شده است؛ مقدار آن در صفحه نمایش داده نمی‌شود.", color = KiraPalette.muted, fontSize = 12.sp)
                    OutlinedButton(
                        onClick = {
                            container.voiceCredentials.clear()
                            keySaved = false
                            status = "کلید Gemini Live حذف شد."
                        },
                        enabled = !callActive
                    ) { Text("حذف کلید") }
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
                        enabled = keySaved,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("شروع تماس زنده") }
                } else {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = {
                                val next = !muted
                                runCatching { session?.setMuted(next) }
                                    .onSuccess { muted = next }
                                    .onFailure { status = it.message ?: "تغییر وضعیت میکروفون ناموفق بود." }
                            },
                            modifier = Modifier.weight(1f)
                        ) { Text(if (muted) "فعال‌کردن میکروفون" else "بی‌صداکردن") }
                        Button(onClick = { stopCall() }, modifier = Modifier.weight(1f)) {
                            Text("پایان تماس")
                        }
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
