package ai.kira.mobile.core

import android.content.Context
import ai.kira.mobile.application.chat.ChatInteractor
import ai.kira.mobile.application.search.InternetSearchInteractor
import ai.kira.mobile.application.image.ImageGenerationInteractor
import ai.kira.mobile.data.local.LocalChatRepository
import ai.kira.mobile.data.remote.SearchCredentialStore
import ai.kira.mobile.data.remote.TavilySearchRepository
import ai.kira.mobile.data.image.ImageGenerationSettingsStore
import ai.kira.mobile.data.image.OpenAiCompatibleImageRepository

class KiraContainer(context: Context) {
    private val app = context.applicationContext
    private val localCore = LocalKiraCore(app)

    val chat: ChatInteractor by lazy {
        ChatInteractor(LocalChatRepository(localCore))
    }

    val searchCredentials: SearchCredentialStore by lazy {
        SearchCredentialStore(app)
    }

    val search: InternetSearchInteractor by lazy {
        InternetSearchInteractor(TavilySearchRepository(searchCredentials))
    }

    val imageSettings: ImageGenerationSettingsStore by lazy {
        ImageGenerationSettingsStore(app)
    }

    val images: ImageGenerationInteractor by lazy {
        ImageGenerationInteractor(OpenAiCompatibleImageRepository(app, imageSettings))
    }
}
