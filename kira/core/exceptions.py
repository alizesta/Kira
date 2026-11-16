"""Stable application-level exceptions shared across feature boundaries."""


class ChatHistoryError(RuntimeError):
    """A chat-history operation failed without silently discarding saved data."""
