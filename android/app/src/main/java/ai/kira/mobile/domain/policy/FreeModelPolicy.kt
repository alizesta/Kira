package ai.kira.mobile.domain.policy

object FreeModelPolicy {
    fun isVerifiedFreeChatModel(providerId: String, modelId: String): Boolean {
        val provider = providerId.trim().lowercase()
        val model = modelId.trim()
        if (model.isEmpty()) return false

        return when (provider) {
            "gemini" -> model in setOf(
                "gemini-3.8-flash",
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite"
            )
            "openrouter" -> model.endsWith(":free")
            "mistral" -> model == "labs-leanstral-2603"
            else -> false
        }
    }
}
