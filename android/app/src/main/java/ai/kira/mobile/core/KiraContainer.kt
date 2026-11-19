package ai.kira.mobile.core

import android.content.Context
import ai.kira.mobile.application.chat.ChatInteractor
import ai.kira.mobile.data.local.LocalChatRepository
import ai.kira.mobile.application.search.InternetSearchInteractor
import ai.kira.mobile.data.remote.SearchCredentialStore
import ai.kira.mobile.data.remote.TavilySearchRepository

class KiraContainer(context: Context) {
    private val localCore = LocalKiraCore(context.applicationContext)

    val chat: ChatInteractor by lazy {
        ChatInteractor(LocalChatRepository(localCore))
    }

    val searchCredentials: SearchCredentialStore by lazy {
        SearchCredentialStore(context.applicationContext)
    }

    val search: InternetSearchInteractor by lazy {
        InternetSearchInteractor(TavilySearchRepository(searchCredentials))
    }
}
