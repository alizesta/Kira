package ai.kira.mobile

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.kira.mobile.assistant.AiAssistantOverlayService
import ai.kira.mobile.application.assistant.OverlayDestination
import ai.kira.mobile.application.assistant.OverlayRouteParser
import ai.kira.mobile.ui.theme.KiraTheme
import ai.kira.mobile.ui.theme.KiraPalette

private data class OverlayLaunchRequest(val route: String, val text: String, val sequence: Long)

class MainActivity : ComponentActivity() {
    private var overlayRequest by mutableStateOf<OverlayLaunchRequest?>(null)
    private var overlaySequence = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        submitOverlayIntent(intent)
        setContent { KiraApp(overlayRequest) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        submitOverlayIntent(intent)
    }

    private fun submitOverlayIntent(intent: Intent?) {
        val route = intent?.getStringExtra(EXTRA_OPEN_ROUTE) ?: return
        overlaySequence += 1
        overlayRequest = OverlayLaunchRequest(
            route = route,
            text = intent.getStringExtra(EXTRA_CHAT_TEXT).orEmpty(),
            sequence = overlaySequence
        )
    }

    companion object {
        const val EXTRA_OPEN_ROUTE = "ai.kira.mobile.extra.OPEN_ROUTE"
        const val EXTRA_CHAT_TEXT = "ai.kira.mobile.extra.CHAT_TEXT"
    }
}

private enum class KiraTab(val label:String,val glyph:String) {
    CHAT("چت","✦"), SEARCH("جستجو","⌕"), IMAGE("تصویر","▧"), CHARACTERS("شخصیت‌ها","♧"), SETTINGS("تنظیمات","⚙")
}

private enum class SettingsPage { HOME, ROUTE, MEMORY, SKILLS, ASSISTANT, VOICE }

@Composable
private fun KiraApp(routeRequest: OverlayLaunchRequest? = null) {
    val context=LocalContext.current
    var selectedTab by rememberSaveable { mutableStateOf(KiraTab.CHAT) }
    var selectedCharacter by rememberSaveable { mutableStateOf("kira") }
    var pendingChatContext by rememberSaveable { mutableStateOf("") }
    var settingsPage by rememberSaveable { mutableStateOf(SettingsPage.HOME) }
    var hasOverlayPermission by remember { mutableStateOf(Settings.canDrawOverlays(context)) }
    var overlayStarted by remember { mutableStateOf(false) }

    LaunchedEffect(routeRequest?.sequence) {
        routeRequest?.let { request ->
            when (OverlayRouteParser.parse(request.route)) {
                OverlayDestination.CHAT -> selectedTab = KiraTab.CHAT
                OverlayDestination.SEARCH -> selectedTab = KiraTab.SEARCH
                OverlayDestination.IMAGE -> selectedTab = KiraTab.IMAGE
                OverlayDestination.VOICE -> {
                    selectedTab = KiraTab.SETTINGS
                    settingsPage = SettingsPage.VOICE
                }
            }
            if (request.text.isNotBlank()) {
                pendingChatContext = request.text
                selectedTab = KiraTab.CHAT
            }
        }
    }

    BackHandler(enabled=selectedTab==KiraTab.SETTINGS && settingsPage!=SettingsPage.HOME) {
        settingsPage=SettingsPage.HOME
    }
    val overlaySettingsLauncher=rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        hasOverlayPermission=Settings.canDrawOverlays(context)
    }

    KiraTheme {
        Scaffold(
            containerColor=KiraPalette.background,
            bottomBar={
                if(selectedTab!=KiraTab.SETTINGS || settingsPage==SettingsPage.HOME) {
                    NavigationBar(containerColor=KiraPalette.surface) {
                    KiraTab.entries.forEach { tab ->
                        NavigationBarItem(selected=selectedTab==tab,onClick={selectedTab=tab},
                            icon={Text(tab.glyph,fontSize=18.sp,color=if(selectedTab==tab) KiraPalette.primary else KiraPalette.muted)},label={Text(tab.label,fontSize=11.sp)})
                    }
                    }
                }
            }
        ) { padding ->
            Surface(Modifier.fillMaxSize().padding(padding),color=Color(0xFF0B0E15)) {
                when(selectedTab) {
                    KiraTab.CHAT -> KiraChatScreen(character=selectedCharacter,prefillText=pendingChatContext,onPrefillConsumed={pendingChatContext=""})
                    KiraTab.SEARCH -> KiraSearchScreen(onUseInChat={ text -> pendingChatContext=text; selectedTab=KiraTab.CHAT })
                    KiraTab.IMAGE -> KiraImageScreen()
                    KiraTab.CHARACTERS -> KiraCharactersScreen(selectedCharacter) { selectedCharacter=it }
                    KiraTab.SETTINGS -> when(settingsPage) {
                        SettingsPage.ROUTE -> SettingsSubpage("اتصال API و مدل‌ها",{settingsPage=SettingsPage.HOME}) { KiraRouteScreen() }
                        SettingsPage.MEMORY -> SettingsSubpage("حافظه بلندمدت",{settingsPage=SettingsPage.HOME}) { KiraMemoryScreen() }
                        SettingsPage.SKILLS -> SettingsSubpage("مهارت‌ها و اتصال API",{settingsPage=SettingsPage.HOME}) { KiraSkillsScreen() }
                        SettingsPage.VOICE -> SettingsSubpage("تماس صوتی زنده",{settingsPage=SettingsPage.HOME}) { KiraVoiceScreen() }
                        SettingsPage.ASSISTANT -> SettingsSubpage("دستیار و ویس",{settingsPage=SettingsPage.HOME}) {
                            AssistantScreen(
                                hasOverlayPermission=hasOverlayPermission,
                                overlayStarted=overlayStarted,
                                onRequestOverlayPermission={
                                    val intent=Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,Uri.parse("package:"+context.packageName))
                                    overlaySettingsLauncher.launch(intent)
                                },
                                onStartOverlay={
                                    val intent=Intent(context,AiAssistantOverlayService::class.java).setAction(AiAssistantOverlayService.ACTION_START)
                                    overlayStarted=context.startService(intent)!=null
                                },
                                onStopOverlay={
                                    context.startService(Intent(context,AiAssistantOverlayService::class.java).setAction(AiAssistantOverlayService.ACTION_STOP))
                                    overlayStarted=false
                                }
                            )
                        }
                        SettingsPage.HOME -> KiraSettingsHome(
                            onRoute={settingsPage=SettingsPage.ROUTE},
                            onMemory={settingsPage=SettingsPage.MEMORY},
                            onAssistant={settingsPage=SettingsPage.ASSISTANT},
                            onSkills={settingsPage=SettingsPage.SKILLS},
                            onVoice={settingsPage=SettingsPage.VOICE}
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsSubpage(title:String,onBack:()->Unit,content:@Composable ()->Unit) {
    Column(Modifier.fillMaxSize().background(Color(0xFF0B0E15))) {
        Row(Modifier.fillMaxWidth().padding(horizontal=12.dp,vertical=6.dp),verticalAlignment=Alignment.CenterVertically) {
            TextButton(onClick=onBack) { Text("‹ بازگشت",color=Color(0xFFB9A5FF)) }
            Text(title,color=Color(0xFFF4F2FA),fontWeight=FontWeight.SemiBold,fontSize=16.sp)
        }
        Box(Modifier.weight(1f)) { content() }
    }
}

@Composable
private fun KiraSettingsHome(onRoute:()->Unit,onMemory:()->Unit,onAssistant:()->Unit,onSkills:()->Unit,onVoice:()->Unit) {
    val context=LocalContext.current
    val core=remember { ai.kira.mobile.core.LocalKiraCore(context) }
    val skills=remember { core.installedSkills() }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
        Text("تنظیمات Kira",color=Color(0xFFF4F2FA),fontSize=25.sp,fontWeight=FontWeight.Bold)
        Text("هسته و داده‌ها روی همین دستگاه نگهداری می‌شوند.",color=Color(0xFF9BA5B8),fontSize=12.sp)
        SettingsCard("اتصال API و مدل‌ها","افزودن کلید، دریافت خودکار مدل‌ها و مدیریت اولویت و جایگزینی",onRoute)
        SettingsCard("حافظه بلندمدت","مدیریت یادداشت‌هایی که Kira، Ren و Mika به خاطر می‌سپارند",onMemory)
        SettingsCard("تماس صوتی زنده","مکالمه دوطرفه و کم‌تأخیر با Gemini Live",onVoice)
        SettingsCard("دستیار شناور","دسترسی سریع Kira روی برنامه‌های دیگر",onAssistant)
        SettingsCard("مهارت‌ها و APIها","نصب، فعال‌سازی جداگانه برای شخصیت‌ها و اتصال APIهای واقعی",onSkills)
        SettingsCard("هسته محلی","SQLite محلی و رمزنگاری کلیدها",{})
        Text("کتابخانه: "+core.libraryDirectory(),color=Color(0xFF7F8A9E),fontSize=10.sp)
        Text("مهارت‌های نصب‌شده: "+skills.size,color=Color(0xFF7F8A9E),fontSize=11.sp)
        Text("API Keyها با Android Keystore رمزنگاری می‌شوند و مستقیماً از گوشی به Provider ارسال می‌شوند.",color=Color(0xFF7F8A9E),fontSize=11.sp,lineHeight=17.sp)
    }
}

@Composable
private fun SettingsCard(title:String,description:String,onClick:()->Unit) {
    Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth(),onClick=onClick) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
            Text(title,color=Color(0xFFF1EFF8),fontWeight=FontWeight.SemiBold,fontSize=15.sp)
            Text(description,color=Color(0xFF9BA5B8),fontSize=11.sp,lineHeight=17.sp)
        }
    }
}

@Composable
private fun KiraCharactersScreen(selected:String,onSelect:(String)->Unit) {
    val characters=listOf(
        Triple("kira","Kira","باهوش، مستقل، طعنه‌زن و وفادار"),
        Triple("ren","Ren","آرام، تحلیل‌گر، دقیق و محافظ"),
        Triple("mika","Mika","سرزنده، بازیگوش، کنجکاو و اجتماعی")
    )
    Column(Modifier.fillMaxSize().padding(18.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
        Text("شخصیت‌ها",color=Color(0xFFF4F2FA),fontSize=25.sp,fontWeight=FontWeight.Bold)
        Text("شخصیتی را که در تب چت با آن صحبت می‌کنی انتخاب کن.",color=Color(0xFF9BA5B8),fontSize=12.sp)
        characters.forEach { (id,name,description) ->
            Surface(color=if(selected==id) Color(0xFF292344) else Color(0xFF151C2B),shape=RoundedCornerShape(18.dp),
                modifier=Modifier.fillMaxWidth(),onClick={onSelect(id)}) {
                Row(Modifier.padding(16.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                        Text(name,color=Color(0xFFF4F2FA),fontSize=18.sp,fontWeight=FontWeight.Bold)
                        Text(description,color=Color(0xFF9BA5B8),fontSize=12.sp)
                    }
                    if(selected==id) Text("فعال ✓",color=Color(0xFFB9A5FF),fontSize=12.sp)
                    else OutlinedButton(onClick={onSelect(id)}) { Text("انتخاب") }
                }
            }
        }
    }
}

@Composable
private fun AssistantScreen(
    hasOverlayPermission:Boolean,
    overlayStarted:Boolean,
    onRequestOverlayPermission:()->Unit,
    onStartOverlay:()->Unit,
    onStopOverlay:()->Unit
) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),verticalArrangement=Arrangement.spacedBy(14.dp)) {
        Text("دستیار و ویس",color=Color(0xFFF4F2FA),fontSize=23.sp,fontWeight=FontWeight.Bold)
        InfoPanel("دسترسی سریع روی برنامه‌ها","حباب شناور Kira برای دسترسی از داخل برنامه‌های دیگر.",when {
            overlayStarted -> "حباب شناور فعال است"
            hasOverlayPermission -> "مجوز آماده است"
            else -> "نیازمند مجوز نمایش روی برنامه‌ها"
        }) {
            if(!hasOverlayPermission) Button(onClick=onRequestOverlayPermission,modifier=Modifier.fillMaxWidth()) { Text("دادن مجوز") }
            else if(!overlayStarted) Button(onClick=onStartOverlay,modifier=Modifier.fillMaxWidth()) { Text("فعال‌کردن حباب") }
            else OutlinedButton(onClick=onStopOverlay,modifier=Modifier.fillMaxWidth()) { Text("خاموش‌کردن حباب") }
        }
        InfoPanel("تعامل صوتی","تماس صوتی Real-time با Gemini Live از بخش مستقل «تماس صوتی زنده» در تنظیمات در دسترس است.","فعال") {}
        InfoPanel("درک محتوای صفحه","تحلیل صفحه فقط با اجازه صریح کاربر و پس از پیاده‌سازی نشست امن فعال می‌شود.","فعلاً غیرفعال") {}
    }
}

@Composable
private fun InfoPanel(title:String,description:String,status:String,actions:@Composable ()->Unit={}) {
    Surface(color=Color(0xFF151C2B),shape=RoundedCornerShape(18.dp),modifier=Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                Text(title,color=Color(0xFFF1EFF8),fontWeight=FontWeight.SemiBold,fontSize=15.sp)
                Text(status,color=Color(0xFFB9A5FF),fontSize=10.sp)
            }
            Text(description,color=Color(0xFFA2ADC0),fontSize=12.sp,lineHeight=18.sp)
            actions()
        }
    }
}
