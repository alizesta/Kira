package ai.kira.mobile.data.remote

import ai.kira.mobile.application.search.InternetSearchRepository
import ai.kira.mobile.application.search.InternetSearchResponse
import ai.kira.mobile.application.search.InternetSearchResult
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SearchCredentialStore(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences("kira_search_credentials", Context.MODE_PRIVATE)

    fun hasApiKey(): Boolean = preferences.contains(KEY_ENTRY)

    @Synchronized
    fun saveApiKey(value: String) {
        val normalized = value.trim()
        require(normalized.isNotEmpty()) { "Search API key must not be blank." }
        require(normalized.length <= 512) { "Search API key is too long." }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(normalized.toByteArray(StandardCharsets.UTF_8))
        preferences.edit().putString(KEY_ENTRY, Base64.encodeToString(cipher.iv + encrypted, Base64.NO_WRAP)).apply()
    }

    @Synchronized
    fun readApiKey(): String {
        val encoded = preferences.getString(KEY_ENTRY, null)
            ?: throw IllegalStateException("ابتدا کلید Tavily Search را ذخیره کن.")
        val payload = Base64.decode(encoded, Base64.NO_WRAP)
        require(payload.size > IV_LENGTH) { "کلید ذخیره‌شده جستجو معتبر نیست." }
        val iv = payload.copyOfRange(0, IV_LENGTH)
        val encrypted = payload.copyOfRange(IV_LENGTH, payload.size)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, iv))
        return String(cipher.doFinal(encrypted), StandardCharsets.UTF_8)
    }

    @Synchronized
    fun clearApiKey() {
        preferences.edit().remove(KEY_ENTRY).apply()
    }

    private fun getOrCreateKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build()
        )
        return generator.generateKey()
    }

    private companion object {
        const val KEY_ALIAS = "kira.search.tavily.key.v1"
        const val KEY_ENTRY = "tavily_api_key"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_LENGTH = 12
    }
}

class TavilySearchRepository(
    private val credentials: SearchCredentialStore
) : InternetSearchRepository {
    override fun search(query: String, maxResults: Int): InternetSearchResponse {
        val connection = URL(ENDPOINT).openConnection() as HttpURLConnection
        try {
            val body = JSONObject()
                .put("query", query)
                .put("search_depth", "basic")
                .put("max_results", maxResults.coerceIn(1, 8))
                .put("include_answer", true)
                .put("include_raw_content", false)
                .put("include_images", false)

            connection.requestMethod = "POST"
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 12_000
            connection.readTimeout = 25_000
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Authorization", "Bearer " + credentials.readApiKey())
            connection.outputStream.use { it.write(body.toString().toByteArray(StandardCharsets.UTF_8)) }

            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val raw = stream?.use { readLimited(it, MAX_RESPONSE_BYTES) }.orEmpty()
            if (status !in 200..299) {
                val detail = runCatching {
                    JSONObject(raw).optString("detail").ifBlank { JSONObject(raw).optString("message") }
                }.getOrDefault("")
                throw IllegalStateException("جستجوی وب با HTTP " + status + " شکست خورد. " + detail.take(240))
            }

            val json = JSONObject(raw)
            val rows = json.optJSONArray("results")
            val results = buildList {
                if (rows != null) for (index in 0 until rows.length()) {
                    val row = rows.optJSONObject(index) ?: continue
                    val title = row.optString("title").trim()
                    val url = row.optString("url").trim()
                    val excerpt = row.optString("content").trim()
                    if (title.isBlank() || excerpt.isBlank() || !isHttpsUrl(url)) continue
                    add(InternetSearchResult(title.take(300), url, excerpt.take(2_000), row.optDouble("score", 0.0)))
                }
            }
            return InternetSearchResponse(json.optString("answer").trim().take(6_000), results)
        } finally {
            connection.disconnect()
        }
    }

    private fun isHttpsUrl(value: String): Boolean = runCatching {
        val parsed = URL(value)
        parsed.protocol.equals("https", ignoreCase = true) && parsed.host.isNotBlank()
    }.getOrDefault(false)

    private fun readLimited(input: java.io.InputStream, limit: Int): String {
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(8_192)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            if (output.size() + count > limit) throw IllegalStateException("پاسخ جستجو بیش از حد بزرگ است.")
            output.write(buffer, 0, count)
        }
        return output.toString("UTF-8")
    }

    private companion object {
        const val ENDPOINT = "https://api.tavily.com/search"
        const val MAX_RESPONSE_BYTES = 512 * 1024
    }
}
