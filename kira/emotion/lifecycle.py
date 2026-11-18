"""Shared policy for deciding which assistant messages may teach long-term state."""


def should_observe_assistant_message(status: str | None) -> bool:
    """Only complete assistant replies may update persona or emotional memory."""
    return str(status or "complete").strip().lower() == "complete"
