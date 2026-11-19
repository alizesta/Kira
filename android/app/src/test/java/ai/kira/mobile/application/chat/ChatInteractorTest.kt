package ai.kira.mobile.application.chat

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

    private class FakeChatRepository : ChatRepository {
        var sentText: String = ""

        override fun history(characterId: String, limit: Int): List<ChatMessage> = emptyList()

        override fun sendMessage(characterId: String, text: String): ChatResult {
            sentText = text
            return ChatResult(text, "fake", "fake-model")
        }

        override fun clearHistory(characterId: String) = Unit
    }
}
