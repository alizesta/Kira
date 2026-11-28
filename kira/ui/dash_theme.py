"""Per-character colours of the dashboard skin.

The skin (chat_shell.py, dashboard_chat.py) is written in Kira's violet. Another character gets the same layout in its own colours:
violet hues turn into the character's main hue and the cyan accents into its second hue. Everything that carries a colour goes through
tone() / css() / set_icon() / set_pixmap() / set_style(), so retheme() can repaint the page when the character changes.
"""
from __future__ import annotations

import colorsys
import json
import re

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon

from ..ui_icons import make_icon

# main: hue (degrees) that replaces violet; second: hue that replaces cyan; ticks: colour of the double tick
PALETTES = {
    "ren": {"main": 354.0, "second": 146.0, "ticks": "#35d07f"},
}
_STATE = {"cid": "kira"}
_HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
_RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)")


def set_character(cid: str) -> None:
    _STATE["cid"] = str(cid or "kira")


def character() -> str:
    return _STATE["cid"]


def palette() -> dict | None:
    return PALETTES.get(_STATE["cid"])


def _shift(r: int, g: int, b: int) -> tuple[int, int, int]:
    pal = palette()
    if pal is None:
        return r, g, b
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    deg = h * 360
    if s < 0.12:                                           # greys and whites stay as they are
        return r, g, b
    if 230 <= deg <= 310:
        h = pal["main"] / 360
    elif 160 <= deg <= 210:
        h = pal["second"] / 360
    else:
        return r, g, b
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    return round(nr * 255), round(ng * 255), round(nb * 255)


def tone(value: str) -> str:
    """One #rrggbb colour of the skin, in the active character's palette."""
    match = _HEX.fullmatch(str(value or "").strip())
    if not match or palette() is None:
        return value
    raw = match.group(1)
    r, g, b = _shift(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    return "#%02x%02x%02x" % (r, g, b)


def ticks_colour(default: str) -> str:
    pal = palette()
    return pal["ticks"] if pal else default


def second(value: str) -> QColor:
    """A colour that is the character's second accent: Ren's market green, otherwise the usual tone."""
    pal = palette()
    return QColor(pal["ticks"]) if pal else QColor(value)


def rgba(r: int, g: int, b: int, a: int = 255) -> QColor:
    """An (r, g, b, alpha) colour of the skin in the active character's palette (the dark fades under the pictures)."""
    r, g, b = _shift(r, g, b)
    return QColor(r, g, b, a)


def qcolor(value: str) -> QColor:
    return QColor(tone(value))


def css(text: str) -> str:
    """Recolour every hex / rgb() / rgba() colour of a stylesheet or HTML snippet."""
    if palette() is None:
        return text

    def hex_repl(m):
        return tone(m.group(0))

    def rgba_repl(m):
        r, g, b = _shift(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        alpha = m.group(4)
        return f"rgba({r}, {g}, {b}, {alpha})" if alpha is not None else f"rgb({r}, {g}, {b})"

    return _RGBA.sub(rgba_repl, _HEX.sub(hex_repl, text))


# ---- widgets that remember how they were painted, so retheme() can paint them again

def _paint_icon(widget) -> None:
    spec = widget.property("dashIconSpec")
    if not spec:
        return
    name, colours, size, as_pixmap = json.loads(str(spec))
    icon = make_icon(name, **{key: tone(value) for key, value in colours.items()})
    if as_pixmap:
        widget.setPixmap(icon.pixmap(size, size))
    else:
        widget.setIcon(icon)


def set_icon(widget, name: str, size: int | None = None, **colours) -> None:
    widget.setProperty("dashIconSpec", json.dumps([name, dict(colours), size or 0, False]))
    _paint_icon(widget)
    if size:
        widget.setIconSize(QSize(size, size))


def set_pixmap(label, name: str, size: int, **colours) -> None:
    label.setProperty("dashIconSpec", json.dumps([name, dict(colours), size, True]))
    _paint_icon(label)


def set_style(widget, sheet: str) -> None:
    widget.setProperty("dashCss", sheet)
    widget.setStyleSheet(css(sheet))


def retheme(page) -> None:
    """Repaint every icon and inline style of the page for the active character."""
    from PySide6.QtWidgets import QWidget
    for widget in page.findChildren(QWidget):
        if widget.property("dashIconSpec"):
            _paint_icon(widget)
        sheet = widget.property("dashCss")
        if sheet:
            widget.setStyleSheet(css(str(sheet)))
