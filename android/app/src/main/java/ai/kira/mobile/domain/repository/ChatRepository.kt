package ai.kira.mobile.domain.repository

import ai.kira.mobile.domain.model.ChatAttachmentInput
import ai.kira.mobile.domain.model.ChatMessage
import ai.kira.mobile.domain.model.ChatResult

interface ChatRepository {
    fun history(characterId: String, limit: Int = 100): List<ChatMessage>
    fun sendMessage(characterId: String, text: String, attachments: List<ChatAttachmentInput> = emptyList()): ChatResult
    fun clearHistory(characterId: String)
}
