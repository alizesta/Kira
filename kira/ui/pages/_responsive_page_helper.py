from __future__ import annotations

from kira.ui.responsive_layout import configure_fluid_layout_on_widget, wrap_in_responsive_scroll


def normalize_page_widget(page_widget):
    """Apply Jakob-familiar fluid sizing and safe scroll containment to a page widget."""
    configure_fluid_layout_on_widget(page_widget)
    return wrap_in_responsive_scroll(page_widget, parent=page_widget.parent())
