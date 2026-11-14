package ai.kira.mobile

import android.os.Handler
import android.os.Looper
import ai.kira.mobile.core.LocalKiraCore
import ai.kira.mobile.core.LocalProvider
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.util.concurrent.Executors

private data class ProviderPreset(val id:String,val label:String,val endpoint:String)
private val providerPresets=listOf(
    ProviderPreset("gemini","Google Gemini","https://generativelanguage.googleapis.com/v1beta"),
    ProviderPreset("openrouter","OpenRouter","https://openrouter.ai/api/v1"),
    ProviderPreset("groq","Groq","https://api.groq.com/openai/v1"),
    ProviderPreset("mistral","Mistral","https://api.mistral.ai/v1"),
    ProviderPreset("deepseek","DeepSeek","https://api.deepseek.com")
)

@Composable
internal fun KiraRouteScreen() {
    val context=androidx.compose.ui.platform.LocalContext.current
    val core=remember { LocalKiraCore(context) }
    val executor=remember { Executors.newSingleThreadExecutor() }
    val handler=remember { Handler(Looper.getMainLooper()) }
    val routes=remember { mutableStateListOf<LocalProvider>() }
    val models=remember { mutableStateListOf<String>() }
    var providerId by remember { mutableStateOf("gemini") }
    var apiKey by remember { mutableStateOf("") }
    var selectedModel by remember { mutableStateOf("") }
    var modelMenu by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("فقط API Key را وارد کن؛ Kira مدل‌ها را خودش دریافت می‌کند.") }

    DisposableEffect(executor) { onDispose { executor.shutdownNow() } }
    fun refresh() { routes.clear(); routes.addAll(core.providers()) }
    LaunchedEffect(Unit) { refresh() }
    LaunchedEffect(Unit) {
        val saved=core.providers().firstOrNull { it.enabled && it.hasKey }
        if(saved!=null) providerId=saved.id
        models.clear(); models.addAll(core.discoveredModels(providerId)); selectedModel=models.firstOrNull().orEmpty()
    }

    fun connect() {
        if(busy || apiKey.isBlank()) { status="API Key را وارد کن."; return }
        val key=apiKey.trim()
        busy=true
        status="در حال اتصال و دریافت خودکار فهرست مدل‌ها…"
        executor.execute {
            try {
                val (id,found)=core.detectProviderAndDiscoverModels(key)
                val endpoint=providerPresets.first { it.id==id }.endpoint
                val preferred=when(id) {
                    "gemini" -> found.firstOrNull { it.contains("flash",true) } ?: found.first()
                    "deepseek" -> found.firstOrNull { it.contains("chat",true) } ?: found.first()
                    else -> found.first()
                }
                core.saveProvider(id,preferred,endpoint,key,true)
                val list=core.providers()
                handler.post {
                    providerId=id
                    models.clear(); models.addAll(found)
                    selectedModel=preferred
                    routes.clear(); routes.addAll(list)
                    apiKey=""
                    status="اتصال موفق؛ ${found.size} مدل دریافت شد. مدل پیش‌فرض: $preferred"
                    busy=false
                }
            } catch(e:Exception) {
                handler.post { status=e.message ?: "اتصال ناموفق بود."; busy=false }
            }
        }
    }

    fun selectModel(model:String) {
        selectedModel=model
        val route=routes.firstOrNull { it.id==providerId } ?: return
        busy=true
        executor.execute {
            try {
                core.saveProvider(route.id,model,route.baseUrl,"",true)
                val list=core.providers()
                handler.post { routes.clear();routes.addAll(list);status="مدل پیش‌فرض به‌روزرسانی شد: $model";busy=false }
            } catch(e:Exception) { handler.post { status=e.message ?: "ذخیره مدل ناموفق بود.";busy=false } }
        }
    }
    fun change(route:LocalProvider,enabled:Boolean?=null,delta:Int=0) {
        if(busy) return
        busy=true
        executor.execute {
            try {
                if(enabled!=null) core.setProviderEnabled(route.id,enabled)
                if(delta!=0) core.moveProvider(route.id,delta)
                val list=core.providers()
                handler.post { routes.clear();routes.addAll(list);status="تنظیمات Route ذخیره شد.";busy=false }
            } catch(e:Exception) { handler.post { status=e.message ?: "تغییر Route ناموفق بود.";busy=false } }
        }
    }

    Column(Modifier.fillMaxSize().background(Color(0xFF0B0E15)).padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
        Text("اتصال هوشمند مدل‌ها",color=Color(0xFFF4F2FA),fontSize=22.sp,fontWeight=FontWeight.Bold)
        Text("فقط API Key را وارد کن. Kira نوع Provider را تشخیص می‌دهد، مدل‌ها را می‌گیرد و تنظیمات اتصال را خودش انجام می‌دهد.",color=Color(0xFF9BA5B8),fontSize=12.sp,lineHeight=18.sp)
        Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(9.dp)) {
                Text("Provider به‌صورت خودکار از روی API Key تشخیص داده می‌شود.",color=Color(0xFFB9A5FF),fontSize=11.sp)
                OutlinedTextField(value=apiKey,onValueChange={apiKey=it},label={Text("API Key",color=Color.White)},visualTransformation=PasswordVisualTransformation(),singleLine=true,modifier=Modifier.fillMaxWidth(),colors=OutlinedTextFieldDefaults.colors(focusedTextColor=Color.White,unfocusedTextColor=Color.White,disabledTextColor=Color.White,cursorColor=Color.White,focusedLabelColor=Color.White,unfocusedLabelColor=Color.White))
                Button(onClick={connect()},enabled=!busy && apiKey.isNotBlank(),modifier=Modifier.fillMaxWidth(),colors=ButtonDefaults.buttonColors(containerColor=Color(0xFF7661D8))) {
                    Text(if(busy) "در حال اتصال…" else "تشخیص Provider و دریافت مدل‌ها")
                }
                if(models.isNotEmpty()) {
                    Text("مدل پیش‌فرض چت",color=Color(0xFFF1EFF8),fontWeight=FontWeight.SemiBold,fontSize=12.sp)
                    Box {
                        OutlinedButton(onClick={modelMenu=true},modifier=Modifier.fillMaxWidth(),enabled=!busy) { Text(selectedModel.ifBlank { "انتخاب مدل" }) }
                        DropdownMenu(expanded=modelMenu,onDismissRequest={modelMenu=false},modifier=Modifier.heightIn(max=360.dp)) {
                            models.forEach { modelId -> DropdownMenuItem(text={Text(modelId)},onClick={modelMenu=false;selectModel(modelId)}) }
                        }
                    }
                    Text("${models.size} مدل از Provider دریافت شده است.",color=Color(0xFF8FD6B0),fontSize=10.sp)
                }
            }
        }
        Text("مدیریت اتصال‌ها و جایگزینی خودکار",color=Color(0xFFF1EFF8),fontWeight=FontWeight.SemiBold)
        LazyColumn(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(7.dp)) {
            itemsIndexed(routes,key={_,r->r.id}) { index,route ->
                Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(13.dp),modifier=Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(11.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
                        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                            Column(Modifier.weight(1f)) {
                                Text("${index+1}. ${providerPresets.firstOrNull { it.id==route.id }?.label ?: route.id}",color=Color(0xFFF1EFF8),fontWeight=FontWeight.SemiBold)
                                Text(route.model,color=Color(0xFF9BA5B8),fontSize=10.sp)
                                Text(if(route.hasKey) "کلید ذخیره شده" else "نیازمند API Key",color=if(route.hasKey) Color(0xFF8FD6B0) else Color(0xFFFFC27A),fontSize=10.sp)
                            }
                            Text(if(route.enabled) "فعال" else "خاموش",color=Color(0xFFB9A5FF),fontSize=10.sp)
                        }
                        Row(horizontalArrangement=Arrangement.spacedBy(5.dp)) {
                            OutlinedButton(onClick={change(route,enabled=!route.enabled)},enabled=!busy) { Text(if(route.enabled) "خاموش" else "روشن") }
                            OutlinedButton(onClick={change(route,delta=-1)},enabled=!busy && index>0) { Text("↑") }
                            OutlinedButton(onClick={change(route,delta=1)},enabled=!busy && index<routes.lastIndex) { Text("↓") }
                        }
                    }
                }
            }
        }
        if(busy) LinearProgressIndicator(Modifier.fillMaxWidth(),color=Color(0xFFB9A5FF))
        Text(status,color=Color(0xFF9BA5B8),fontSize=10.sp,lineHeight=15.sp)
    }
}
