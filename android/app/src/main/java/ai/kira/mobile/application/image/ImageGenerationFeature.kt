package ai.kira.mobile.application.image

data class GeneratedImage(
    val id: String,
    val prompt: String,
    val model: String,
    val localPath: String,
    val createdAt: Long
)

interface ImageGenerationRepository {
    fun generate(prompt: String, size: String): GeneratedImage
    fun history(limit: Int = 40): List<GeneratedImage>
}

class ImageGenerationInteractor(private val repository: ImageGenerationRepository) {
    fun generate(prompt: String, size: String): GeneratedImage {
        val normalizedPrompt = prompt.trim()
        require(normalizedPrompt.length >= 3) { "Image prompt is too short." }
        require(normalizedPrompt.length <= 2_000) { "Image prompt is too long." }
        require(size in SUPPORTED_SIZES) { "Unsupported image size." }
        return repository.generate(normalizedPrompt, size)
    }

    fun history(limit: Int = 40): List<GeneratedImage> {
        require(limit in 1..100) { "History limit is out of range." }
        return repository.history(limit)
    }

    private companion object {
        val SUPPORTED_SIZES = setOf("1024x1024", "1024x1536", "1536x1024")
    }
}
