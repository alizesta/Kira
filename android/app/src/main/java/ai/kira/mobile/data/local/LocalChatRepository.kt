package ai.kira.mobile.data.local

import ai.kira.mobile.core.LocalKiraCore
import ai.kira.mobile.domain.model.ChatMessage
import ai.kira.mobile.domain.model.ConnectorDefinition
import ai.kira.mobile.domain.model.ProviderRoute
import ai.kira.mobile.domain.repository.ChatRepository

/** SQLite/Android Keystore adapter for the Chat repository port. */
class LocalChatRepository(private val core:LocalKiraCore):ChatRepository {
    override fun history(characterId:String,limit:Int):List<ChatMessage> =
        core.history(characterId,limit).map { ChatMessage(it.id,it.role,it.content,it.route,it.createdAt) }

    override fun providerRoutes():List<ProviderRoute> = core.providers().map {
        ProviderRoute(it.id,it.model,it.baseUrl,it.enabled,it.priority,it.hasKey)
    }

    override fun providerApiKey(providerId:String):String = core.providerApiKey(providerId)

    override fun appendMessage(characterId:String,role:String,content:String,route:String) =
        core.appendChatMessage(characterId,role,content,route)

    override fun connectorsFor(characterId:String):List<ConnectorDefinition> =
        core.connectorDefinitions(characterId).map { ConnectorDefinition(it.id,it.description,it.parameters) }

    override fun executeConnectorResponse(characterId:String,assistantContent:String):String? =
        core.executeConnectorResponse(characterId,assistantContent)

    override fun clearHistory(characterId:String) = core.clearHistory(characterId)
}
