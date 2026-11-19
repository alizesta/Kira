package ai.kira.mobile.application.search

data class InternetSearchResult(
    val title: String,
    val url: String,
    val excerpt: String,
    val score: Double
)

data class InternetSearchResponse(
    val answer: String,
    val results: List<InternetSearchResult>
)

interface InternetSearchRepository {
    fun search(query: String, maxResults: Int = 6): InternetSearchResponse
}

class InternetSearchInteractor(private val repository: InternetSearchRepository) {
    fun search(query: String): InternetSearchResponse {
        val normalized = query.trim()
        require(normalized.length >= 2) { "Search query is too short." }
        require(normalized.length <= 350) { "Search query is too long." }
        return repository.search(normalized, maxResults = 6)
    }
}
