package ai.kira.mobile.data.remote

import ai.kira.mobile.domain.model.ConnectorExecutionConfig
import ai.kira.mobile.domain.repository.ConnectorConfigurationRepository
import ai.kira.mobile.domain.repository.ConnectorExecutionGateway
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/** Remote adapter for approved, read-only HTTPS API connectors. Redirects and private hosts are blocked. */
class HttpApiConnectorGateway(
    private val configurations:ConnectorConfigurationRepository
):ConnectorExecutionGateway {
    override fun executeIfRequested(characterId:String,assistantContent:String):String? {
        val call=parseCall(assistantContent) ?: return null
        return try {
            val config=configurations.executionConfig(characterId,call.id)
                ?: throw IllegalStateException("Connector نصب‌شده پیدا نشد یا برای این شخصیت فعال نیست.")
            execute(config,call.params)
        } catch(error:Exception) {
            "Connector error: ${error.message ?: "request failed"}"
        }
    }

    private fun parseCall(content:String):ConnectorCall? {
        val match=Regex("<kira_connector>\\s*(\\{.*?\\})\\s*</kira_connector>",setOf(RegexOption.DOT_MATCHES_ALL)).find(content)
            ?: return null
        val json=JSONObject(match.groupValues[1])
        val id=json.optString("id")
        require(id.isNotBlank()) { "شناسه Connector در درخواست مدل خالی است." }
        return ConnectorCall(id,json.optJSONObject("params") ?: JSONObject())
    }

    private fun execute(config:ConnectorExecutionConfig,params:JSONObject):String {
        val base=URL(config.baseUrl)
        require(base.protocol=="https" && base.host.isNotBlank() && base.userInfo==null &&
            base.query==null && base.ref==null && (base.port==-1 || base.port==443)) {
            "آدرس پایه Connector معتبر نیست."
        }
        val supplied=mutableListOf<String>()
        val keys=params.keys()
        while(keys.hasNext()) supplied+=keys.next()
        require(supplied.all { it in config.allowedParameters }) { "Connector پارامتر ناشناخته دریافت کرد." }
        val placeholders=Regex("\\{([A-Za-z][A-Za-z0-9_]*)}").findAll(config.pathTemplate)
            .map { it.groupValues[1] }.toSet()
        require(placeholders.all { it in config.allowedParameters }) { "قالب مسیر Connector معتبر نیست." }
        val path=Regex("\\{([A-Za-z][A-Za-z0-9_]*)}").replace(config.pathTemplate) { match ->
            val key=match.groupValues[1]
            val value=params.optString(key,"")
            require(value.isNotBlank() && value.length<=200) { "پارامتر $key الزامی است." }
            URLEncoder.encode(value,StandardCharsets.UTF_8.name()).replace("+","%20")
        }
        require(!path.contains("{") && !path.contains("}")) { "پارامتر مسیر ناقص است." }
        val query=supplied.filter { it !in placeholders }.sorted().map { key ->
            val value=params.optString(key,"")
            require(value.length<=500) { "مقدار پارامتر بیش از حد بزرگ است." }
            URLEncoder.encode(key,StandardCharsets.UTF_8.name())+"="+
                URLEncoder.encode(value,StandardCharsets.UTF_8.name())
        }
        val url=URL(config.baseUrl.trimEnd('/')+path+(if(query.isEmpty()) "" else "?"+query.joinToString("&")))
        require(url.protocol=="https" && url.host.equals(base.host,true) &&
            (url.port==-1 || url.port==443) && isPublicHost(url.host)) {
            "مقصد Connector معتبر یا عمومی نیست."
        }
        val connection=(url.openConnection() as HttpURLConnection).apply {
            requestMethod="GET"
            instanceFollowRedirects=false
            connectTimeout=10_000
            readTimeout=20_000
            setRequestProperty("Accept","application/json")
        }
        try {
            if(config.authType=="bearer") {
                require(config.apiKey.isNotBlank()) { "کلید API این Connector بازخوانی نشد." }
                connection.setRequestProperty("Authorization","Bearer "+config.apiKey)
            }
            val status=connection.responseCode
            val stream=if(status in 200..299) connection.inputStream else connection.errorStream
            val body=stream?.use { input ->
                val bytes=java.io.ByteArrayOutputStream()
                val buffer=ByteArray(4096)
                while(true) {
                    val count=input.read(buffer)
                    if(count<0) break
                    if(bytes.size()+count>MAX_RESPONSE_BYTES)
                        throw IllegalStateException("پاسخ Connector از ۶۴ کیلوبایت بیشتر است.")
                    bytes.write(buffer,0,count)
                }
                bytes.toString("UTF-8")
            }.orEmpty()
            if(status !in 200..299)
                throw IllegalStateException("Connector با HTTP $status پاسخ داد: "+body.take(500))
            if(body.isBlank()) throw IllegalStateException("Connector پاسخ خالی برگرداند.")
            return body
        } finally { connection.disconnect() }
    }

    private fun isPublicHost(host:String):Boolean = try {
        val addresses=InetAddress.getAllByName(host)
        addresses.isNotEmpty() && addresses.all { address ->
            !address.isAnyLocalAddress && !address.isLoopbackAddress &&
                !address.isLinkLocalAddress && !address.isSiteLocalAddress && !address.isMulticastAddress
        }
    } catch(_:Exception) { false }

    private data class ConnectorCall(val id:String,val params:JSONObject)
    private companion object { const val MAX_RESPONSE_BYTES=65_536 }
}
