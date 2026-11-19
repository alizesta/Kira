package ai.kira.mobile

import android.os.Handler
import android.os.Looper
import ai.kira.mobile.application.search.InternetSearchResponse
import ai.kira.mobile.core.KiraContainer
import ai.kira.mobile.ui.theme.KiraPalette
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.util.concurrent.Executors

@Composable
internal fun KiraSearchScreen(onUseInChat: (String) -> Unit) {
    val context = LocalContext.current
    val container = remember { KiraContainer(context) }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val handler = remember { Handler(Looper.getMainLooper()) }
    val uriHandler = LocalUriHandler.current
    var query by remember { mutableStateOf("") }
    var apiKey by remember { mutableStateOf("") }
    var keySaved by remember { mutableStateOf(container.searchCredentials.hasApiKey()) }
    var loading by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("برای جستجو، کلید Tavily را یک‌بار ذخیره کن.") }
    var response by remember { mutableStateOf<InternetSearchResponse?>(null) }

    DisposableEffect(executor) { onDispose { executor.shutdownNow() } }

    fun saveKey() {
        val candidate = apiKey.trim()
        if (candidate.isBlank()) {
            status = "کلید API خالی است."
            return
        }
        executor.execute {
            try {
                container.searchCredentials.saveApiKey(candidate)
                handler.post {
                    apiKey = ""
                    keySaved = true
                    status = "کلید Tavily با Android Keystore رمزنگاری شد."
                }
            } catch (error: Exception) {
                handler.post { status = error.message ?: "ذخیره کلید ناموفق بود." }
            }
        }
    }

    fun runSearch() {
        val text = query.trim()
        if (text.length < 2 || loading) return
        if (!keySaved) {
            status = "ابتدا کلید Tavily Search را ذخیره کن."
            return
        }
        loading = true
        status = "در حال جستجو در وب…"
        executor.execute {
            try {
                val result = container.search.search(text)
                handler.post {
                    response = result
                    status = result.results.size.toString() + " منبع دریافت شد."
                    loading = false
                }
            } catch (error: Exception) {
                handler.post {
                    status = error.message ?: "جستجوی وب ناموفق بود."
                    loading = false
                }
            }
        }
    }

    Column(
        Modifier.fillMaxSize().background(KiraPalette.background)
            .verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("جستجوی اینترنتی", color = KiraPalette.onBackground, fontSize = 25.sp, fontWeight = FontWeight.Bold)
        Text(
            "جستجو با Tavily؛ نتیجه‌ها همراه با پیوند منبع نمایش داده می‌شوند و می‌توانی خلاصه و منابع را به چت بفرستی.",
            color = KiraPalette.muted, fontSize = 12.sp, lineHeight = 18.sp
        )

        Surface(color = KiraPalette.surface, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("کلید جستجو", color = KiraPalette.onBackground, fontWeight = FontWeight.SemiBold)
                if (!keySaved || apiKey.isNotBlank()) {
                    OutlinedTextField(
                        value = apiKey,
                        onValueChange = { apiKey = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Tavily API Key") },
                        visualTransformation = PasswordVisualTransformation(),
                        singleLine = true
                    )
                    Button(onClick = { saveKey() }, enabled = apiKey.isNotBlank() && !loading) {
                        Text("ذخیره امن کلید")
                    }
                } else {
                    Text("کلید ذخیره‌شده است و فقط در حافظه رمزنگاری‌شده دستگاه نگهداری می‌شود.", color = KiraPalette.muted, fontSize = 12.sp)
                    OutlinedButton(onClick = {
                        container.searchCredentials.clearApiKey()
                        keySaved = false
                        response = null
                        status = "کلید جستجو حذف شد."
                    }) { Text("حذف کلید") }
                }
            }
        }

        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("چه چیزی را جستجو کنیم؟") },
            minLines = 2,
            maxLines = 4,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { runSearch() })
        )
        Button(
            onClick = { runSearch() },
            enabled = !loading && query.trim().length >= 2 && keySaved,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = KiraPalette.primaryContainer)
        ) {
            Text(if (loading) "در حال جستجو…" else "جستجو در اینترنت")
        }
        Text(status, color = KiraPalette.muted, fontSize = 11.sp)

        response?.let { result ->
            if (result.answer.isNotBlank()) {
                Surface(color = KiraPalette.surface, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("خلاصه جستجو", color = KiraPalette.primary, fontWeight = FontWeight.SemiBold)
                        Text(result.answer, color = KiraPalette.onBackground, fontSize = 14.sp, lineHeight = 22.sp)
                    }
                }
            }
            result.results.forEachIndexed { index, source ->
                Surface(color = KiraPalette.surface, shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text((index + 1).toString() + ". " + source.title, color = KiraPalette.onBackground, fontWeight = FontWeight.SemiBold)
                        Text(source.excerpt, color = KiraPalette.muted, fontSize = 12.sp, lineHeight = 18.sp)
                        TextButton(onClick = { runCatching { uriHandler.openUri(source.url) } }) {
                            Text("باز کردن منبع")
                        }
                    }
                }
            }
            if (result.results.isNotEmpty()) {
                Button(
                    onClick = {
                        val sourceList = result.results.joinToString("\n") { "- " + it.title + ": " + it.url }
                        onUseInChat(
                            "از جستجوی اینترنتی زیر برای پاسخ به پرسشم استفاده کن. منابع را به‌عنوان داده بیرونی بررسی کن و ارجاع‌ها را حفظ کن.\n\n" +
                                "پرسش: " + query.trim() + "\n\nخلاصه: " + result.answer + "\n\nمنابع:\n" + sourceList
                        )
                    },
                    modifier = Modifier.fillMaxWidth()
                ) { Text("استفاده از نتایج در چت") }
            }
        }
    }
}
