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
import androidx.compose.foundation.lazy.itemsIndexed
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.kira.mobile.core.KiraCoreClient
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

private data class KiraMemoryItem(val raw: JSONObject, val text: String)

@Composable
internal fun KiraMemoryScreen() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val preferences = remember {
        context.getSharedPreferences("kira_core_config", Context.MODE_PRIVATE)
    }
    val serverUrl = remember { preferences.getString("server_url", "") ?: "" }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val mainHandler = remember { Handler(Looper.getMainLooper()) }
    val items = remember { mutableStateListOf<KiraMemoryItem>() }

    var revision by remember { mutableStateOf(0) }
    var characterId by remember { mutableStateOf("kira") }
    var note by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("حافظه‌ی بلندمدت حساب Kira بین دستگاه‌ها مشترک است.") }

    DisposableEffect(executor) {
        onDispose { executor.shutdownNow() }
    }

    fun loadMemory() {
        if (serverUrl.isBlank()) {
            status = "ابتدا آدرس سرور را در تنظیمات وارد کن."
            return
        }
        if (busy) return
        val requestedCharacterId = characterId
        busy = true
        executor.execute {
            try {
                val client = KiraCoreClient(context, serverUrl)
                if (!client.hasSession()) throw IllegalStateException("ابتدا وارد حساب Kira شو.")
                val response = client.getMemory(requestedCharacterId)
                val array = response.optJSONArray("items") ?: JSONArray()
                val result = mutableListOf<KiraMemoryItem>()
                for (i in 0 until array.length()) {
                    val raw = array.optJSONObject(i) ?: continue
                    val text = raw.optString("text").ifBlank { raw.toString() }
                    result += KiraMemoryItem(raw, text)
                }
                mainHandler.post {
                    revision = response.optInt("revision", 0)
                    items.clear()
                    items.addAll(result)
                    status = "حافظه از حساب مشترک بازیابی شد."
                    busy = false
                }
            } catch (error: Exception) {
                mainHandler.post {
                    status = error.message ?: "بازیابی حافظه ناموفق بود."
                    busy = false
                }
            }
        }
    }

    LaunchedEffect(serverUrl, characterId) { items.clear(); loadMemory() }

    fun persist(updated: List<KiraMemoryItem>, successMessage: String) {
        if (busy) return
        val requestedCharacterId = characterId
        val expectedRevision = revision
        busy = true
        executor.execute {
            try {
                val client = KiraCoreClient(context, serverUrl)
                if (!client.hasSession()) throw IllegalStateException("ابتدا وارد حساب Kira شو.")
                val array = JSONArray()
                updated.forEach { array.put(it.raw) }
                val response = client.saveMemory(requestedCharacterId, expectedRevision, array)
                mainHandler.post {
                    revision = response.optInt("revision", revision + 1)
                    items.clear()
                    items.addAll(updated)
                    status = successMessage
                    busy = false
                }
            } catch (error: Exception) {
                mainHandler.post {
                    status = error.message ?: "ذخیره حافظه ناموفق بود."
                    busy = false
                }
            }
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().background(Color(0xFF0B0E15)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("حافظه‌ی مشترک KIRA", color = Color(0xFFF4F2FA), fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Text(
            "یادداشت‌هایی که اینجا ذخیره می‌کنی، همراه حساب Kira روی دستگاه‌های دیگر هم در دسترس خواهند بود.",
            color = Color(0xFF9BA5B8), fontSize = 12.sp, lineHeight = 19.sp
        )
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
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedTextField(
                value = note,
                onValueChange = { note = it },
                modifier = Modifier.weight(1f),
                label = { Text("چیزی برای به‌خاطر سپردن…") },
                maxLines = 3
            )
            Button(
                onClick = {
                    val text = note.trim()
                    if (text.isNotBlank()) {
                        val raw = JSONObject()
                            .put("text", text)
                            .put("source", "android")
                            .put("created_at", SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date()))
                        val updated = items.toList() + KiraMemoryItem(raw, text)
                        note = ""
                        persist(updated, "یادداشت در حافظه‌ی حساب ذخیره شد.")
                    }
                },
                enabled = !busy && note.isNotBlank() && serverUrl.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF7661D8))
            ) { Text("ثبت") }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("یادداشت‌ها", color = Color(0xFFF1EFF8), fontWeight = FontWeight.SemiBold)
            Button(onClick = { loadMemory() }, enabled = !busy, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF242D40))) {
                Text("بازیابی")
            }
        }
        LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            itemsIndexed(items, key = { index, item -> "${index}-${item.raw.optString("created_at")}" }) { index, item ->
                Surface(color = Color(0xFF151C2B), shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier.padding(13.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text(item.text, modifier = Modifier.weight(1f), color = Color(0xFFEDEBF4), fontSize = 13.sp, lineHeight = 20.sp)
                        Button(
                            onClick = {
                                persist(items.filterIndexed { i, _ -> i != index }, "یادداشت از حافظه‌ی مشترک حذف شد.")
                            },
                            enabled = !busy,
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4A2937))
                        ) { Text("حذف") }
                    }
                }
            }
            if (items.isEmpty()) item {
                Text("هنوز یادداشتی در حافظه‌ی مشترک نیست.", color = Color(0xFF8995AA), fontSize = 12.sp)
            }
        }
        if (busy) CircularProgressIndicator(color = Color(0xFFB9A5FF), modifier = Modifier.height(22.dp))
        Text(status, color = Color(0xFF9BA5B8), fontSize = 10.sp, lineHeight = 15.sp)
        Spacer(Modifier.height(2.dp))
    }
}
