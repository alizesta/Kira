package ai.kira.mobile.data.local

import ai.kira.mobile.core.LocalKiraCore
import ai.kira.mobile.domain.model.ChatAttachmentInfo
import ai.kira.mobile.domain.model.ChatAttachmentInput
import ai.kira.mobile.domain.model.ChatMessage
import ai.kira.mobile.domain.model.ChatResult
import ai.kira.mobile.domain.repository.ChatRepository

class LocalChatRepository(
    private val core: LocalKiraCore
) : ChatRepository {
    override fun history(characterId: String, limit: Int): List<ChatMessage> =
        core.history(characterId, limit).map { message ->
            ChatMessage(
                id = message.id,
                role = message.role,
                content = message.content,
                route = message.route,
                createdAt = message.createdAt,
                attachments = message.attachments.map { a -> ChatAttachmentInfo(a.id,a.name,a.mimeType,a.sizeBytes) }
            )
        }

    override fun sendMessage(characterId:String,text:String,attachments:List<ChatAttachmentInput>):ChatResult {
        val result = core.sendMessage(characterId,text,attachments)
        return ChatResult(
            content = result.content,
            provider = result.provider,
            model = result.model
        )
    }

    override fun clearHistory(characterId: String) {
        core.clearHistory(characterId)
    }
}
