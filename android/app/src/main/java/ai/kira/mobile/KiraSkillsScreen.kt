package ai.kira.mobile

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.kira.mobile.core.LocalKiraCore

@Composable
internal fun KiraSkillsScreen() {
    val context=LocalContext.current
    val core=remember { LocalKiraCore(context) }
    var character by remember { mutableStateOf("global") }
    var refresh by remember { mutableIntStateOf(0) }
    var name by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }
    var baseUrl by remember { mutableStateOf("https://api.example.com") }
    var endpoint by remember { mutableStateOf("/v1/search") }
    var parameters by remember { mutableStateOf("q") }
    var apiKey by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("سه Connector آماده در کتابخانه نصب شده‌اند.") }
    val skills=remember(character,refresh) { core.skillsFor(character) }

    Column(
        Modifier.fillMaxSize().background(Color(0xFF0B0E15)).verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement=Arrangement.spacedBy(12.dp)
    ) {
        Text("کتابخانه مهارت‌ها",color=Color(0xFFF4F2FA),fontSize=23.sp,fontWeight=FontWeight.Bold)
        Text("یک کتابخانه محلی و مشترک. مهارت را یک‌بار نصب کن و برای Kira، Ren، Mika یا هر سه فعالش کن.",color=Color(0xFF9BA5B8),fontSize=12.sp,lineHeight=18.sp)
        Text("دامنه فعال‌سازی",color=Color(0xFFB9A5FF),fontWeight=FontWeight.SemiBold)
        Row(horizontalArrangement=Arrangement.spacedBy(6.dp)) {
            listOf("global" to "همه","kira" to "Kira","ren" to "Ren","mika" to "Mika").forEach { (id,label) ->
                FilterChip(selected=character==id,onClick={character=id},label={Text(label)})
            }
        }
        Text("مهارت‌های نصب‌شده",color=Color(0xFFF4F2FA),fontWeight=FontWeight.SemiBold)
        if(skills.isEmpty()) Text("هنوز مهارتی نصب نشده است.",color=Color(0xFF9BA5B8),fontSize=12.sp)
        skills.forEach { skill ->
            Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(14.dp),modifier=Modifier.fillMaxWidth()) {
                Column(Modifier.padding(13.dp),verticalArrangement=Arrangement.spacedBy(7.dp)) {
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(3.dp)) {
                            Text(skill.name,color=Color(0xFFF4F2FA),fontWeight=FontWeight.Bold)
                            Text(skill.description,color=Color(0xFF9BA5B8),fontSize=11.sp,lineHeight=16.sp)
                            Text(if(skill.source=="builtin") "Connector آماده · فقط خواندنی" else "Connector سفارشی · HTTPS GET",color=Color(0xFF8F84D8),fontSize=10.sp)
                        }
                        Switch(checked=skill.enabled,onCheckedChange={
                            core.setSkillEnabled(skill.name,character,it)
                            refresh++
                        })
                    }
                    if(skill.source!="builtin") {
                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.End) {
                            TextButton(onClick={ core.removeSkill(skill.name);refresh++ }) { Text("حذف",color=Color(0xFFFF8A9A)) }
                        }
                    }
                }
            }
        }
        Divider(color=Color(0xFF273047))
        Text("ساخت Connector جدید",color=Color(0xFFF4F2FA),fontSize=18.sp,fontWeight=FontWeight.Bold)
        Text("فقط درخواست HTTPS GET. هیچ اسکریپت یا کد دانلودشده‌ای اجرا نمی‌شود. کلید اختیاری با Android Keystore رمزنگاری می‌شود.",color=Color(0xFF9BA5B8),fontSize=11.sp,lineHeight=17.sp)
        OutlinedTextField(value=name,onValueChange={name=it.lowercase().replace(Regex("[^a-z0-9-]"),"-").replace(Regex("-+"),"-").trim('-')},label={Text("شناسه مهارت (انگلیسی)")},singleLine=true,modifier=Modifier.fillMaxWidth())
        OutlinedTextField(value=description,onValueChange={description=it},label={Text("توضیح کوتاه")},modifier=Modifier.fillMaxWidth())
        OutlinedTextField(value=baseUrl,onValueChange={baseUrl=it},label={Text("Base URL")},singleLine=true,modifier=Modifier.fillMaxWidth())
        OutlinedTextField(value=endpoint,onValueChange={endpoint=it},label={Text("مسیر Endpoint")},singleLine=true,modifier=Modifier.fillMaxWidth())
        OutlinedTextField(value=parameters,onValueChange={parameters=it},label={Text("پارامترهای مجاز با کاما")},singleLine=true,modifier=Modifier.fillMaxWidth())
        OutlinedTextField(value=apiKey,onValueChange={apiKey=it},label={Text("API Key اختیاری (Bearer)")},singleLine=true,visualTransformation=PasswordVisualTransformation(),modifier=Modifier.fillMaxWidth())
        Button(
            onClick={
                try {
                    core.installApiSkill(name,description,description,baseUrl,endpoint,parameters.split(",").map { it.trim() },apiKey,character)
                    name="";description="";apiKey="";status="Connector نصب شد و برای دامنه انتخاب‌شده فعال است.";refresh++
                } catch(e:Exception) { status=e.message ?: "نصب Connector ناموفق بود." }
            },
            enabled=name.isNotBlank() && description.isNotBlank() && endpoint.startsWith("/"),
            modifier=Modifier.fillMaxWidth()
        ) { Text("نصب Connector") }
        Text(status,color=Color(0xFFB9A5FF),fontSize=11.sp,lineHeight=17.sp)
    }
}
