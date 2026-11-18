"""Shared policy for deciding which messages may teach long-term state."""


def should_observe_message(role: str, status: str | None, observe: bool = True) -> bool:
    """Observe user turns normally; only complete assistant replies may teach memory/mood."""
    if not observe:
        return False
    if str(role or "").strip().lower() != "assistant":
        return True
    return str(status or "complete").strip().lower() == "complete"


def should_observe_assistant_message(status: str | None) -> bool:
    """Backward-compatible assistant-only predicate."""
    return should_observe_message("assistant", status)


def stream_speech_action(status: str, speech_live: bool) -> str:
    """Return the one valid audio action after a streamed response reaches a terminal state."""
    status = str(status or "").strip().lower()
    if not speech_live:
        return "speak" if status == "complete" else "none"
    if status == "cancelled":
        return "stop"
    if status in ("complete", "interrupted", "failed"):
        return "end"
    return "none"
