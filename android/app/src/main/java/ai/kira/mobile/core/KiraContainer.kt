package ai.kira.mobile.core

import android.content.Context
import ai.kira.mobile.application.chat.ChatInteractor
import ai.kira.mobile.data.local.LocalChatRepository

class KiraContainer(context: Context) {
    private val localCore = LocalKiraCore(context.applicationContext)

    val chat: ChatInteractor by lazy {
        ChatInteractor(LocalChatRepository(localCore))
    }
}
