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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.kira.mobile.core.KiraCoreClient
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

private data class KiraChatMessage(
    val id: String,
    val role: String,
    val content: String,
    val route: String = ""
)

@Composable
internal fun KiraChatScreen() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val preferences = remember {
        context.getSharedPreferences("kira_core_config", Context.MODE_PRIVATE)
    }
    val serverUrl = remember { preferences.getString("server_url", "") ?: "" }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val mainHandler = remember { Handler(Looper.getMainLooper()) }
    val messages = remember { mutableStateListOf<KiraChatMessage>() }
    val listState = rememberLazyListState()

    var conversationId by remember { mutableStateOf("") }
    var characterId by remember { mutableStateOf("kira") }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("در حال آماده‌سازی چت مشترک Kira…") }

    DisposableEffect(executor) {
        onDispose { executor.shutdownNow() }
    }

    fun loadHistory() {
        if (serverUrl.isBlank()) {
            status = "ابتدا آدرس Kira Core را در تنظیمات وارد کن و وارد حساب شو."
            return
        }
        if (busy) return
        val requestedCharacterId = characterId
        busy = true
        executor.execute {
            try {
                val client = KiraCoreClient(context, serverUrl)
                if (!client.hasSession()) {
                    throw IllegalStateException("برای استفاده از چت مشترک، ابتدا وارد حساب Kira شو.")
                }
                val list = client.conversations(requestedCharacterId).optJSONArray("items") ?: JSONArray()
                var selectedId = ""
                var loaded = JSONArray()
                if (list.length() > 0) {
                    val first = list.getJSONObject(0)
                    selectedId = first.optString("id")
                    loaded = client.messages(selectedId).optJSONArray("items") ?: JSONArray()
                } else {
                    selectedId = client.createConversation(requestedCharacterId).optString("id")
                }
                val result = mutableListOf<KiraChatMessage>()
                for (i in 0 until loaded.length()) {
                    val item = loaded.optJSONObject(i) ?: continue
                    result += KiraChatMessage(
                        id = item.optString("id", i.toString()),
                        role = item.optString("role"),
                        content = item.optString("content"),
                        route = item.optJSONObject("route")?.let {
                            listOf(it.optString("provider"), it.optString("model"))
                                .filter(String::isNotBlank).joinToString(" · ")
                        }.orEmpty()
                    )
                }
                mainHandler.post {
                    conversationId = selectedId
                    messages.clear()
                    messages.addAll(result)
                    status = if (result.isEmpty()) "به Kira Core وصل شدی. پیام اول را بفرست." else "تاریخچه از حساب مشترک بازیابی شد."
                    busy = false
                }
            } catch (error: Exception) {
                mainHandler.post {
                    status = error.message ?: "اتصال به Kira Core ناموفق بود."
                    busy = false
                }
            }
        }
    }

    LaunchedEffect(serverUrl, characterId) {
        conversationId = ""
        messages.clear()
        loadHistory()
    }
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    fun sendMessage() {
        val text = input.trim()
        if (text.isBlank() || busy) return
        if (serverUrl.isBlank()) {
            status = "ابتدا آدرس Kira Core را در تنظیمات وارد کن."
            return
        }
        val requestedCharacterId = characterId
        busy = true
        input = ""
        status = "Kira در حال پاسخ‌دادن است…"
        executor.execute {
            try {
                val client = KiraCoreClient(context, serverUrl)
                if (!client.hasSession()) {
                    throw IllegalStateException("ابتدا وارد حساب Kira شو.")
                }
                var id = conversationId
                if (id.isBlank()) id = client.createConversation("kira").optString("id")
                if (id.isBlank()) throw IllegalStateException("ساخت گفت‌وگو ناموفق بود.")
                val response = client.sendMessage(id, requestedCharacterId, text)
                val route = response.optJSONObject("route")?.let {
                    listOf(it.optString("provider"), it.optString("model"))
                        .filter(String::isNotBlank).joinToString(" · ")
                }.orEmpty()
                val userId = response.optString("user_message_id", System.nanoTime().toString())
                val assistantId = response.optString("assistant_message_id", (System.nanoTime() + 1).toString())
                val answer = response.optString("content")
                mainHandler.post {
                    conversationId = id
                    messages.add(KiraChatMessage(userId, "user", text))
                    messages.add(KiraChatMessage(assistantId, "assistant", answer, route))
                    status = if (route.isBlank()) "پاسخ از Kira Core" else "پاسخ از $route"
                    busy = false
                }
            } catch (error: Exception) {
                mainHandler.post {
                    messages.add(KiraChatMessage(System.nanoTime().toString(), "user", text))
                    status = error.message ?: "ارسال پیام ناموفق بود."
                    busy = false
                }
            }
        }
    }

    MaterialTheme {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(0xFF0B0E15))
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text("KIRA", color = Color(0xFFB9A5FF), fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 3.sp)
                    Text("چت مشترک", color = Color(0xFFF4F2FA), fontSize = 21.sp, fontWeight = FontWeight.Bold)
                }
                Button(
                    onClick = { loadHistory() },
                    enabled = !busy,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF242D40))
                ) { Text("بازیابی") }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(7.dp)
            ) {
                listOf("kira" to "Kira", "ren" to "Ren", "mika" to "Mika").forEach { (id, label) ->
                    Button(
                        onClick = { characterId = id },
                        enabled = !busy,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (characterId == id) Color(0xFF7661D8) else Color(0xFF20293A)
                        )
                    ) { Text(label) }
                }
            }

            LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                state = listState,
                verticalArrangement = Arrangement.spacedBy(9.dp)
            ) {
                if (messages.isEmpty()) {
                    item {
                        Text(
                            "تاریخچه‌ی چت از همان حساب Kira روی ویندوز و موبایل قابل بازیابی است.",
                            color = Color(0xFF8995AA),
                            fontSize = 13.sp,
                            lineHeight = 20.sp,
                            modifier = Modifier.padding(vertical = 20.dp)
                        )
                    }
                }
                items(messages, key = { it.id }) { message ->
                    val user = message.role == "user"
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = if (user) Arrangement.End else Arrangement.Start
                    ) {
                        Surface(
                            color = if (user) Color(0xFF493D79) else Color(0xFF151C2B),
                            shape = RoundedCornerShape(
                                topStart = 17.dp,
                                topEnd = 17.dp,
                                bottomStart = if (user) 17.dp else 5.dp,
                                bottomEnd = if (user) 5.dp else 17.dp
                            ),
                            modifier = Modifier.fillMaxWidth(0.88f)
                        ) {
                            Column(Modifier.padding(13.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                                Text(
                                    if (user) "تو" else "Kira",
                                    color = if (user) Color(0xFFE5DCFF) else Color(0xFFB9A5FF),
                                    fontSize = 10.sp,
                                    fontWeight = FontWeight.Bold
                                )
                                Text(message.content, color = Color(0xFFF0EFF6), fontSize = 14.sp, lineHeight = 21.sp)
                                if (!user && message.route.isNotBlank()) {
                                    Text(message.route, color = Color(0xFF8290A7), fontSize = 9.sp)
                                }
                            }
                        }
                    }
                }
                if (busy) {
                    item {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            CircularProgressIndicator(modifier = Modifier.height(18.dp), color = Color(0xFFB9A5FF), strokeWidth = 2.dp)
                            Text("در حال ارتباط با Kira Core…", color = Color(0xFF9BA5B8), fontSize = 11.sp)
                        }
                    }
                }
            }

            Text(status, color = Color(0xFF9BA5B8), fontSize = 10.sp, lineHeight = 15.sp)
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("پیامت را بنویس…") },
                    maxLines = 4,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(onSend = { sendMessage() }),
                    shape = RoundedCornerShape(18.dp)
                )
                Button(
                    onClick = { sendMessage() },
                    enabled = !busy && input.isNotBlank(),
                    modifier = Modifier.height(54.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF7661D8))
                ) { Text("ارسال") }
            }
        }
    }
}
