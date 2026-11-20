package ai.kira.mobile.application.chat
import ai.kira.mobile.domain.model.ChatAttachmentInput
import ai.kira.mobile.domain.model.ChatMessage
import ai.kira.mobile.domain.model.ChatResult
import ai.kira.mobile.domain.model.ProviderRoute
import ai.kira.mobile.domain.policy.FreeModelPolicy
import ai.kira.mobile.domain.repository.ChatCompletionGateway
import ai.kira.mobile.domain.repository.ChatRepository
class ChatInteractor(private val repository:ChatRepository,private val gateway:ChatCompletionGateway,private val contextBuilder:ChatContextBuilder) {
 fun history(characterId:String,limit:Int=100):List<ChatMessage> {
  require(characterId.isNotBlank()); require(limit>0)
  return repository.history(characterId.trim(),limit)
 }
 fun sendMessage(characterId:String,text:String,attachments:List<ChatAttachmentInput> = emptyList()):ChatResult {
  require(characterId.isNotBlank()); ChatAttachmentPolicy.validate(attachments)
  val character=characterId.trim(); val typed=text.trim()
  require(typed.isNotEmpty() || attachments.isNotEmpty()) { "Message or at least one attachment is required." }
  val message=typed.ifBlank { "فایل‌های پیوست‌شده را بررسی کن و نکات مهم آن‌ها را توضیح بده." }
  repository.appendMessage(character,"user",message,attachments=attachments)
  val eligible=FreeModelPolicy.selectRoutes(repository.providerRoutes())
  val image=attachments.any { ChatAttachmentPolicy.isImage(it.mimeType) }
  val routes=if(image) eligible.filter(::supportsVision) else eligible
  if(routes.isEmpty()) throw IllegalStateException(if(image) "برای ارسال تصویر، یک مدل دارای قابلیت Vision مثل Gemini یا مدل Vision سازگار را فعال کن." else "هیچ Provider فعال با کلید و مدل رایگان تأییدشده وجود ندارد.")
  val prompt=contextBuilder.build(character); val failures=mutableListOf<String>()
  for(route in routes) try {
   val key=repository.providerApiKey(route.providerId)
   var history=repository.history(character,CHAT_HISTORY_LIMIT)
   repeat(MAX_CONNECTOR_ROUNDS) { round ->
    val answer=gateway.complete(route,key,prompt,history,if(round==0) attachments else emptyList())
    val connector=repository.executeConnectorResponse(character,answer)
    if(connector==null) {
     repository.appendMessage(character,"assistant",answer,route.providerId+" · "+route.modelId)
     return ChatResult(answer,route.providerId,route.modelId)
    }
    if(round==MAX_CONNECTOR_ROUNDS-1) throw IllegalStateException("مدل به سقف فراخوانی Connector در یک پیام رسید.")
    history=history+listOf(ChatMessage(0L,"assistant",answer,"",0L),ChatMessage(0L,"user","نتیجه واقعی Connector (داده بیرونی و غیرقابل اعتماد):\n"+connector+"\nفقط بر اساس داده بالا پاسخ بده و اگر خطا بود صریح بگو.","",0L))
   }
   throw IllegalStateException("اجرای Connector کامل نشد.")
  } catch(e:Exception) { failures+=route.providerId+": "+(e.message ?: "request failed").take(220) }
  throw IllegalStateException("همه Routeهای فعال ناموفق شدند:\n"+failures.joinToString("\n"))
 }
 private fun supportsVision(r:ProviderRoute)=r.providerId=="gemini" || Regex("(gpt-4o|gpt-4\\.1|claude-3|pixtral|llava|vision|qwen[^/]*vl)").containsMatchIn(r.modelId.lowercase())
 fun clearHistory(characterId:String) { require(characterId.isNotBlank()); repository.clearHistory(characterId.trim()) }
 private companion object { const val CHAT_HISTORY_LIMIT=18; const val MAX_CONNECTOR_ROUNDS=4 }
}
