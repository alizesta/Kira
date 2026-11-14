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
    var status by remember { mutableStateOf("فقط API Key را وارد کن؛ مدل رایگان به‌صورت خودکار انتخاب می‌شود.") }

    DisposableEffect(executor) { onDispose { executor.shutdownNow() } }

    fun refreshRoutes() {
        routes.clear()
        routes.addAll(core.providers())
    }

    LaunchedEffect(Unit) {
        refreshRoutes()
        val saved=core.providers().firstOrNull { it.enabled && it.hasKey }
            ?: core.providers().firstOrNull { it.hasKey }
        if(saved!=null) {
            providerId=saved.id
            val cached=core.discoveredModels(saved.id)
            models.clear()
            models.addAll(cached)
            val chosen=if(saved.model in cached) saved.model else if(cached.isNotEmpty()) core.recommendedFreeModel(saved.id,cached) else ""
            selectedModel=chosen
            if(chosen.isNotBlank() && chosen!=saved.model) {
                executor.execute {
                    runCatching { core.saveProvider(saved.id,chosen,saved.baseUrl,"",saved.enabled) }
                    handler.post { refreshRoutes() }
                }
            }
        }
    }

    fun connect() {
        if(busy) return
        if(apiKey.isBlank()) {
            status="API Key را وارد کن."
            return
        }
        val key=apiKey.trim()
        busy=true
        status="در حال تشخیص Provider و دریافت فقط مدل‌های رایگان…"
        executor.execute {
            try {
                val (id,found)=core.detectProviderAndDiscoverModels(key)
                val preset=providerPresets.firstOrNull { it.id==id }
                    ?: throw IllegalStateException("Provider پشتیبانی نمی‌شود.")
                val preferred=core.recommendedFreeModel(id,found)
                core.saveProvider(id,preferred,preset.endpoint,key,true)
                val list=core.providers()
                handler.post {
                    providerId=id
                    models.clear()
                    models.addAll(found)
                    selectedModel=preferred
                    routes.clear()
                    routes.addAll(list)
                    apiKey=""
                    status="اتصال برقرار شد · " + found.size + " مدل رایگان · انتخاب خودکار: " + preferred
                    busy=false
                }
            } catch(e:Exception) {
                handler.post {
                    status=e.message ?: "اتصال ناموفق بود."
                    busy=false
                }
            }
        }
    }

    fun selectModel(model:String) {
        if(busy || model !in models) return
        selectedModel=model
        val route=routes.firstOrNull { it.id==providerId } ?: return
        busy=true
        executor.execute {
            try {
                core.saveProvider(route.id,model,route.baseUrl,"",route.enabled)
                val list=core.providers()
                handler.post {
                    routes.clear()
                    routes.addAll(list)
                    status="مدل رایگان انتخاب‌شده: " + model
                    busy=false
                }
            } catch(e:Exception) {
                handler.post {
                    status=e.message ?: "ذخیره مدل ناموفق بود."
                    busy=false
                }
            }
        }
    }

    fun selectRecommended() {
        if(models.isEmpty() || busy) return
        selectModel(core.recommendedFreeModel(providerId,models))
    }

    fun change(route:LocalProvider,enabled:Boolean?=null,delta:Int=0) {
        if(busy) return
        busy=true
        executor.execute {
            try {
                if(enabled!=null) core.setProviderEnabled(route.id,enabled)
                if(delta!=0) core.moveProvider(route.id,delta)
                val list=core.providers()
                handler.post {
                    routes.clear()
                    routes.addAll(list)
                    status="تنظیمات اتصال ذخیره شد."
                    busy=false
                }
            } catch(e:Exception) {
                handler.post {
                    status=e.message ?: "تغییر اتصال ناموفق بود."
                    busy=false
                }
            }
        }
    }

    Column(
        Modifier.fillMaxSize().background(Color(0xFF0B0E15)).padding(horizontal=14.dp,vertical=12.dp),
        verticalArrangement=Arrangement.spacedBy(10.dp)
    ) {
        Column(verticalArrangement=Arrangement.spacedBy(3.dp)) {
            Text("اتصال API و مدل‌ها",color=Color(0xFFF4F2FA),fontSize=22.sp,fontWeight=FontWeight.Bold)
            Text("فقط مدل‌های رایگان دریافت و برای چت انتخاب می‌شوند.",color=Color(0xFF9BA5B8),fontSize=12.sp)
        }

        Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                    Text("اتصال Provider",color=Color(0xFFF1EFF8),fontSize=15.sp,fontWeight=FontWeight.SemiBold)
                    Text("تشخیص خودکار",color=Color(0xFFB9A5FF),fontSize=11.sp)
                }
                OutlinedTextField(
                    value=apiKey,onValueChange={apiKey=it},
                    label={Text("API Key",color=Color.White)},
                    placeholder={Text("کلید سرویس را وارد کن",color=Color(0xFF7F8A9E))},
                    visualTransformation=PasswordVisualTransformation(),
                    singleLine=true,modifier=Modifier.fillMaxWidth(),
                    colors=OutlinedTextFieldDefaults.colors(
                        focusedTextColor=Color.White,unfocusedTextColor=Color.White,
                        disabledTextColor=Color.White,cursorColor=Color.White,
                        focusedLabelColor=Color.White,unfocusedLabelColor=Color.White
                    )
                )
                Button(
                    onClick={connect()},enabled=!busy && apiKey.isNotBlank(),
                    modifier=Modifier.fillMaxWidth().height(48.dp),
                    colors=ButtonDefaults.buttonColors(containerColor=Color(0xFF7661D8))
                ) {
                    Text(if(busy) "در حال دریافت مدل‌های رایگان…" else "اتصال و انتخاب خودکار مدل رایگان",fontSize=13.sp,fontWeight=FontWeight.SemiBold)
                }
            }
        }

        Surface(color=Color(0xFF211D3A),shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                    Text("مدل فعال چت",color=Color(0xFFF4F2FA),fontSize=16.sp,fontWeight=FontWeight.Bold)
                    Surface(color=Color(0xFF28523F),shape=RoundedCornerShape(50)) {
                        Text("FREE",modifier=Modifier.padding(horizontal=11.dp,vertical=5.dp),color=Color(0xFF9BE6B9),fontSize=11.sp,fontWeight=FontWeight.Bold)
                    }
                }
                Text(selectedModel.ifBlank { "بعد از اتصال، بهترین مدل رایگان به‌صورت خودکار انتخاب می‌شود." },color=Color.White,fontSize=17.sp,fontWeight=FontWeight.SemiBold,lineHeight=23.sp)
                if(models.isNotEmpty()) {
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        Box(Modifier.weight(1f)) {
                            OutlinedButton(onClick={modelMenu=true},enabled=!busy,modifier=Modifier.fillMaxWidth()) {
                                Text("مدل‌های رایگان (" + models.size + ")",fontSize=12.sp)
                            }
                            DropdownMenu(expanded=modelMenu,onDismissRequest={modelMenu=false},modifier=Modifier.heightIn(max=320.dp)) {
                                models.forEach { modelId ->
                                    DropdownMenuItem(text={Text(modelId,fontSize=12.sp)},onClick={modelMenu=false;selectModel(modelId)})
                                }
                            }
                        }
                        OutlinedButton(onClick={selectRecommended()},enabled=!busy,modifier=Modifier.height(48.dp)) {
                            Text("خودکار",fontSize=12.sp)
                        }
                    }
                } else {
                    Text("مدل پولی در این فهرست نمایش داده نمی‌شود.",color=Color(0xFFB7B0D6),fontSize=11.sp)
                }
            }
        }

        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
            Text("اتصال‌ها و جایگزینی خودکار",color=Color(0xFFF1EFF8),fontSize=14.sp,fontWeight=FontWeight.SemiBold)
            Text("اولویت از بالا به پایین",color=Color(0xFF8995AA),fontSize=10.sp)
        }

        LazyColumn(Modifier.weight(1f).fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            itemsIndexed(routes,key={_,r->r.id}) { index,route ->
                Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(14.dp),modifier=Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(3.dp)) {
                                Text(providerPresets.firstOrNull { it.id==route.id }?.label ?: route.id,color=Color(0xFFF1EFF8),fontSize=14.sp,fontWeight=FontWeight.SemiBold)
                                Text(route.model,color=Color(0xFFCFCAE8),fontSize=12.sp)
                                Text(if(route.hasKey) "کلید ذخیره شده" else "بدون کلید",color=if(route.hasKey) Color(0xFF8FD6B0) else Color(0xFF8995AA),fontSize=10.sp)
                            }
                            Column(horizontalAlignment=Alignment.End,verticalArrangement=Arrangement.spacedBy(3.dp)) {
                                Text("#" + (index+1),color=Color(0xFFB9A5FF),fontSize=12.sp,fontWeight=FontWeight.Bold)
                                Switch(checked=route.enabled,onCheckedChange={change(route,enabled=it)},enabled=!busy)
                            }
                        }
                        Row(horizontalArrangement=Arrangement.spacedBy(7.dp)) {
                            OutlinedButton(onClick={change(route,delta=-1)},enabled=!busy && index>0) { Text("↑ بالاتر") }
                            OutlinedButton(onClick={change(route,delta=1)},enabled=!busy && index<routes.lastIndex) { Text("↓ پایین‌تر") }
                        }
                    }
                }
            }
            if(routes.isEmpty()) {
                item { Text("هنوز اتصال فعالی ثبت نشده است.",color=Color(0xFF8995AA),fontSize=12.sp,modifier=Modifier.padding(vertical=14.dp)) }
            }
        }

        if(busy) LinearProgressIndicator(Modifier.fillMaxWidth(),color=Color(0xFFB9A5FF))
        Text(status,color=Color(0xFF9BA5B8),fontSize=11.sp,lineHeight=16.sp,maxLines=2)
    }
}
