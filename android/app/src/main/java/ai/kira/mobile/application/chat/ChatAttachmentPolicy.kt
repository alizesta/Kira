package ai.kira.mobile.application.chat
import ai.kira.mobile.domain.model.ChatAttachmentInput
object ChatAttachmentPolicy {
 const val MAX_ATTACHMENTS=5
 const val MAX_IMAGE_BYTES=8*1024*1024
 const val MAX_TEXT_BYTES=512*1024
 const val MAX_TOTAL_BYTES=12*1024*1024
 private val images=setOf("image/png","image/jpeg","image/webp")
 private val text=setOf("text/plain","text/markdown","text/csv","text/tab-separated-values","text/xml","text/yaml","text/x-log","text/x-python","text/x-java","text/x-kotlin","application/json","application/xml","application/yaml","application/x-yaml","application/x-ndjson","application/sql","application/x-sql","application/javascript")
 fun normalizeMime(v:String)=v.substringBefore(';').trim().lowercase()
 fun isImage(v:String)=normalizeMime(v) in images
 fun isText(v:String):Boolean { val m=normalizeMime(v); return m in text || (m.startsWith("text/") && m!="text/html") }
 fun validate(files:List<ChatAttachmentInput>) {
  require(files.size<=MAX_ATTACHMENTS) { "حداکثر ۵ فایل را می‌توان هم‌زمان پیوست کرد." }
  var total=0L
  files.forEachIndexed { index,f ->
   val name=f.name.trim()
   require(name.isNotEmpty() && name.length<=160 && !name.contains('/') && !name.contains('\\') && name.none { it.isISOControl() }) { "نام فایل شماره " +(index+1)+" معتبر نیست." }
   val mime=normalizeMime(f.mimeType); val image=mime in images
   require(image || isText(mime)) { "فرمت «"+mime+"» پشتیبانی نمی‌شود." }
   val size=f.bytes.size
   require(size>0) { "فایل «"+name+"» خالی است." }
   require(size<=(if(image) MAX_IMAGE_BYTES else MAX_TEXT_BYTES)) { "حجم فایل «"+name+"» از حد مجاز بیشتر است." }
   if(image) verifyImage(name,mime,f.bytes)
   if(isText(mime)) require(f.bytes.none { it==0.toByte() }) { "فایل «"+name+"» متن معتبر نیست." }
   total+=size.toLong()
   require(total<=MAX_TOTAL_BYTES) { "حجم مجموع پیوست‌ها نباید از ۱۲ مگابایت بیشتر شود." }
  }
 }
 private fun verifyImage(name:String,mime:String,b:ByteArray) {
  fun Byte.u()=toInt() and 255
  val ok=when(mime) {
   "image/png" -> b.size>=8 && b[0].u()==137 && b[1].u()==80 && b[2].u()==78 && b[3].u()==71 && b[4].u()==13 && b[5].u()==10 && b[6].u()==26 && b[7].u()==10
   "image/jpeg" -> b.size>=3 && b[0].u()==255 && b[1].u()==216 && b[2].u()==255
   "image/webp" -> b.size>=12 && b.copyOfRange(0,4).decodeToString()=="RIFF" && b.copyOfRange(8,12).decodeToString()=="WEBP"
   else -> false
  }
  require(ok) { "محتوای فایل «"+name+"» با فرمت تصویر مطابقت ندارد." }
 }
}
