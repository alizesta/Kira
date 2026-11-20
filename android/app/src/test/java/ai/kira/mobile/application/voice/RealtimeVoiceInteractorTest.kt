package ai.kira.mobile.application.voice

import ai.kira.mobile.domain.repository.RealtimeVoiceSession
import ai.kira.mobile.domain.repository.RealtimeVoiceSessionFactory
import ai.kira.mobile.domain.repository.VoiceCredentialRepository
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RealtimeVoiceInteractorTest {
    @Test
    fun managesCredentialAndFullDuplexSessionLifecycle() {
        val credentials = FakeCredentials()
        val factory = FakeSessionFactory()
        val service = RealtimeVoiceInteractor(credentials, factory)
        val events = mutableListOf<String>()

        service.saveApiKey(" live-key ")
        assertTrue(service.hasApiKey())
        service.start(onStatus = { events.add(it) }, onTranscript = { speaker, text -> events.add(speaker + ":" + text) })

        assertEquals(VoiceCallState.Connected, service.state)
        assertEquals("live-key", factory.lastApiKey)
        factory.session.emitStatus("میکروفون بی‌صداست.")
        assertEquals(VoiceCallState.Muted, service.state)

        service.setMuted(false)
        assertEquals(VoiceCallState.Connected, service.state)
        factory.session.emitTranscript("Kira", "سلام")
        assertTrue(events.contains("Kira:سلام"))

        service.stop()
        assertEquals(VoiceCallState.Idle, service.state)
        assertTrue(factory.session.stopped)
    }

    @Test
    fun providerFailureAllowsRetryAndClearsActiveState() {
        val factory = FakeSessionFactory()
        val service = RealtimeVoiceInteractor(FakeCredentials(), factory)
        service.start(onStatus = {}, onTranscript = { _, _ -> })

        factory.session.emitStatus("اتصال صوتی قطع شد: شبکه")
        assertTrue(service.state is VoiceCallState.Failed)
        assertFalse(service.isActive())

        service.start(onStatus = {}, onTranscript = { _, _ -> })
        assertEquals(2, factory.createdSessions)
    }

    @Test(expected = IllegalStateException::class)
    fun cannotDeleteCredentialDuringActiveCall() {
        val service = RealtimeVoiceInteractor(FakeCredentials(), FakeSessionFactory())
        service.start(onStatus = {}, onTranscript = { _, _ -> })
        service.clearApiKey()
    }

    private class FakeCredentials : VoiceCredentialRepository {
        private var value = "live-key"
        override fun hasApiKey(): Boolean = value.isNotBlank()
        override fun saveApiKey(value: String) { this.value = value }
        override fun readApiKey(): String = value
        override fun clearApiKey() { value = "" }
    }

    private class FakeSessionFactory : RealtimeVoiceSessionFactory {
        var lastApiKey = ""
        var createdSessions = 0
        lateinit var session: FakeSession

        override fun create(
            apiKey: String,
            onStatus: (String) -> Unit,
            onTranscript: (speaker: String, text: String) -> Unit
        ): RealtimeVoiceSession {
            lastApiKey = apiKey
            createdSessions += 1
            return FakeSession(onStatus, onTranscript).also { session = it }
        }
    }

    private class FakeSession(
        private val onStatus: (String) -> Unit,
        private val onTranscript: (String, String) -> Unit
    ) : RealtimeVoiceSession {
        var stopped = false
        private var muted = false

        override fun start() { onStatus("تماس زنده برقرار شد؛ صحبت کن.") }
        override fun setMuted(value: Boolean) {
            muted = value
            onStatus(if (value) "میکروفون بی‌صداست." else "تماس زنده است؛ می‌توانی صحبت کنی.")
        }
        override fun isMuted(): Boolean = muted
        override fun stop() {
            stopped = true
            onStatus("تماس صوتی پایان یافت.")
        }
        fun emitStatus(value: String) = onStatus(value)
        fun emitTranscript(speaker: String, text: String) = onTranscript(speaker, text)
    }
}
