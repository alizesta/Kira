package ai.kira.mobile.application.chat

import ai.kira.mobile.domain.model.ChatAttachmentInput
import ai.kira.mobile.domain.model.ChatMessage
import ai.kira.mobile.domain.model.ChatResult
import ai.kira.mobile.domain.repository.ChatRepository

class ChatInteractor(private val repository: ChatRepository) {
    fun history(characterId: String, limit: Int = 100): List<ChatMessage> {
        require(characterId.isNotBlank()) { "Character id must not be blank." }
        require(limit > 0) { "History limit must be greater than zero." }
        return repository.history(characterId, limit)
    }

    fun sendMessage(characterId:String,text:String,attachments:List<ChatAttachmentInput> = emptyList()):ChatResult {
        require(characterId.isNotBlank()) { "Character id must not be blank." }
        ChatAttachmentPolicy.validate(attachments)
        val normalized=text.trim()
        require(normalized.isNotEmpty() || attachments.isNotEmpty()) { "Message or an attachment is required." }
        val content=normalized.ifBlank { "فایل‌های پیوست‌شده را بررسی کن و نکات مهم آن‌ها را توضیح بده." }
        return repository.sendMessage(characterId,content,attachments)
    }

    fun clearHistory(characterId: String) {
        require(characterId.isNotBlank()) { "Character id must not be blank." }
        repository.clearHistory(characterId)
    }
}
