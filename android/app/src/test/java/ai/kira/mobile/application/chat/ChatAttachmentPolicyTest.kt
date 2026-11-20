package ai.kira.mobile.application.chat
import ai.kira.mobile.domain.model.ChatAttachmentInput
import org.junit.Assert.assertTrue
import org.junit.Test
class ChatAttachmentPolicyTest {
 @Test fun acceptsTextFile() {
  ChatAttachmentPolicy.validate(listOf(ChatAttachmentInput("notes.md","text/markdown","# note".toByteArray())))
 }
 @Test fun acceptsPngSignature() {
  val bytes=byteArrayOf(0x89.toByte(),0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A)+ByteArray(16)
  ChatAttachmentPolicy.validate(listOf(ChatAttachmentInput("screen.png","image/png",bytes)))
  assertTrue(ChatAttachmentPolicy.isImage("image/png"))
 }
 @Test(expected=IllegalArgumentException::class) fun rejectsUnsupportedBinary() {
  ChatAttachmentPolicy.validate(listOf(ChatAttachmentInput("payload.bin","application/octet-stream",byteArrayOf(1))))
 }
 @Test(expected=IllegalArgumentException::class) fun rejectsWrongImageSignature() {
  ChatAttachmentPolicy.validate(listOf(ChatAttachmentInput("fake.jpg","image/jpeg","text".toByteArray())))
 }
 @Test(expected=IllegalArgumentException::class) fun rejectsEmptyFile() {
  ChatAttachmentPolicy.validate(listOf(ChatAttachmentInput("empty.txt","text/plain",byteArrayOf())))
 }
 @Test(expected=IllegalArgumentException::class) fun rejectsOversizedText() {
  ChatAttachmentPolicy.validate(listOf(ChatAttachmentInput("large.txt","text/plain",ByteArray(ChatAttachmentPolicy.MAX_TEXT_BYTES+1))))
 }
 @Test(expected=IllegalArgumentException::class) fun rejectsTraversalName() {
  ChatAttachmentPolicy.validate(listOf(ChatAttachmentInput("../secret.txt","text/plain","safe".toByteArray())))
 }
}
