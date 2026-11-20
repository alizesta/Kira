package ai.kira.mobile.application.chat

import ai.kira.mobile.domain.model.ChatAttachmentInput
import ai.kira.mobile.domain.model.ChatMessage
import ai.kira.mobile.domain.model.ChatResult
import ai.kira.mobile.domain.repository.ChatRepository
import org.junit.Assert.assertEquals
import org.junit.Test

class ChatInteractorTest {
    @Test
    fun sendMessageTrimsWhitespaceBeforeCallingRepository() {
        val repository = FakeChatRepository()
        val interactor = ChatInteractor(repository)

        val result = interactor.sendMessage("kira", "  hello Kira  ")

        assertEquals("hello Kira", repository.sentText)
        assertEquals("hello Kira", result.content)
    }

    @Test(expected = IllegalArgumentException::class)
    fun sendMessageRejectsBlankInput() {
        ChatInteractor(FakeChatRepository()).sendMessage("kira", "  \n  ")
    }

    @Test(expected = IllegalArgumentException::class)
    fun historyRejectsNonPositiveLimit() {
        ChatInteractor(FakeChatRepository()).history("kira", 0)
    }

    @Test
    fun sendMessageAcceptsAttachmentWithoutTypedText() {
        val repository = FakeChatRepository()
        val file = ChatAttachmentInput("notes.txt", "text/plain", "Kira notes".toByteArray())
        val result = ChatInteractor(repository).sendMessage("kira", "", listOf(file))
        assertEquals("فایل‌های پیوست‌شده را بررسی کن و نکات مهم آن‌ها را توضیح بده.", repository.sentText)
        assertEquals("notes.txt", repository.sentAttachments.single().name)
        assertEquals("fake", result.provider)
    }

    @Test(expected = IllegalArgumentException::class)
    fun sendMessageRejectsUnsupportedAttachmentType() {
        ChatInteractor(FakeChatRepository()).sendMessage("kira", "inspect",
            listOf(ChatAttachmentInput("payload.exe", "application/octet-stream", byteArrayOf(1,2,3))))
    }

    @Test(expected = IllegalArgumentException::class)
    fun sendMessageRejectsImageWithMismatchedContent() {
        ChatInteractor(FakeChatRepository()).sendMessage("kira", "inspect",
            listOf(ChatAttachmentInput("fake.png", "image/png", "not an image".toByteArray())))
    }

    @Test(expected = IllegalArgumentException::class)
    fun sendMessageRejectsMoreThanFiveAttachments() {
        val files=(1..6).map { ChatAttachmentInput("note"+it+".txt","text/plain","ok".toByteArray()) }
        ChatInteractor(FakeChatRepository()).sendMessage("kira","inspect",files)
    }

    private class FakeChatRepository : ChatRepository {
        var sentText: String = ""
        var sentAttachments: List<ChatAttachmentInput> = emptyList()
        override fun history(characterId: String, limit: Int): List<ChatMessage> = emptyList()
        override fun sendMessage(characterId: String, text: String, attachments: List<ChatAttachmentInput>): ChatResult {
            sentText=text
            sentAttachments=attachments
            return ChatResult(text,"fake","fake-model")
        }
        override fun clearHistory(characterId: String) = Unit
    }
}
