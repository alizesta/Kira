"""SVG-only icon renderer for Kira's desktop UI.

Lucide assets and Kira-specific mood/stop SVGs are rendered through QtSvg.
The multi-pass neon bloom and make_icon/set_glow_intensity public API stay stable.

Mood faces: a mood with its own file (assets/icons/emotion_<mood>.svg) uses it; any other mood falls back to the
SVG of its family (_EMOTION_GROUPS), so a new mood never renders as an empty button.
"""
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QByteArray
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SIZE = 96
_CACHE = {}
_GLOW_INTENSITY = 0.58
_SVG_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"
_SVG_SOURCE = {}

_EMOTION_GROUPS = {
    "happy": "happy", "excited": "happy", "laughing": "happy", "hopeful": "happy", "grateful": "happy",
    "affectionate": "soft", "flirty": "soft", "shy": "soft", "embarrassed": "soft", "content": "soft",
    "sad": "sad", "disappointed": "sad", "lonely": "sad", "guilty": "sad", "nostalgic": "sad",
    "angry": "angry", "frustrated": "angry", "tsundere": "angry", "jealous": "angry", "annoyed": "angry",
    "curious": "curious", "thinking": "curious", "confused": "curious", "surprised": "curious",
    "playful": "playful", "teasing": "playful", "smug": "playful", "arrogant": "playful", "proud": "playful", "confident": "playful",
    "fearful": "fearful", "disgusted": "disgusted", "bored": "bored",
    "protective": "protective", "relieved": "relieved", "neutral": "neutral", "calm": "neutral",
}


def set_glow_intensity(value):
    """Set the subtle icon bloom level (0..1) and rebuild cached glyphs."""
    global _GLOW_INTENSITY
    level = max(0.0, min(1.0, float(value)))
    if abs(level - _GLOW_INTENSITY) > 0.001:
        _GLOW_INTENSITY = level
        _CACHE.clear()


def _asset_name(name):
    value = str(name or "help")
    if value.startswith("emotion_"):
        if (_SVG_DIR / f"{value}.svg").is_file():
            return value
        mood = value.removeprefix("emotion_")
        return "emotion_" + _EMOTION_GROUPS.get(mood, "neutral")
    return value


_CAT_HEAD = '<path d="M4.2 11.4V4.2c0-.8.9-1.1 1.4-.6l3.6 2.6c1.7-.5 3.7-.5 5.6 0l3.6-2.6c.5-.5 1.4-.2 1.4.6v7.2c0 4.5-3.3 8-7.8 8s-7.8-3.5-7.8-8z"/><path d="M6.2 8.4V5.4l2.2 1.5M17.8 8.4V5.4l-2.2 1.5" opacity=".7"/><path d="M12 6.7v1.7M10.1 7v1.2M13.9 7v1.2" opacity=".7"/><path d="M.9 11.6l3.3.8M.8 14.4l3.4-.2M1.4 17l3-.9M23.1 11.6l-3.3.8M23.2 14.4l-3.4-.2M22.6 17l-3-.9" opacity=".6"/>'


def _cat_face(source):
    """Mood faces are cat faces: the round head of the SVG becomes a head with two pointed ears (same eyes and mouth)."""
    # bigger, friendlier eyes than the plain round faces
    return "<!--thin-->" + source.replace('<circle cx="12" cy="12" r="9"/>', _CAT_HEAD, 1).replace('r=".8"', 'r="1.15"')


def _svg_text(name):
    """Read the SVG asset for an icon or mood group."""
    asset = _asset_name(name)
    if asset not in _SVG_SOURCE:
        path = _SVG_DIR / f"{asset}.svg"
        try:
            _SVG_SOURCE[asset] = path.read_text(encoding="utf-8") if path.is_file() else None
            if _SVG_SOURCE[asset] and asset.startswith("emotion_"):
                _SVG_SOURCE[asset] = _cat_face(_SVG_SOURCE[asset])
        except OSError:
            _SVG_SOURCE[asset] = None
    return _SVG_SOURCE[asset]


def _svg_pass(painter, source, colour, width, alpha):
    tint = QColor(colour)
    svg = (
        source.replace('stroke="currentColor"', f'stroke="{tint.name()}" stroke-opacity="{max(0.0, min(1.0, alpha / 255.0)):.3f}"')
        .replace('fill="currentColor"', f'fill="{tint.name()}" fill-opacity="{max(0.0, min(1.0, alpha / 255.0)):.3f}"')
        .replace('stroke-width="2"', f'stroke-width="{width:.2f}"')
    )
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, _SIZE, _SIZE))


def _svg_pixmap(source, colour):
    pm = QPixmap(_SIZE, _SIZE)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    intensity = max(0.0, min(1.0, _GLOW_INTENSITY))
    k = 0.58 if "<!--thin-->" in source else 1.0                  # detailed drawings (cat, bull) use finer lines
    for alpha, width in ((14 + 42 * intensity, 6.8 + intensity),
                         (24 + 62 * intensity, 4.4 + 0.7 * intensity),
                         (38 + 82 * intensity, 2.8 + 0.4 * intensity)):
        _svg_pass(painter, source, colour, width * k, alpha)
    _svg_pass(painter, source, colour, 1.75 * k, 242)
    _svg_pass(painter, source, QColor(232, 250, 255), 0.5 * k, 72 + 72 * intensity)
    painter.end()
    return pm


def _pixmap(name, colour):
    source = _svg_text(name)
    return _svg_pixmap(source, colour) if source else QPixmap()


def make_icon(name, normal="#4FD8FF", hover="#FFFFFF", checked="#8F6BFF", disabled="#52617B"):
    key = (name, normal, hover, checked, disabled)
    icon = _CACHE.get(key)
    if icon is None:
        icon = QIcon()
        states = (
            (_pixmap(name, normal), QIcon.Normal, QIcon.Off),
            (_pixmap(name, hover), QIcon.Active, QIcon.Off),
            (_pixmap(name, checked), QIcon.Normal, QIcon.On),
            (_pixmap(name, hover), QIcon.Active, QIcon.On),
            (_pixmap(name, disabled), QIcon.Disabled, QIcon.Off),
            (_pixmap(name, disabled), QIcon.Disabled, QIcon.On),
        )
        for pixmap, mode, state in states:
            if not pixmap.isNull():
                icon.addPixmap(pixmap, mode, state)
        _CACHE[key] = icon
    return icon
