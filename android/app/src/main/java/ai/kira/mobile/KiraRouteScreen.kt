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

@Composable
internal fun KiraRouteScreen() {
    val context=androidx.compose.ui.platform.LocalContext.current
    val core=remember { LocalKiraCore(context) }
    val executor=remember { Executors.newSingleThreadExecutor() }
    val handler=remember { Handler(Looper.getMainLooper()) }
    val routes=remember { mutableStateListOf<LocalProvider>() }
    var providerId by remember { mutableStateOf("openrouter") }
    var model by remember { mutableStateOf("openai/gpt-4o-mini") }
    var baseUrl by remember { mutableStateOf("https://openrouter.ai/api/v1") }
    var apiKey by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("کلیدها رمزنگاری‌شده و فقط روی همین گوشی ذخیره می‌شوند.") }

    DisposableEffect(executor) { onDispose { executor.shutdownNow() } }
    fun refresh() { routes.clear(); routes.addAll(core.providers()) }
    LaunchedEffect(Unit) { refresh() }

    fun save() {
        if(busy || providerId.isBlank() || model.isBlank() || baseUrl.isBlank()) return
        if(apiKey.isBlank() && routes.none { it.id==providerId && it.hasKey }) {
            status="برای Provider جدید باید API Key وارد کنی."
            return
        }
        val id=providerId.trim(); val modelId=model.trim(); val endpoint=baseUrl.trim(); val key=apiKey
        busy=true; status="در حال ذخیره امن تنظیمات محلی…"
        executor.execute {
            try {
                core.saveProvider(id,modelId,endpoint,key,true)
                val list=core.providers()
                handler.post { routes.clear(); routes.addAll(list); apiKey=""; status="Provider ذخیره شد. درخواست‌ها مستقیماً از گوشی به API می‌روند."; busy=false }
            } catch(e:Exception) {
                handler.post { status=e.message ?: "ذخیره Provider ناموفق بود."; busy=false }
            }
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
                handler.post { routes.clear(); routes.addAll(list); status="تنظیمات Route روی همین دستگاه ذخیره شد."; busy=false }
            } catch(e:Exception) { handler.post { status=e.message ?: "تغییر Route ناموفق بود."; busy=false } }
        }
    }

    Column(Modifier.fillMaxSize().background(Color(0xFF0B0E15)).padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
            Column {
                Text("LOCAL ROUTE MANAGER",color=Color(0xFFB9A5FF),fontSize=10.sp,fontWeight=FontWeight.Bold,letterSpacing=2.sp)
                Text("اتصال مستقیم API",color=Color(0xFFF4F2FA),fontSize=21.sp,fontWeight=FontWeight.Bold)
            }
            OutlinedButton(onClick={refresh()},enabled=!busy) { Text("بازیابی") }
        }
        Text("Providerهای آماده: OpenRouter، Groq، Mistral، DeepSeek و Gemini. برای هرکدام کلید و Model ID خودت را وارد کن.",color=Color(0xFF9BA5B8),fontSize=11.sp,lineHeight=17.sp)
        Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(value=providerId,onValueChange={providerId=it},label={Text("Provider ID مثل openrouter یا gemini")},singleLine=true,modifier=Modifier.fillMaxWidth())
                OutlinedTextField(value=model,onValueChange={model=it},label={Text("Model ID")},singleLine=true,modifier=Modifier.fillMaxWidth())
                OutlinedTextField(value=baseUrl,onValueChange={baseUrl=it},label={Text("Base URL")},singleLine=true,modifier=Modifier.fillMaxWidth())
                OutlinedTextField(value=apiKey,onValueChange={apiKey=it},label={Text("API Key")},visualTransformation=PasswordVisualTransformation(),singleLine=true,modifier=Modifier.fillMaxWidth())
                Button(onClick={save()},enabled=!busy && providerId.isNotBlank() && model.isNotBlank() && baseUrl.isNotBlank(),modifier=Modifier.fillMaxWidth(),colors=ButtonDefaults.buttonColors(containerColor=Color(0xFF7661D8))) { Text("ذخیره کلید و فعال‌سازی") }
            }
        }
        Text("ترتیب Route و Failover",color=Color(0xFFF1EFF8),fontWeight=FontWeight.SemiBold)
        LazyColumn(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(7.dp)) {
            itemsIndexed(routes,key={_,r->r.id}) { index,route ->
                Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(13.dp),modifier=Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(11.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
                        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                            Column(Modifier.weight(1f)) {
                                Text((index+1).toString()+". "+route.id,color=Color(0xFFF1EFF8),fontWeight=FontWeight.SemiBold)
                                Text(route.model,color=Color(0xFF9BA5B8),fontSize=10.sp)
                                Text(if(route.hasKey) "کلید ذخیره‌شده" else "بدون کلید API",color=if(route.hasKey) Color(0xFF8FD6B0) else Color(0xFFFFC27A),fontSize=10.sp)
                            }
                            Text(if(route.enabled) "فعال" else "خاموش",color=Color(0xFFB9A5FF),fontSize=10.sp)
                        }
                        Row(horizontalArrangement=Arrangement.spacedBy(5.dp)) {
                            OutlinedButton(onClick={change(route,enabled=!route.enabled)},enabled=!busy) { Text(if(route.enabled) "خاموش" else "روشن") }
                            OutlinedButton(onClick={change(route,delta=-1)},enabled=!busy && index>0) { Text("↑") }
                            OutlinedButton(onClick={change(route,delta=1)},enabled=!busy && index<routes.lastIndex) { Text("↓") }
                            TextButton(onClick={providerId=route.id;model=route.model;baseUrl=route.baseUrl;apiKey=""},enabled=!busy) { Text("ویرایش") }
                        }
                    }
                }
            }
        }
        if(busy) LinearProgressIndicator(Modifier.fillMaxWidth(),color=Color(0xFFB9A5FF))
        Text(status,color=Color(0xFF9BA5B8),fontSize=10.sp,lineHeight=15.sp)
    }
}
