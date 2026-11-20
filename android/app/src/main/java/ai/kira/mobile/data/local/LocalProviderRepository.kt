package ai.kira.mobile.data.local

import ai.kira.mobile.core.LocalKiraCore
import ai.kira.mobile.domain.model.ProviderConnection
import ai.kira.mobile.domain.model.ProviderDiscovery
import ai.kira.mobile.domain.repository.ProviderRepository

/** SQLite/Android adapter for the provider repository port. */
class LocalProviderRepository(private val core: LocalKiraCore) : ProviderRepository {
    override fun providers(): List<ProviderConnection> =
        core.providers().map { local ->
            ProviderConnection(
                providerId = local.id,
                displayName = ProviderEndpointCatalog.label(local.id),
                modelId = local.model,
                enabled = local.enabled,
                priority = local.priority,
                hasApiKey = local.hasKey
            )
        }

    override fun cachedModels(providerId: String): List<String> = core.discoveredModels(providerId)

    override fun discoverProvider(apiKey: String): ProviderDiscovery {
        val (providerId, modelIds) = core.detectProviderAndDiscoverModels(apiKey)
        return ProviderDiscovery(providerId, modelIds)
    }

    override fun refreshModels(providerId: String): List<String> = core.refreshFreeModels(providerId)

    override fun saveProvider(providerId: String, modelId: String, apiKey: String?) {
        val existing = core.providers().firstOrNull { it.id == providerId }
        val endpoint = existing?.baseUrl ?: ProviderEndpointCatalog.baseUrl(providerId)
        core.saveProvider(
            id = providerId,
            model = modelId,
            baseUrl = endpoint,
            apiKey = apiKey.orEmpty(),
            enabled = existing?.enabled ?: true
        )
    }

    override fun setEnabled(providerId: String, enabled: Boolean) = core.setProviderEnabled(providerId, enabled)
    override fun move(providerId: String, delta: Int) = core.moveProvider(providerId, delta)
}
