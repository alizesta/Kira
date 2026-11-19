package ai.kira.mobile.application.search

import org.junit.Assert.assertEquals
import org.junit.Test

class InternetSearchInteractorTest {
    @Test
    fun trimsQueryAndCapsResultCount() {
        val repository = FakeSearchRepository()
        InternetSearchInteractor(repository).search("  Kira Android  ")
        assertEquals("Kira Android", repository.lastQuery)
        assertEquals(6, repository.lastLimit)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsShortQueryBeforeNetworkCall() {
        InternetSearchInteractor(FakeSearchRepository()).search(" ")
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsOverlongQuery() {
        InternetSearchInteractor(FakeSearchRepository()).search("x".repeat(351))
    }

    private class FakeSearchRepository : InternetSearchRepository {
        var lastQuery = ""
        var lastLimit = 0

        override fun search(query: String, maxResults: Int): InternetSearchResponse {
            lastQuery = query
            lastLimit = maxResults
            return InternetSearchResponse("", emptyList())
        }
    }
}
