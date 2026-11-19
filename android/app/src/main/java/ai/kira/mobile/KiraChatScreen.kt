package ai.kira.mobile

import android.os.Handler
import android.os.Looper
import ai.kira.mobile.core.KiraContainer
import ai.kira.mobile.domain.model.ChatMessage
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.util.concurrent.Executors

@Composable
internal fun KiraChatScreen(character:String,onCharacterChange:(String)->Unit) {
    val context=androidx.compose.ui.platform.LocalContext.current
    val chat=remember { KiraContainer(context).chat }
    val executor=remember { Executors.newSingleThreadExecutor() }
    val handler=remember { Handler(Looper.getMainLooper()) }
    val messages=remember { mutableStateListOf<ChatMessage>() }
    val listState=rememberLazyListState()
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("هسته محلی آماده است. کلید API را در Route وارد کن.") }

    DisposableEffect(executor) { onDispose { executor.shutdownNow() } }
    fun load() {
        messages.clear()
        messages.addAll(chat.history(character))
        status="تاریخچه از حافظه همین دستگاه بارگذاری شد."
    }
    LaunchedEffect(character) { load() }
    LaunchedEffect(messages.size) { if(messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex) }

    fun send() {
        val text=input.trim()
        if(text.isBlank() || busy) return
        val who=character
        input=""
        busy=true
        status="در حال دریافت پاسخ…"
        executor.execute {
            try {
                val reply=chat.sendMessage(who,text)
                val history=chat.history(who)
                handler.post {
                    messages.clear(); messages.addAll(history)
                    status="پاسخ از "+reply.provider+" · "+reply.model
                    busy=false
                }
            } catch(e:Exception) {
                val history=core.history(who)
                handler.post {
                    messages.clear(); messages.addAll(history)
                    status=e.message ?: "ارسال پیام ناموفق بود."
                    busy=false
                }
            }
        }
    }

    Column(Modifier.fillMaxSize().background(Color(0xFF0B0E15)).padding(14.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
            Column {
                Text("KIRA LOCAL CORE",color=Color(0xFFB9A5FF),fontSize=10.sp,fontWeight=FontWeight.Bold,letterSpacing=2.sp)
                Text("گفت‌وگو با "+character.replaceFirstChar { it.uppercase() },color=Color(0xFFF4F2FA),fontSize=21.sp,fontWeight=FontWeight.Bold)
            }
            OutlinedButton(onClick={load()},enabled=!busy) { Text("بازیابی") }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth(),state=listState,verticalArrangement=Arrangement.spacedBy(9.dp)) {
            if(messages.isEmpty()) item {
                Text("این چت فقط روی همین گوشی ذخیره می‌شود. API Key را از تنظیمات اضافه کن تا Kira پاسخ بدهد.",color=Color(0xFF8995AA),fontSize=13.sp,lineHeight=20.sp,modifier=Modifier.padding(vertical=20.dp))
            }
            items(messages,key={it.id}) { message ->
                val user=message.role=="user"
                Row(Modifier.fillMaxWidth(),horizontalArrangement=if(user) Arrangement.End else Arrangement.Start) {
                    Surface(color=if(user) Color(0xFF493D79) else Color(0xFF151C2B),shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth(0.88f)) {
                        Column(Modifier.padding(13.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                            Text(if(user) "تو" else character.uppercase(),color=if(user) Color(0xFFE5DCFF) else Color(0xFFB9A5FF),fontSize=10.sp,fontWeight=FontWeight.Bold)
                            Text(message.content,color=Color(0xFFF0EFF6),fontSize=14.sp,lineHeight=21.sp)
                            if(!user && message.route.isNotBlank()) Text(message.route,color=Color(0xFF8290A7),fontSize=9.sp)
                        }
                    }
                }
            }
            if(busy) item { Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(Modifier.size(18.dp),color=Color(0xFFB9A5FF),strokeWidth=2.dp)
                Text("Kira در حال فکرکردن است…",color=Color(0xFF9BA5B8),fontSize=11.sp)
            } }
        }
        Text(status,color=Color(0xFF9BA5B8),fontSize=10.sp,lineHeight=15.sp)
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.Bottom,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(value=input,onValueChange={input=it},modifier=Modifier.weight(1f),placeholder={Text("پیامت را بنویس…",color=Color(0xFFD7D1E8))},maxLines=4,
                keyboardOptions=KeyboardOptions(imeAction=ImeAction.Send),keyboardActions=KeyboardActions(onSend={send()}),shape=RoundedCornerShape(18.dp),
                colors=OutlinedTextFieldDefaults.colors(focusedTextColor=Color.White,unfocusedTextColor=Color.White,disabledTextColor=Color.White,cursorColor=Color.White,focusedPlaceholderColor=Color(0xFFD7D1E8),unfocusedPlaceholderColor=Color(0xFFD7D1E8)))
            Button(onClick={send()},enabled=!busy && input.isNotBlank(),modifier=Modifier.height(54.dp),colors=ButtonDefaults.buttonColors(containerColor=Color(0xFF7661D8))) { Text("ارسال") }
        }
    }
}
