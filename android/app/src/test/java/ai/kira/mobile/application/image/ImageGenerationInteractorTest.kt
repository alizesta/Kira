package ai.kira.mobile.application.image

import org.junit.Assert.assertEquals
import org.junit.Test

class ImageGenerationInteractorTest {
    @Test
    fun normalizesPromptAndPassesSupportedSize() {
        val repository = FakeImageRepository()
        val image = ImageGenerationInteractor(repository).generate("  a blue fox  ", "1024x1024")
        assertEquals("a blue fox", repository.prompt)
        assertEquals("1024x1024", repository.size)
        assertEquals("test-image", image.id)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsShortPromptBeforeNetworkCall() {
        ImageGenerationInteractor(FakeImageRepository()).generate("  ", "1024x1024")
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsUnsupportedSize() {
        ImageGenerationInteractor(FakeImageRepository()).generate("a blue fox", "64x64")
    }

    private class FakeImageRepository : ImageGenerationRepository {
        var prompt = ""
        var size = ""
        override fun generate(prompt: String, size: String): GeneratedImage {
            this.prompt = prompt
            this.size = size
            return GeneratedImage("test-image", prompt, "test-model", "/tmp/image.png", 1L)
        }
        override fun history(limit: Int): List<GeneratedImage> = emptyList()
    }
}
