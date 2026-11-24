"""Small, Qt-free identity helper for the companion chat preview."""


def session_marker(session):
    """Return a stable per-conversation marker, including for legacy Session objects."""
    marker = getattr(session, "session_id", None)
    if marker is not None:
        return marker
    return (
        getattr(session, "cid", None),
        getattr(session, "conversation_id", None),
    )
