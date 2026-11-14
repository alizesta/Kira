package ai.kira.mobile.core

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class LocalProvider(val id:String,val model:String,val baseUrl:String,val enabled:Boolean,val priority:Int,val hasKey:Boolean)
data class LocalChatMessage(val id:Long,val role:String,val content:String,val route:String,val createdAt:Long)
data class LocalChatReply(val content:String,val provider:String,val model:String)

private class LocalKeyVault {
    private val alias="kira.local.provider.keys.v1"
    private val key:SecretKey by lazy {
        val store=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias,null) as? SecretKey) ?: run {
            val gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore")
            gen.init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build())
            gen.generateKey()
        }
    }
    fun encrypt(value:String):String {
        if(value.isBlank()) return ""
        val cipher=Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE,key)
        return Base64.encodeToString(cipher.iv+cipher.doFinal(value.toByteArray(StandardCharsets.UTF_8)),Base64.NO_WRAP)
    }
    fun decrypt(value:String):String {
        if(value.isBlank()) return ""
        return try {
            val raw=Base64.decode(value,Base64.NO_WRAP); require(raw.size>12)
            val cipher=Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE,key,GCMParameterSpec(128,raw.copyOfRange(0,12)))
            String(cipher.doFinal(raw.copyOfRange(12,raw.size)),StandardCharsets.UTF_8)
        } catch(_:Exception) { "" }
    }
}

private class LocalDb(context:Context):SQLiteOpenHelper(context.applicationContext,"kira_local_core.db",null,1) {
    override fun onCreate(db:SQLiteDatabase) {
        db.execSQL("CREATE TABLE providers(id TEXT PRIMARY KEY,model TEXT NOT NULL,base_url TEXT NOT NULL,encrypted_key TEXT NOT NULL DEFAULT '',enabled INTEGER NOT NULL DEFAULT 0,priority INTEGER NOT NULL DEFAULT 0)")
        db.execSQL("CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,character_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,route TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL)")
        db.execSQL("CREATE INDEX idx_messages_character ON messages(character_id,id)")
        db.execSQL("CREATE TABLE memories(id INTEGER PRIMARY KEY AUTOINCREMENT,character_id TEXT NOT NULL,text TEXT NOT NULL,created_at INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE skills(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,description TEXT NOT NULL DEFAULT '',character_id TEXT NOT NULL DEFAULT 'global',enabled INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL)")
        val defaults=listOf(
            arrayOf("openrouter","openai/gpt-4o-mini","https://openrouter.ai/api/v1"),
            arrayOf("groq","openai/gpt-oss-120b","https://api.groq.com/openai/v1"),
            arrayOf("mistral","mistral-small-latest","https://api.mistral.ai/v1"),
            arrayOf("deepseek","deepseek-chat","https://api.deepseek.com"),
            arrayOf("gemini","gemini-2.5-flash","https://generativelanguage.googleapis.com/v1beta")
        )
        defaults.forEachIndexed { i,row ->
            db.execSQL("INSERT INTO providers(id,model,base_url,priority) VALUES(?,?,?,?)",arrayOf<Any>(row[0],row[1],row[2],i))
        }
    }
    override fun onUpgrade(db:SQLiteDatabase,oldVersion:Int,newVersion:Int)=Unit
}

/** Independent on-device Core. API keys are encrypted with Android Keystore. */
class LocalKiraCore(context:Context) {
    private val app=context.applicationContext
    private val db=LocalDb(app).writableDatabase
    private val vault=LocalKeyVault()

    init {
        val root=java.io.File(app.filesDir,"kira")
        listOf(root,java.io.File(root,"library"),java.io.File(root,"skills")).forEach {
            if(!it.exists() && !it.mkdirs()) throw IllegalStateException("ساخت پوشه محلی Kira ناموفق بود: "+it.name)
        }
    }

    @Synchronized fun providers():List<LocalProvider> {
        val out=mutableListOf<LocalProvider>()
        db.rawQuery("SELECT id,model,base_url,enabled,priority,encrypted_key FROM providers ORDER BY priority,id",null).use { c ->
            while(c.moveToNext()) out+=LocalProvider(c.getString(0),c.getString(1),c.getString(2),c.getInt(3)!=0,c.getInt(4),c.getString(5).isNotBlank())
        }
        return out
    }

    @Synchronized fun saveProvider(id:String,model:String,baseUrl:String,apiKey:String,enabled:Boolean=true) {
        val pid=id.trim().lowercase()
        require(pid.matches(Regex("[a-z0-9][a-z0-9_-]{1,39}"))) { "شناسه Provider معتبر نیست." }
        require(model.isNotBlank()) { "Model ID را وارد کن." }
        require(baseUrl.startsWith("https://")) { "آدرس Provider باید HTTPS باشد." }
        val old=db.rawQuery("SELECT encrypted_key FROM providers WHERE id=?",arrayOf(pid)).use { if(it.moveToFirst()) vault.decrypt(it.getString(0)) else "" }
        val priority=providers().indexOfFirst { it.id==pid }.let { if(it<0) providers().size else it }
        val values=ContentValues().apply {
            put("id",pid); put("model",model.trim()); put("base_url",baseUrl.trim().trimEnd('/'))
            put("encrypted_key",vault.encrypt(apiKey.trim().ifBlank { old }))
            put("enabled",if(enabled) 1 else 0); put("priority",priority)
        }
        db.insertWithOnConflict("providers",null,values,SQLiteDatabase.CONFLICT_REPLACE)
    }

    @Synchronized fun setProviderEnabled(id:String,enabled:Boolean) {
        db.execSQL("UPDATE providers SET enabled=? WHERE id=?",arrayOf<Any>(if(enabled) 1 else 0,id))
    }
    @Synchronized fun moveProvider(id:String,delta:Int) {
        val rows=providers().toMutableList(); val i=rows.indexOfFirst { it.id==id }; if(i<0) return
        val target=(i+delta).coerceIn(0,rows.lastIndex); if(target==i) return
        val item=rows.removeAt(i); rows.add(target,item); db.beginTransaction()
        try { rows.forEachIndexed { index,p -> db.execSQL("UPDATE providers SET priority=? WHERE id=?",arrayOf<Any>(index,p.id)) }; db.setTransactionSuccessful() }
        finally { db.endTransaction() }
    }

    @Synchronized fun history(characterId:String,limit:Int=100):List<LocalChatMessage> {
        val out=mutableListOf<LocalChatMessage>()
        db.rawQuery("SELECT id,role,content,route,created_at FROM (SELECT * FROM messages WHERE character_id=? ORDER BY id DESC LIMIT ?) ORDER BY id ASC",arrayOf(characterId,limit.coerceIn(1,500).toString())).use { c ->
            while(c.moveToNext()) out+=LocalChatMessage(c.getLong(0),c.getString(1),c.getString(2),c.getString(3),c.getLong(4))
        }
        return out
    }
    @Synchronized fun clearHistory(characterId:String) { db.delete("messages","character_id=?",arrayOf(characterId)) }
    @Synchronized fun addMemory(characterId:String,text:String) {
        require(text.isNotBlank())
        db.execSQL("INSERT INTO memories(character_id,text,created_at) VALUES(?,?,?)",arrayOf<Any>(characterId,text.trim(),System.currentTimeMillis()))
    }
    @Synchronized fun memories(characterId:String):List<Pair<Long,String>> {
        val out=mutableListOf<Pair<Long,String>>()
        db.rawQuery("SELECT id,text FROM memories WHERE character_id=? OR character_id='global' ORDER BY id DESC",arrayOf(characterId)).use { c -> while(c.moveToNext()) out+=c.getLong(0) to c.getString(1) }
        return out
    }
    @Synchronized fun deleteMemory(id:Long) { db.delete("memories","id=?",arrayOf(id.toString())) }
    fun libraryDirectory()=java.io.File(app.filesDir,"kira/library").absolutePath
    fun installedSkills():List<String> = java.io.File(app.filesDir,"kira/library").listFiles()?.filter { it.isDirectory }?.map { it.name }?.sorted().orEmpty()

    @Synchronized fun sendMessage(characterId:String,text:String):LocalChatReply {
        require(text.isNotBlank()) { "پیام خالی است." }
        db.execSQL("INSERT INTO messages(character_id,role,content,route,created_at) VALUES(?,?,?,?,?)",arrayOf<Any>(characterId,"user",text.trim(),"",System.currentTimeMillis()))
        val active=providers().filter { it.enabled && it.hasKey }
        if(active.isEmpty()) throw IllegalStateException("هیچ Provider فعالی با API Key ذخیره‌شده وجود ندارد. از بخش Route یک کلید اضافه کن.")
        val errors=mutableListOf<String>()
        for(p in active) {
            try {
                val key=readKey(p.id)
                val answer=if(p.id=="gemini") callGemini(p,key,characterId) else callOpenAi(p,key,characterId)
                db.execSQL("INSERT INTO messages(character_id,role,content,route,created_at) VALUES(?,?,?,?,?)",arrayOf<Any>(characterId,"assistant",answer,p.id+" · "+p.model,System.currentTimeMillis()))
                return LocalChatReply(answer,p.id,p.model)
            } catch(e:Exception) { errors.add(p.id+": "+(e.message ?: "request failed").take(220)) }
        }
        throw IllegalStateException("همه Routeهای فعال ناموفق شدند:\n"+errors.joinToString("\n"))
    }

    private fun readKey(id:String):String {
        val encrypted=db.rawQuery("SELECT encrypted_key FROM providers WHERE id=?",arrayOf(id)).use { if(it.moveToFirst()) it.getString(0) else "" }
        val key=vault.decrypt(encrypted)
        if(key.isBlank()) throw IllegalStateException("API Key برای "+id+" ذخیره نشده است.")
        return key
    }
    private fun systemPrompt(characterId:String):String {
        val memory=memories(characterId).take(12).joinToString("\n") { it.second }
        val persona=when(characterId) {
            "ren" -> "Ren is analytical, calm, observant, slightly teasing and protective."
            "mika" -> "Mika is bright, playful, curious, expressive and supportive."
            else -> "Kira is confident, witty, loyal, anime-inspired and technically capable."
        }
        return "You are Kira, an anime-style AI companion. Speak naturally in Persian unless the user uses another language. Be concise, useful and honest. Never claim to use tools unless you did. "+persona+if(memory.isBlank()) "" else "\nRelevant local memories:\n"+memory
    }
    private fun chatMessages(characterId:String):JSONArray {
        val arr=JSONArray().put(JSONObject().put("role","system").put("content",systemPrompt(characterId)))
        history(characterId,18).forEach { arr.put(JSONObject().put("role",if(it.role=="assistant") "assistant" else "user").put("content",it.content)) }
        return arr
    }
    private fun callOpenAi(p:LocalProvider,key:String,characterId:String):String {
        val body=JSONObject().put("model",p.model).put("messages",chatMessages(characterId)).put("temperature",0.75)
        val response=request(p.baseUrl.trimEnd('/')+"/chat/completions",key,body,p.id)
        val choices=response.optJSONArray("choices") ?: throw IllegalStateException("پاسخ Provider فیلد choices ندارد.")
        val content=choices.optJSONObject(0)?.optJSONObject("message")?.opt("content")
        val answer=when(content) {
            is String -> content
            is JSONArray -> (0 until content.length()).mapNotNull { content.optJSONObject(it)?.optString("text") }.joinToString("\n")
            else -> ""
        }.trim()
        if(answer.isBlank()) throw IllegalStateException("Provider پاسخ متنی برنگرداند.")
        return answer
    }
    private fun callGemini(p:LocalProvider,key:String,characterId:String):String {
        val endpoint=p.baseUrl.trimEnd('/')+"/models/"+URLEncoder.encode(p.model,"UTF-8")+":generateContent?key="+URLEncoder.encode(key,"UTF-8")
        val contents=JSONArray()
        history(characterId,18).forEach { contents.put(JSONObject().put("role",if(it.role=="assistant") "model" else "user").put("parts",JSONArray().put(JSONObject().put("text",it.content)))) }
        val body=JSONObject().put("systemInstruction",JSONObject().put("parts",JSONArray().put(JSONObject().put("text",systemPrompt(characterId)))))
            .put("contents",contents).put("generationConfig",JSONObject().put("temperature",0.75))
        val response=request(endpoint,"",body,"gemini")
        val parts=response.optJSONArray("candidates")?.optJSONObject(0)?.optJSONObject("content")?.optJSONArray("parts") ?: JSONArray()
        val answer=(0 until parts.length()).mapNotNull { parts.optJSONObject(it)?.optString("text") }.filter { it.isNotBlank() }.joinToString("\n").trim()
        if(answer.isBlank()) throw IllegalStateException("Gemini پاسخ متنی برنگرداند.")
        return answer
    }
    private fun request(url:String,key:String,body:JSONObject,provider:String):JSONObject {
        val conn=URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod="POST"; conn.connectTimeout=15000; conn.readTimeout=90000; conn.doOutput=true
            conn.setRequestProperty("Content-Type","application/json"); conn.setRequestProperty("Accept","application/json")
            if(key.isNotBlank()) conn.setRequestProperty("Authorization","Bearer "+key)
            if(provider=="openrouter") { conn.setRequestProperty("HTTP-Referer","https://github.com/alizesta/Kira"); conn.setRequestProperty("X-Title","Kira") }
            conn.outputStream.use { it.write(body.toString().toByteArray(StandardCharsets.UTF_8)) }
            val code=conn.responseCode; val stream=if(code in 200..299) conn.inputStream else conn.errorStream
            val raw=stream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() }.orEmpty()
            if(code !in 200..299) {
                val detail=runCatching { JSONObject(raw).optJSONObject("error")?.optString("message") }.getOrNull().orEmpty()
                throw IllegalStateException("HTTP "+code+" "+detail.take(250))
            }
            return JSONObject(raw)
        } finally { conn.disconnect() }
    }
}
