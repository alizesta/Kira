package ai.kira.mobile.core

import android.content.Context
import ai.kira.mobile.application.chat.ChatInteractor
import ai.kira.mobile.application.image.ImageGenerationInteractor
import ai.kira.mobile.application.provider.ProviderApplicationService
import ai.kira.mobile.application.search.InternetSearchInteractor
import ai.kira.mobile.data.image.ImageGenerationSettingsStore
import ai.kira.mobile.data.image.OpenAiCompatibleImageRepository
import ai.kira.mobile.data.local.LocalChatRepository
import ai.kira.mobile.data.local.LocalProviderRepository
import ai.kira.mobile.data.remote.SearchCredentialStore
import ai.kira.mobile.data.remote.TavilySearchRepository
import ai.kira.mobile.application.voice.RealtimeVoiceInteractor
import ai.kira.mobile.data.voice.GeminiLiveCredentialStore
import ai.kira.mobile.data.voice.GeminiLiveVoiceSessionFactory

/** Single Android composition root for app-wide use cases and data adapters. */
class KiraContainer(context: Context) {
    private val app = context.applicationContext
    private val localCore = LocalKiraCore(app)

    val chat: ChatInteractor by lazy { ChatInteractor(LocalChatRepository(localCore)) }

    private val searchCredentials: SearchCredentialStore by lazy { SearchCredentialStore(app) }
    val search: InternetSearchInteractor by lazy {
        InternetSearchInteractor(TavilySearchRepository(searchCredentials), searchCredentials)
    }

    val providers: ProviderApplicationService by lazy {
        ProviderApplicationService(LocalProviderRepository(localCore))
    }

    private val imageSettings: ImageGenerationSettingsStore by lazy { ImageGenerationSettingsStore(app) }
    val images: ImageGenerationInteractor by lazy {
        ImageGenerationInteractor(OpenAiCompatibleImageRepository(app, imageSettings), imageSettings)
    }

    private val voiceCredentials: GeminiLiveCredentialStore by lazy { GeminiLiveCredentialStore(app) }
    private val voiceSessionFactory: GeminiLiveVoiceSessionFactory by lazy { GeminiLiveVoiceSessionFactory(app) }
    val voice: RealtimeVoiceInteractor by lazy {
        RealtimeVoiceInteractor(voiceCredentials, voiceSessionFactory)
    }

    fun libraryDirectory(): String = localCore.libraryDirectory()

    fun installedSkillCount(): Int = localCore.installedSkills().size

}
