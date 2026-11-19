package ai.kira.mobile.application.voice

sealed class VoiceCallState {
    data object Idle : VoiceCallState()
    data object Connecting : VoiceCallState()
    data object Connected : VoiceCallState()
    data object Muted : VoiceCallState()
    data class Failed(val reason: String) : VoiceCallState()
}

class VoiceCallStateMachine {
    var state: VoiceCallState = VoiceCallState.Idle
        private set

    fun begin() {
        check(state is VoiceCallState.Idle || state is VoiceCallState.Failed) {
            "Voice session is already active."
        }
        state = VoiceCallState.Connecting
    }

    fun connected() {
        check(state is VoiceCallState.Connecting) { "Voice session is not connecting." }
        state = VoiceCallState.Connected
    }

    fun setMuted(muted: Boolean) {
        check(state is VoiceCallState.Connected || state is VoiceCallState.Muted) {
            "Voice session is not connected."
        }
        state = if (muted) VoiceCallState.Muted else VoiceCallState.Connected
    }

    fun fail(reason: String) {
        state = VoiceCallState.Failed(reason.ifBlank { "Voice session failed." })
    }

    fun end() {
        state = VoiceCallState.Idle
    }
}
