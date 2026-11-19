package ai.kira.mobile.application.chat

import ai.kira.mobile.domain.model.ChatMessage
import ai.kira.mobile.domain.model.ChatResult
import ai.kira.mobile.domain.repository.ChatRepository

class ChatInteractor(private val repository: ChatRepository) {
    fun history(characterId: String, limit: Int = 100): List<ChatMessage> {
        require(characterId.isNotBlank()) { "Character id must not be blank." }
        require(limit > 0) { "History limit must be greater than zero." }
        return repository.history(characterId, limit)
    }

    fun sendMessage(characterId: String, text: String): ChatResult {
        require(characterId.isNotBlank()) { "Character id must not be blank." }
        val normalizedText = text.trim()
        require(normalizedText.isNotEmpty()) { "Message must not be blank." }
        return repository.sendMessage(characterId, normalizedText)
    }

    fun clearHistory(characterId: String) {
        require(characterId.isNotBlank()) { "Character id must not be blank." }
        repository.clearHistory(characterId)
    }
}
