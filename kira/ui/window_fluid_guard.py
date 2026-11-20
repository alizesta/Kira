from __future__ import annotations

from kira.ui.responsive_layout import apply_fluid_policy, configure_fluid_layout_on_widget


def apply_window_fluid_guard(window, min_width: int = 360, min_height: int = 320) -> None:
    """Ensure main window and central container adapt smoothly on resize without clipping."""
    window.setMinimumSize(min_width, min_height)
    central = window.centralWidget() if hasattr(window, "centralWidget") else None
    if central is not None:
        configure_fluid_layout_on_widget(central)
        apply_fluid_policy(central, min_w=0, min_h=0, expand_h=True)


def wire_main_window_fluid(window) -> None:
    """Wire fluid resizing rules into Kira main window and composition controllers."""
    apply_window_fluid_guard(window)
    for attr in ("composition_controller", "chat_controller"):
        ctrl = getattr(window, attr, None)
        if ctrl is not None:
            for w_attr in ("central_widget", "chat_panel", "composer", "header"):
                widget = getattr(ctrl, w_attr, None)
                if widget is not None:
                    configure_fluid_layout_on_widget(widget)
