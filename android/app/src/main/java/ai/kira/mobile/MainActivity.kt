package ai.kira.mobile

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.kira.mobile.assistant.AiAssistantOverlayService
import ai.kira.mobile.core.KiraCoreClient
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            KiraApp()
        }
    }
}

private enum class KiraTab(val label: String, val glyph: String) {
    CHAT("چت", "✦"),
    ASSISTANT("دستیار", "◉"),
    ROUTE("Route", "⇄"),
    MEMORY("حافظه", "▤"),
    SETTINGS("تنظیمات", "⚙")
}

@Composable
private fun KiraApp() {
    val context = LocalContext.current
    var selectedTab by remember { mutableStateOf(KiraTab.ASSISTANT) }
    var hasOverlayPermission by remember {
        mutableStateOf(Settings.canDrawOverlays(context))
    }
    var overlayStarted by remember { mutableStateOf(false) }

    val overlaySettingsLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) {
        hasOverlayPermission = Settings.canDrawOverlays(context)
    }

    MaterialTheme {
        Scaffold(
            containerColor = Color(0xFF0B0E15),
            bottomBar = {
                NavigationBar(containerColor = Color(0xFF111725)) {
                    KiraTab.entries.forEach { tab ->
                        NavigationBarItem(
                            selected = selectedTab == tab,
                            onClick = { selectedTab = tab },
                            icon = { Text(tab.glyph, fontSize = 17.sp) },
                            label = { Text(tab.label, fontSize = 10.sp) }
                        )
                    }
                }
            }
        ) { contentPadding ->
            Surface(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(contentPadding),
                color = Color(0xFF0B0E15)
            ) {
                when (selectedTab) {
                    KiraTab.ASSISTANT -> AssistantScreen(
                        hasOverlayPermission = hasOverlayPermission,
                        overlayStarted = overlayStarted,
                        onRequestOverlayPermission = {
                            val intent = Intent(
                                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                Uri.parse("package:" + context.packageName)
                            )
                            overlaySettingsLauncher.launch(intent)
                        },
                        onStartOverlay = {
                            val intent = Intent(context, AiAssistantOverlayService::class.java)
                                .setAction(AiAssistantOverlayService.ACTION_START)
                            overlayStarted = context.startService(intent) != null
                        },
                        onStopOverlay = {
                            val intent = Intent(context, AiAssistantOverlayService::class.java)
                                .setAction(AiAssistantOverlayService.ACTION_STOP)
                            context.startService(intent)
                            overlayStarted = false
                        }
                    )
                    KiraTab.CHAT -> PlaceholderScreen(
                        title = "چت شخصیت‌ها",
                        description = "چت Kira، Ren و Mika از همان Kira Core، همان تاریخچه و همان حساب ویندوز استفاده می‌کند. اتصال سرور در حال آماده‌سازی است."
                    )
                    KiraTab.ROUTE -> PlaceholderScreen(
                        title = "Route Manager",
                        description = "Routeهای Cloud، کلیدهای Provider و ترتیب Failover در سطح حساب مشترک‌اند. مدل‌های محلی فقط روی همان دستگاه نمایش داده می‌شوند."
                    )
                    KiraTab.MEMORY -> PlaceholderScreen(
                        title = "حافظه",
                        description = "حافظه‌ی بلندمدت و تاریخچه به حساب Kira متصل می‌شوند و با ورود به همان حساب روی ویندوز و موبایل بازیابی خواهند شد."
                    )
                    KiraTab.SETTINGS -> CoreAccountScreen()
                }
            }
        }
    }
}

@Composable
private fun CoreAccountScreen() {
    val context = LocalContext.current
    val preferences = remember {
        context.getSharedPreferences("kira_core_config", android.content.Context.MODE_PRIVATE)
    }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val mainHandler = remember { Handler(Looper.getMainLooper()) }

    var serverUrl by remember { mutableStateOf(preferences.getString("server_url", "") ?: "") }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var displayName by remember { mutableStateOf("") }
    var accountId by remember { mutableStateOf("") }
    var connected by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var status by remember {
        mutableStateOf("برای اتصال، آدرس HTTPS سرور Kira Core را وارد کن. سرور هنوز به‌صورت عمومی میزبانی نشده است.")
    }

    DisposableEffect(executor) {
        onDispose { executor.shutdownNow() }
    }

    fun runCoreAction(action: (KiraCoreClient) -> String) {
        if (busy) return
        val configuredUrl = serverUrl.trim()
        if (configuredUrl.isBlank()) {
            status = "اول آدرس سرور Kira Core را وارد کن."
            return
        }
        busy = true
        status = "در حال اتصال به Kira Core…"
        preferences.edit().putString("server_url", configuredUrl).apply()

        executor.execute {
            try {
                val client = KiraCoreClient(context, configuredUrl)
                val result = action(client)
                val stillSignedIn = client.hasSession()
                val currentAccountId = if (stillSignedIn) {
                    runCatching { client.account().optString("account_id") }.getOrDefault("")
                } else {
                    ""
                }
                mainHandler.post {
                    connected = stillSignedIn
                    accountId = currentAccountId
                    status = result
                    busy = false
                }
            } catch (error: Exception) {
                mainHandler.post {
                    status = error.message ?: "اتصال به Kira Core ناموفق بود."
                    connected = false
                    busy = false
                }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text(
            text = "حساب مشترک KIRA",
            color = Color(0xFFF4F2FA),
            fontSize = 24.sp,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = "با همین حساب در ویندوز و موبایل وارد می‌شوی. تنظیمات مشترک، تاریخچه، شخصیت‌ها و حافظه از یک Kira Core بازیابی می‌شوند.",
            color = Color(0xFF9BA5B8),
            fontSize = 13.sp,
            lineHeight = 20.sp
        )

        InfoPanel(
            title = "سرور Kira Core",
            description = "آدرس سرور خودت را وارد کن. برای استفاده از اینترنت باید سرور با HTTPS در دسترس باشد.",
            status = if (connected) "متصل" else "هنوز متصل نیست"
        ) {
            OutlinedTextField(
                value = serverUrl,
                onValueChange = { serverUrl = it },
                label = { Text("آدرس سرور، مثل https://kira.example.com") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
        }

        InfoPanel(
            title = "ورود یا ساخت حساب Kira",
            description = "فعلاً ورود با ایمیل و رمز عبور است. Google Sign-In بعداً به همین شناسه‌ی حساب متصل می‌شود.",
            status = if (connected) "حساب فعال" else "نیازمند ورود"
        ) {
            OutlinedTextField(
                value = email,
                onValueChange = { email = it },
                label = { Text("ایمیل") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                label = { Text("رمز عبور") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = displayName,
                onValueChange = { displayName = it },
                label = { Text("نام نمایشی (برای ساخت حساب)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Button(
                    onClick = {
                        runCoreAction { client ->
                            val session = client.register(email.trim(), password, displayName.trim())
                            "حساب ساخته شد: " + session.optString("account_id")
                        }
                    },
                    enabled = !busy && email.isNotBlank() && password.length >= 12,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF7661D8))
                ) {
                    Text("ساخت حساب")
                }
                OutlinedButton(
                    onClick = {
                        runCoreAction { client ->
                            val session = client.login(email.trim(), password)
                            "وارد شدی: " + session.optString("account_id")
                        }
                    },
                    enabled = !busy && email.isNotBlank() && password.isNotBlank(),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("ورود")
                }
            }
            OutlinedButton(
                onClick = {
                    runCoreAction { client ->
                        val account = client.account()
                        "نشست قبلی بازیابی شد: " + account.optString("account_id")
                    }
                },
                enabled = !busy && !connected && serverUrl.isNotBlank(),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("بازیابی نشست ذخیره‌شده")
            }
            if (connected) {
                Text(
                    text = "شناسه حساب: $accountId",
                    color = Color(0xFFB9A5FF),
                    fontSize = 11.sp
                )
                OutlinedButton(
                    onClick = {
                        runCoreAction { client ->
                            client.logout()
                            "از حساب Kira خارج شدی."
                        }
                        connected = false
                        accountId = ""
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !busy
                ) {
                    Text("خروج از حساب")
                }
            }
        }

        if (busy) {
            CircularProgressIndicator(color = Color(0xFFB9A5FF))
        }
        Text(
            text = status,
            color = if (connected) Color(0xFF8FD6B0) else Color(0xFFB9A5FF),
            fontSize = 12.sp,
            lineHeight = 18.sp
        )
        Text(
            text = "امنیت نشست: Tokenها با Android Keystore روی همین گوشی رمزنگاری می‌شوند. کلیدهای Provider روی سرور می‌مانند و داخل گوشی ذخیره نمی‌شوند.",
            color = Color(0xFF7F8A9E),
            fontSize = 11.sp,
            lineHeight = 17.sp
        )
    }
}

@Composable
private fun AssistantScreen(
    hasOverlayPermission: Boolean,
    overlayStarted: Boolean,
    onRequestOverlayPermission: () -> Unit,
    onStartOverlay: () -> Unit,
    onStopOverlay: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Text(
            text = "KIRA",
            color = Color(0xFFB9A5FF),
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 4.sp
        )
        Text(
            text = "دستیار هوشمند اندروید",
            color = Color(0xFFF4F2FA),
            fontSize = 25.sp,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = "کلاینت موبایل Kira؛ متصل به همان حساب و هسته‌ی ویندوز",
            color = Color(0xFF9BA5B8),
            fontSize = 13.sp
        )

        InfoPanel(
            title = "دسترسی سریع روی برنامه‌ها",
            description = "حباب شناور Kira را فعال کن تا از داخل برنامه‌های دیگر هم سریع به دستیار برگردی.",
            status = when {
                overlayStarted -> "حباب شناور فعال شده"
                hasOverlayPermission -> "مجوز نمایش روی برنامه‌ها آماده است"
                else -> "برای فعال‌سازی، مجوز نمایش روی برنامه‌ها لازم است"
            }
        ) {
            if (!hasOverlayPermission) {
                Button(
                    onClick = onRequestOverlayPermission,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFF7661D8)
                    )
                ) {
                    Text("دادن مجوز حباب شناور")
                }
            } else if (!overlayStarted) {
                Button(
                    onClick = onStartOverlay,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFF7661D8)
                    )
                ) {
                    Text("فعال‌کردن دستیار شناور")
                }
            } else {
                OutlinedButton(
                    onClick = onStopOverlay,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("خاموش‌کردن حباب")
                }
            }
        }

        InfoPanel(
            title = "درک محتوای صفحه",
            description = "معادل اندرویدی بخش Vision در Game Mode ویندوز: دستیار می‌تواند با اجازه‌ی صریح کاربر، محتوای صفحه را برای پاسخ به سؤال بررسی کند.",
            status = "در حال اتصال به Core مشترک"
        )

        InfoPanel(
            title = "فرمان صوتی",
            description = "تعامل صوتی و فعال‌سازی دستیار به موتور مشترک صدا متصل می‌شود.",
            status = "در حال ساخت"
        )

        Text(
            text = "حریم خصوصی: هیچ تصویری از صفحه یا صدایی در پس‌زمینه ضبط یا ارسال نمی‌شود. دریافت محتوای صفحه فقط پس از پیاده‌سازی و تأیید صریح هر نشست فعال خواهد شد.",
            color = Color(0xFF7F8A9E),
            fontSize = 11.sp,
            lineHeight = 17.sp
        )
    }
}

@Composable
private fun InfoPanel(
    title: String,
    description: String,
    status: String,
    actions: @Composable () -> Unit = {}
) {
    Surface(
        color = Color(0xFF151C2B),
        shape = RoundedCornerShape(20.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(9.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = title,
                    color = Color(0xFFF1EFF8),
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 15.sp
                )
                Text(
                    text = status,
                    color = Color(0xFFB9A5FF),
                    fontSize = 10.sp
                )
            }
            Text(
                text = description,
                color = Color(0xFFA2ADC0),
                fontSize = 12.sp,
                lineHeight = 19.sp
            )
            actions()
        }
    }
}

@Composable
private fun PlaceholderScreen(title: String, description: String) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.Start
    ) {
        Text(
            text = title,
            color = Color(0xFFF1EFF8),
            fontSize = 24.sp,
            fontWeight = FontWeight.Bold
        )
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = description,
            color = Color(0xFFA2ADC0),
            fontSize = 14.sp,
            lineHeight = 22.sp
        )
        Spacer(modifier = Modifier.height(18.dp))
        Text(
            text = "این بخش هنوز به موتور اصلی متصل نشده است.",
            color = Color(0xFFB9A5FF),
            fontSize = 12.sp
        )
    }
}
