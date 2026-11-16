"""Minimal line icons, painted with QPainter (no image files, no extra dependencies).

make_icon(name) returns a QIcon with colours for normal / hover / checked / disabled states,
so every icon button in the application shares one visual style.
"""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QBrush

_SIZE = 96            # pixmap size; icons are designed on a 24 x 24 grid and shown smaller
_CACHE = {}
_GLOW_INTENSITY = 0.58


def set_glow_intensity(value):
    """Set the subtle icon bloom level (0..1) and rebuild cached glyphs."""
    global _GLOW_INTENSITY
    level = max(0.0, min(1.0, float(value)))
    if abs(level - _GLOW_INTENSITY) > 0.001:
        _GLOW_INTENSITY = level
        _CACHE.clear()



def _poly(points):
    p = QPainterPath()
    p.moveTo(*points[0])
    for pt in points[1:]:
        p.lineTo(*pt)
    return p



def _emotion_shapes(name):
    """Vector face glyphs for Kira's mood chip; chat-message emoji are deliberately untouched."""
    name = str(name or "neutral").removeprefix("emotion_")
    face = QPainterPath()
    face.addEllipse(QRectF(3.0, 3.0, 18.0, 18.0))
    shapes = [(face, False)]

    def curve(start, control1, control2, end):
        path = QPainterPath()
        path.moveTo(*start)
        path.cubicTo(*control1, *control2, *end)
        return path

    def line(*points):
        return _poly(points)

    def dot(x, y, rx=1.0, ry=None):
        path = QPainterPath()
        path.addEllipse(QPointF(x, y), rx, rx if ry is None else ry)
        return path

    def heart(cx, cy, scale=1.0):
        path = QPainterPath()
        path.moveTo(cx, cy + 2.2 * scale)
        path.cubicTo(cx - 4.8 * scale, cy - 0.8 * scale, cx - 2.2 * scale, cy - 4.0 * scale,
                     cx, cy - 1.8 * scale)
        path.cubicTo(cx + 2.2 * scale, cy - 4.0 * scale, cx + 4.8 * scale, cy - 0.8 * scale,
                     cx, cy + 2.2 * scale)
        return path

    happy = {"happy", "excited", "laughing", "hopeful", "grateful"}
    soft = {"affectionate", "flirty", "shy", "embarrassed", "content"}
    sad = {"sad", "disappointed", "lonely", "guilty", "nostalgic"}
    angry = {"angry", "frustrated", "tsundere", "jealous", "annoyed"}
    curious = {"curious", "thinking", "confused", "surprised"}
    playful = {"playful", "teasing", "smug", "arrogant", "proud", "confident"}
    if name not in happy | soft | sad | angry | curious | playful | {"neutral", "calm", "bored", "fearful", "disgusted", "protective", "relieved"}:
        name = "neutral"

    if name in happy:
        shapes += [(curve((7.0, 10.2), (7.8, 8.7), (9.4, 8.7), (10.2, 10.2)), False),
                   (curve((13.8, 10.2), (14.6, 8.7), (16.2, 8.7), (17.0, 10.2)), False),
                   (curve((7.8, 13.4), (9.2, 18.0), (14.8, 18.0), (16.2, 13.4)), False)]
        if name in {"excited", "hopeful", "grateful"}:
            shapes += [(line((4.0, 6.2), (2.2, 5.0)), False), (line((20.0, 6.2), (21.8, 5.0)), False)]
        if name == "laughing":
            shapes += [(line((8.2, 10.0), (9.5, 10.0)), False), (line((14.5, 10.0), (15.8, 10.0)), False)]
    elif name in soft:
        shapes += [(curve((7.1, 10.1), (8.0, 8.9), (9.1, 8.9), (10.0, 10.1)), False),
                   (dot(15.4, 9.8, 1.05), True),
                   (curve((8.5, 14.0), (10.2, 16.8), (13.7, 16.8), (15.5, 13.8)), False),
                   (dot(6.2, 13.0, 0.75, 0.45), True), (dot(17.8, 13.0, 0.75, 0.45), True)]
        if name in {"affectionate", "flirty"}:
            shapes += [(heart(5.0, 5.0, 0.55), False), (heart(19.0, 5.0, 0.55), False)]
        elif name in {"shy", "embarrassed"}:
            shapes += [(line((7.2, 7.0), (9.5, 7.8)), False), (line((14.5, 7.8), (16.8, 7.0)), False)]
    elif name in sad:
        shapes += [(dot(8.4, 9.8, 1.05), True), (dot(15.6, 9.8, 1.05), True),
                   (curve((8.0, 16.2), (10.0, 12.5), (14.0, 12.5), (16.0, 16.2)), False)]
        if name in {"sad", "lonely", "nostalgic"}:
            shapes += [(curve((6.0, 11.2), (5.0, 13.0), (5.4, 14.1), (6.4, 14.8)), False)]
    elif name in angry:
        shapes += [(line((6.8, 8.0), (10.1, 9.0)), False), (line((13.9, 9.0), (17.2, 8.0)), False),
                   (dot(8.8, 10.4, 0.85), True), (dot(15.2, 10.4, 0.85), True),
                   (curve((8.0, 16.5), (10.0, 13.2), (14.0, 13.2), (16.0, 16.5)), False)]
    elif name == "fearful":
        shapes += [(dot(8.4, 9.7, 1.65), False), (dot(15.6, 9.7, 1.65), False),
                   (dot(8.4, 9.7, 0.65), True), (dot(15.6, 9.7, 0.65), True),
                   (dot(12.0, 15.4, 1.55, 1.9), False)]
    elif name == "disgusted":
        shapes += [(line((7.0, 8.1), (10.2, 8.7)), False), (line((14.2, 8.2), (17.0, 7.3)), False),
                   (line((7.5, 10.2), (10.0, 10.2)), False), (dot(15.4, 10.1, 0.9), True),
                   (curve((8.2, 15.0), (10.1, 13.7), (13.6, 17.0), (16.1, 14.4)), False)]
    elif name in curious:
        shapes += [(dot(8.4, 9.8, 1.35), False), (dot(15.6, 9.8, 1.0), True),
                   (line((7.0, 7.2), (10.0, 6.4)), False),
                   (curve((9.3, 15.0), (10.2, 13.5), (13.8, 13.5), (14.7, 15.0)), False)]
        if name == "surprised":
            shapes[-1] = (dot(12.0, 15.0, 1.5, 1.8), False)
    elif name in playful:
        shapes += [(curve((7.0, 10.1), (7.8, 8.6), (9.5, 8.6), (10.2, 10.1)), False),
                   (line((14.0, 9.8), (17.0, 9.1)), False),
                   (curve((8.0, 14.0), (10.8, 17.4), (14.0, 17.2), (16.2, 13.0)), False)]
        if name in {"proud", "confident", "smug", "arrogant"}:
            shapes += [(line((14.0, 7.1), (17.0, 6.0)), False)]
    else:
        shapes += [(dot(8.4, 10.0, 0.9), True), (dot(15.6, 10.0, 0.9), True)]
        if name == "bored":
            shapes += [(line((8.5, 15.0), (15.5, 15.0)), False)]
        elif name == "protective":
            shapes += [(curve((8.0, 14.5), (9.5, 17.0), (14.5, 17.0), (16.0, 14.5)), False)]
        elif name == "relieved":
            shapes += [(curve((8.0, 14.0), (10.0, 16.0), (14.0, 16.0), (16.0, 14.0)), False)]
        else:
            shapes += [(line((9.0, 15.0), (15.0, 15.0)), False)]
    return shapes


def _shapes(name):
    """[(QPainterPath, filled)] in 24x24 grid coordinates."""
    if str(name).startswith("emotion_"):
        return _emotion_shapes(name)
    if name == "chat":
        bubble = QPainterPath()
        bubble.addRoundedRect(QRectF(3, 4, 18, 13), 4, 4)
        return [(bubble, False), (_poly([(8, 17), (7, 21), (12.5, 17)]), False)]
    if name == "route":
        nodes = QPainterPath()
        for cx, cy in ((5, 6), (5, 18), (19, 12)):
            nodes.addEllipse(QPointF(cx, cy), 2.2, 2.2)
        return [(nodes, False), (_poly([(7.2, 6), (12, 6), (12, 12), (16.8, 12)]), False),
                (_poly([(7.2, 18), (12, 18), (12, 12)]), False)]
    if name == "menu":
        return [(_poly([(4, 7), (20, 7)]), False), (_poly([(4, 12), (20, 12)]), False), (_poly([(4, 17), (20, 17)]), False)]
    if name == "check":
        return [(_poly([(5, 12.5), (10, 17.5), (19, 7)]), False)]
    if name == "user":
        head = QPainterPath()
        head.addEllipse(QPointF(12, 8), 3.6, 3.6)
        body = QPainterPath()
        body.moveTo(5, 20)
        body.cubicTo(5, 13.5, 19, 13.5, 19, 20)
        return [(head, False), (body, False)]
    if name == "energy_bolt":
        return [(_poly([(13.5, 2.5), (5.8, 13.2), (10.8, 13.2), (9.6, 21.5),
                         (18.4, 9.6), (13.2, 9.6)]), False)]
    if name == "send":
        return [(_poly([(12, 19), (12, 6)]), False), (_poly([(6.5, 11.5), (12, 6), (17.5, 11.5)]), False)]
    if name == "mic":
        cap = QPainterPath()
        cap.addRoundedRect(QRectF(9, 3, 6, 11), 3, 3)
        arc = QPainterPath()
        arc.moveTo(6, 11)
        arc.cubicTo(6, 17.5, 18, 17.5, 18, 11)
        return [(cap, False), (arc, False), (_poly([(12, 16.5), (12, 20)]), False), (_poly([(9, 20), (15, 20)]), False)]
    if name == "moon":
        outer = QPainterPath()
        outer.addEllipse(QPointF(12, 12), 8, 8)
        cut = QPainterPath()
        cut.addEllipse(QPointF(16, 9), 7, 7)
        return [(outer.subtracted(cut), False)]
    if name == "speaker":
        cone = _poly([(4, 10), (8, 10), (13, 6), (13, 18), (8, 14), (4, 14)])
        cone.closeSubpath()
        w1 = QPainterPath()
        w1.moveTo(16, 9)
        w1.cubicTo(18, 11, 18, 13, 16, 15)
        w2 = QPainterPath()
        w2.moveTo(18.5, 6.5)
        w2.cubicTo(22, 10, 22, 14, 18.5, 17.5)
        return [(cone, False), (w1, False), (w2, False)]
    if name == "stop":
        sq = QPainterPath()
        sq.addRoundedRect(QRectF(7, 7, 10, 10), 2, 2)
        return [(sq, True)]
    if name == "chevron_up":
        return [(_poly([(6, 15), (12, 9), (18, 15)]), False)]
    return []


def _pixmap(name, colour):
    """Render a crisp neon glyph with a multi-pass bloom and a white-hot inner edge."""
    pm = QPixmap(_SIZE, _SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(_SIZE / 24.0, _SIZE / 24.0)
    base = QColor(colour)

    def glow_pen(alpha, width):
        shade = QColor(base)
        shade.setAlpha(max(0, min(255, round(alpha))))
        pen = QPen(shade, width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    intensity = max(0.0, min(1.0, _GLOW_INTENSITY))
    passes = (
        (14 + 42 * intensity, 6.8 + 1.0 * intensity),
        (24 + 62 * intensity, 4.4 + 0.7 * intensity),
        (38 + 82 * intensity, 2.8 + 0.4 * intensity),
    )
    core_colour = QColor(base)
    core_colour.setAlpha(242)
    core_pen = QPen(core_colour, 1.65)
    core_pen.setCapStyle(Qt.RoundCap)
    core_pen.setJoinStyle(Qt.RoundJoin)
    highlight = QColor(232, 250, 255, round(72 + 72 * intensity))
    highlight_pen = QPen(highlight, 0.48)
    highlight_pen.setCapStyle(Qt.RoundCap)
    highlight_pen.setJoinStyle(Qt.RoundJoin)

    for path, filled in _shapes(name):
        p.setBrush(Qt.NoBrush)
        for alpha, width in passes:
            p.setPen(glow_pen(alpha, width))
            p.drawPath(path)
        if filled:
            p.setPen(Qt.NoPen)
            fill = QColor(base)
            fill.setAlpha(248)
            p.setBrush(QBrush(fill))
            p.drawPath(path)
            p.setBrush(Qt.NoBrush)
            p.setPen(highlight_pen)
            p.drawPath(path)
        else:
            p.setPen(core_pen)
            p.drawPath(path)
            p.setPen(highlight_pen)
            p.drawPath(path)
    p.end()
    return pm


def make_icon(name, normal="#4FD8FF", hover="#FFFFFF", checked="#8F6BFF", disabled="#52617B"):
    key = (name, normal, hover, checked, disabled)
    icon = _CACHE.get(key)
    if icon is None:
        icon = QIcon()
        icon.addPixmap(_pixmap(name, normal), QIcon.Normal, QIcon.Off)
        icon.addPixmap(_pixmap(name, hover), QIcon.Active, QIcon.Off)
        icon.addPixmap(_pixmap(name, checked), QIcon.Normal, QIcon.On)
        icon.addPixmap(_pixmap(name, hover), QIcon.Active, QIcon.On)
        icon.addPixmap(_pixmap(name, disabled), QIcon.Disabled, QIcon.Off)
        icon.addPixmap(_pixmap(name, disabled), QIcon.Disabled, QIcon.On)
        _CACHE[key] = icon
    return icon
