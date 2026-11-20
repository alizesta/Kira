package ai.kira.mobile

import android.content.ContentResolver
import android.content.Intent
import android.database.Cursor
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import ai.kira.mobile.core.KiraContainer
import ai.kira.mobile.domain.model.ChatAttachmentInput
import ai.kira.mobile.domain.model.ChatMessage
import ai.kira.mobile.ui.theme.KiraPalette
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

private data class PendingChatAttachment(val uri:Uri,val name:String)

@Composable
internal fun KiraChatScreen(container:KiraContainer,character:String,prefillText:String="",onPrefillConsumed:()->Unit={}) {
    val context=LocalContext.current
    val chat=remember(container) { container.chat }
    val executor=remember { Executors.newSingleThreadExecutor() }
    val handler=remember { Handler(Looper.getMainLooper()) }
    val messages=remember { mutableStateListOf<ChatMessage>() }
    val pending=remember { mutableStateListOf<PendingChatAttachment>() }
    val listState=rememberLazyListState()
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("هسته محلی آماده است. می‌توانی تصویر یا فایل متنی پیوست کنی.") }

    val picker=rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        var exceeded=false
        uris.forEach { uri ->
            if(pending.size>=5) exceeded=true
            else if(pending.none { it.uri==uri }) {
                runCatching { context.contentResolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION) }
                pending+=PendingChatAttachment(uri,attachmentName(context.contentResolver,uri))
            }
        }
        if(exceeded) status="حداکثر ۵ فایل را می‌توان پیوست کرد."
        else if(uris.isNotEmpty()) status="فایل‌ها انتخاب شدند؛ برای ارسال، دکمه ارسال را بزن."
    }

    LaunchedEffect(prefillText) {
        if(prefillText.isNotBlank()) { input=prefillText; onPrefillConsumed() }
    }
    DisposableEffect(executor) { onDispose { executor.shutdownNow() } }

    fun load() {
        messages.clear()
        messages.addAll(chat.history(character))
        status="تاریخچه و مشخصات پیوست‌ها از حافظه همین دستگاه بارگذاری شدند."
    }
    LaunchedEffect(character) { load() }
    LaunchedEffect(messages.size) { if(messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex) }

    fun send() {
        val text=input.trim()
        val selected=pending.toList()
        if((text.isBlank() && selected.isEmpty()) || busy) return
        val who=character
        busy=true
        status="در حال آماده‌سازی فایل‌ها و دریافت پاسخ…"
        executor.execute {
            try {
                val files=selected.map { readAttachment(context.contentResolver,it) }
                val reply=chat.sendMessage(who,text,files)
                val history=chat.history(who)
                handler.post {
                    messages.clear(); messages.addAll(history)
                    input=""
                    pending.removeAll(selected.toSet())
                    status="پاسخ از "+reply.provider+" · "+reply.model
                    busy=false
                }
            } catch(error:Exception) {
                val history=runCatching { chat.history(who) }.getOrDefault(emptyList())
                handler.post {
                    messages.clear(); messages.addAll(history)
                    status=error.message ?: "ارسال پیام یا فایل ناموفق بود."
                    busy=false
                }
            }
        }
    }

    Column(Modifier.fillMaxSize().background(KiraPalette.background).padding(14.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
            Column {
                Text("KIRA LOCAL CORE",color=KiraPalette.primary,fontSize=10.sp,fontWeight=FontWeight.Bold,letterSpacing=2.sp)
                Text("گفت‌وگو با "+character.replaceFirstChar { it.uppercase() },color=KiraPalette.onBackground,fontSize=21.sp,fontWeight=FontWeight.Bold)
            }
            OutlinedButton(onClick={load()},enabled=!busy) { Text("بازیابی") }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth(),state=listState,verticalArrangement=Arrangement.spacedBy(9.dp)) {
            if(messages.isEmpty()) item {
                Text("چت روی همین گوشی ذخیره می‌شود. فایل‌ها فقط هنگام ارسال به Provider فعال فرستاده می‌شوند.",color=Color(0xFF8995AA),fontSize=13.sp,lineHeight=20.sp,modifier=Modifier.padding(vertical=20.dp))
            }
            items(messages,key={it.id}) { message ->
                val user=message.role=="user"
                Row(Modifier.fillMaxWidth(),horizontalArrangement=if(user) Arrangement.End else Arrangement.Start) {
                    Surface(color=if(user) Color(0xFF493D79) else KiraPalette.surface,shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth(0.88f)) {
                        Column(Modifier.padding(13.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                            Text(if(user) "تو" else character.uppercase(),color=if(user) Color(0xFFE5DCFF) else KiraPalette.primary,fontSize=10.sp,fontWeight=FontWeight.Bold)
                            Text(message.content,color=Color(0xFFF0EFF6),fontSize=14.sp,lineHeight=21.sp)
                            if(message.attachments.isNotEmpty()) {
                                Text(message.attachments.joinToString(" · ") { "📎 "+it.name+" ("+attachmentSize(it.sizeBytes)+")" },color=Color(0xFFB9A5FF),fontSize=10.sp,lineHeight=15.sp)
                            }
                            if(!user && message.route.isNotBlank()) Text(message.route,color=Color(0xFF8290A7),fontSize=9.sp)
                        }
                    }
                }
            }
            if(busy) item {
                Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                    CircularProgressIndicator(Modifier.size(18.dp),color=KiraPalette.primary,strokeWidth=2.dp)
                    Text("Kira در حال فکرکردن است…",color=KiraPalette.muted,fontSize=11.sp)
                }
            }
        }
        if(pending.isNotEmpty()) {
            Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(4.dp)) {
                pending.forEach { file ->
                    Row(Modifier.fillMaxWidth().background(Color(0xFF171F30),RoundedCornerShape(10.dp)).padding(horizontal=10.dp,vertical=3.dp),
                        verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                        Text(file.name,maxLines=1,color=Color(0xFFE3DDF5),fontSize=11.sp,modifier=Modifier.weight(1f))
                        TextButton(onClick={pending.remove(file)},enabled=!busy) { Text("حذف",color=Color(0xFFFFA6AE),fontSize=11.sp) }
                    }
                }
            }
        }
        Text(status,color=KiraPalette.muted,fontSize=10.sp,lineHeight=15.sp)
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.Bottom,horizontalArrangement=Arrangement.spacedBy(6.dp)) {
            OutlinedButton(onClick={picker.launch(arrayOf("*/*"))},enabled=!busy && pending.size<5,modifier=Modifier.height(54.dp)) { Text("پیوست",fontSize=11.sp) }
            OutlinedTextField(value=input,onValueChange={input=it},modifier=Modifier.weight(1f),placeholder={Text("پیامت را بنویس…",color=Color(0xFFD7D1E8))},maxLines=4,
                keyboardOptions=KeyboardOptions(imeAction=ImeAction.Send),keyboardActions=KeyboardActions(onSend={send()}),shape=RoundedCornerShape(18.dp),
                colors=OutlinedTextFieldDefaults.colors(focusedTextColor=Color.White,unfocusedTextColor=Color.White,disabledTextColor=Color.White,cursorColor=Color.White,focusedPlaceholderColor=Color(0xFFD7D1E8),unfocusedPlaceholderColor=Color(0xFFD7D1E8)))
            Button(onClick={send()},enabled=!busy && (input.isNotBlank() || pending.isNotEmpty()),modifier=Modifier.height(54.dp),colors=ButtonDefaults.buttonColors(containerColor=KiraPalette.primaryContainer)) { Text("ارسال") }
        }
    }
}

private fun attachmentName(resolver:ContentResolver,uri:Uri):String {
    var name:String?=null
    resolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use { cursor ->
        if(cursor.moveToFirst()) {
            val index=cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if(index>=0) name=cursor.getString(index)
        }
    }
    return name?.substringAfterLast('/')?.substringAfterLast('\\')?.take(160)?.ifBlank { null }
        ?: uri.lastPathSegment?.substringAfterLast('/')?.take(160)?.ifBlank { null }
        ?: "attachment"
}
private fun readAttachment(resolver:ContentResolver,file:PendingChatAttachment):ChatAttachmentInput {
    val declared=resolver.getType(file.uri)?.substringBefore(';')?.trim()?.lowercase().orEmpty()
    val mime=if(declared.isBlank() || declared=="application/octet-stream") guessMime(file.name) else declared
    val limit=if(mime.startsWith("image/")) 8*1024*1024 else 512*1024
    val bytes=resolver.openInputStream(file.uri)?.use { stream ->
        val output=ByteArrayOutputStream(); val buffer=ByteArray(8192); var total=0
        while(true) {
            val count=stream.read(buffer); if(count<0) break
            total+=count; require(total<=limit) { "حجم فایل «"+file.name+"» از حد مجاز بیشتر است." }
            output.write(buffer,0,count)
        }
        output.toByteArray()
    } ?: throw IllegalStateException("خواندن فایل «"+file.name+"» ناموفق بود.")
    return ChatAttachmentInput(file.name,mime,bytes)
}
private fun guessMime(name:String):String=when(name.substringAfterLast('.', "").lowercase()) {
    "png"->"image/png"; "jpg","jpeg"->"image/jpeg"; "webp"->"image/webp"
    "txt","log"->"text/plain"; "md","markdown"->"text/markdown"; "csv"->"text/csv"
    "tsv"->"text/tab-separated-values"; "json"->"application/json"; "xml"->"application/xml"
    "yaml","yml"->"application/yaml"; "sql"->"application/sql"; "py"->"text/x-python"
    "kt"->"text/x-kotlin"; "java"->"text/x-java"; else->"application/octet-stream"
}
private fun attachmentSize(value:Long):String=when {
    value>=1024L*1024L->String.format(java.util.Locale.ROOT,"%.1f MB",value.toDouble()/(1024*1024))
    value>=1024L->String.format(java.util.Locale.ROOT,"%.0f KB",value.toDouble()/1024)
    else->"$value B"
}
