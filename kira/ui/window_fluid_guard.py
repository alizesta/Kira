from __future__ import annotations

from kira.ui.responsive_layout import apply_fluid_policy, configure_fluid_layout_on_widget


def apply_window_fluid_guard(window, min_width: int = 360, min_height: int = 320) -> None:
    """Ensure main window and central container adapt smoothly on resize without clipping."""
    window.setMinimumSize(min_width, min_height)
    central = window.centralWidget() if hasattr(window, "centralWidget") else None
    if central is not None:
        configure_fluid_layout_on_widget(central)
        apply_fluid_policy(central, min_w=0, min_h=0, expand_h=True)
