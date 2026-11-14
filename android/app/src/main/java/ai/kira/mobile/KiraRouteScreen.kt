package ai.kira.mobile

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.kira.mobile.core.KiraCoreClient
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

private data class KiraCloudRoute(
    val id: String,
    val provider: String,
    val model: String,
    val enabled: Boolean,
    val configured: Boolean
)

@Composable
internal fun KiraRouteScreen() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val preferences = remember {
        context.getSharedPreferences("kira_core_config", Context.MODE_PRIVATE)
    }
    val serverUrl = remember { preferences.getString("server_url", "") ?: "" }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val mainHandler = remember { Handler(Looper.getMainLooper()) }
    val routes = remember { mutableStateListOf<KiraCloudRoute>() }

    var providerId by remember { mutableStateOf("openrouter") }
    var apiKey by remember { mutableStateOf("") }
    var providerAccountId by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("Routeهای Cloud در Kira Core بین ویندوز و اندروید مشترک‌اند.") }

    DisposableEffect(executor) {
        onDispose { executor.shutdownNow() }
    }

    fun loadRoutes() {
        if (serverUrl.isBlank()) {
            status = "ابتدا آدرس سرور را در تنظیمات وارد کن."
            return
        }
        if (busy) return
        busy = true
        executor.execute {
            try {
                val client = KiraCoreClient(context, serverUrl)
                if (!client.hasSession()) throw IllegalStateException("ابتدا وارد حساب Kira شو.")
                val response = client.getSettings()
                val settings = response.optJSONObject("settings") ?: JSONObject()
                val routeArray = settings.optJSONArray("routes") ?: JSONArray()
                val configured = mutableSetOf<String>()
                val cloudRoutes = response.optJSONArray("cloud_routes") ?: JSONArray()
                for (i in 0 until cloudRoutes.length()) {
                    cloudRoutes.optJSONObject(i)?.optString("provider_id")?.takeIf { it.isNotBlank() }?.let(configured::add)
                }
                val result = mutableListOf<KiraCloudRoute>()
                for (i in 0 until routeArray.length()) {
                    val route = routeArray.optJSONObject(i) ?: continue
                    val provider = route.optString("provider")
                    if (provider.isBlank() || provider == "ollama") continue
                    result += KiraCloudRoute(
                        id = route.optString("id"),
                        provider = provider,
                        model = route.optString("model"),
                        enabled = route.optBoolean("enabled", true),
                        configured = provider in configured
                    )
                }
                mainHandler.post {
                    routes.clear()
                    routes.addAll(result)
                    status = if (result.isEmpty()) "هنوز Route ابری در حساب ذخیره نشده است. تنظیمات را ابتدا از ویندوز همگام کن یا کلید Provider اضافه کن."
                    else "Routeهای حساب مشترک بارگذاری شدند."
                    busy = false
                }
            } catch (error: Exception) {
                mainHandler.post {
                    status = error.message ?: "خواندن Routeها ناموفق بود."
                    busy = false
                }
            }
        }
    }

    LaunchedEffect(serverUrl) { loadRoutes() }

    fun saveCredential() {
        if (providerId.isBlank() || apiKey.isBlank() || busy) return
        if (serverUrl.isBlank()) {
            status = "آدرس سرور Kira Core تنظیم نشده است."
            return
        }
        busy = true
        status = "در حال ذخیره امن کلید Provider…"
        executor.execute {
            try {
                val client = KiraCoreClient(context, serverUrl)
                if (!client.hasSession()) throw IllegalStateException("ابتدا وارد حساب Kira شو.")
                client.saveProviderCredential(providerId.trim(), apiKey.trim(), providerAccountId.trim().ifBlank { null })
                mainHandler.post {
                    apiKey = ""
                    status = "کلید $providerId در Kira Core رمزنگاری و ذخیره شد."
                    busy = false
                    loadRoutes()
                }
            } catch (error: Exception) {
                mainHandler.post {
                    status = error.message ?: "ذخیره کلید ناموفق بود."
                    busy = false
                }
            }
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().background(Color(0xFF0B0E15)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column {
                Text("ROUTE MANAGER", color = Color(0xFFB9A5FF), fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                Text("مسیرهای مشترک", color = Color(0xFFF4F2FA), fontSize = 22.sp, fontWeight = FontWeight.Bold)
            }
            Button(onClick = { loadRoutes() }, enabled = !busy, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF242D40))) {
                Text("بازیابی")
            }
        }

        Surface(color = Color(0xFF151C2B), shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("افزودن یا تغییر کلید Cloud", color = Color(0xFFF1EFF8), fontWeight = FontWeight.SemiBold)
                OutlinedTextField(
                    value = providerId,
                    onValueChange = { providerId = it },
                    label = { Text("شناسه Provider مثل openrouter یا groq") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = apiKey,
                    onValueChange = { apiKey = it },
                    label = { Text("API Key") },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = providerAccountId,
                    onValueChange = { providerAccountId = it },
                    label = { Text("Account ID (فقط اگر لازم است)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Button(
                    onClick = { saveCredential() },
                    enabled = !busy && providerId.isNotBlank() && apiKey.isNotBlank(),
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF7661D8))
                ) { Text("ذخیره رمزنگاری‌شده روی سرور") }
            }
        }

        Text("اولویت‌ها و وضعیت Providerها", color = Color(0xFFF1EFF8), fontWeight = FontWeight.SemiBold)
        LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(routes, key = { it.id }) { route ->
                Surface(color = Color(0xFF151C2B), shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier.padding(13.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                            Text(route.provider, color = Color(0xFFF1EFF8), fontWeight = FontWeight.SemiBold)
                            Text(route.model.ifBlank { "مدل انتخاب نشده" }, color = Color(0xFF9BA5B8), fontSize = 11.sp)
                            Text(if (route.enabled) "فعال" else "غیرفعال", color = Color(0xFFB9A5FF), fontSize = 10.sp)
                        }
                        Text(
                            if (route.configured) "کلید ذخیره است" else "بدون کلید",
                            color = if (route.configured) Color(0xFF8FD6B0) else Color(0xFFFFC27A),
                            fontSize = 10.sp
                        )
                    }
                }
            }
            if (routes.isEmpty()) item {
                Text("لیست Route پس از اتصال حساب و همگام‌سازی تنظیمات ظاهر می‌شود.", color = Color(0xFF8995AA), fontSize = 12.sp)
            }
        }
        if (busy) CircularProgressIndicator(color = Color(0xFFB9A5FF), modifier = Modifier.height(22.dp))
        Text(status, color = Color(0xFF9BA5B8), fontSize = 10.sp, lineHeight = 15.sp)
        Spacer(Modifier.height(2.dp))
    }
}
