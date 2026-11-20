from __future__ import annotations

from kira.ui.pages._all_pages_fluid_finalizers import finalize_voice_page


class VoicePage:
    """Responsive Voice page applying fluid layout finalization."""

    def __init__(self, parent=None) -> None:
        self.parent = parent
        finalize_voice_page(self)
