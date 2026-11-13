"""Minimal line icons, painted with QPainter (no image files, no extra dependencies).

make_icon(name) returns a QIcon with colours for normal / hover / checked / disabled states,
so every icon button in the application shares one visual style.
"""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QBrush

_SIZE = 96            # pixmap size; icons are designed on a 24 x 24 grid and shown smaller
_CACHE = {}


def _poly(points):
    p = QPainterPath()
    p.moveTo(*points[0])
    for pt in points[1:]:
        p.lineTo(*pt)
    return p


def _shapes(name):
    """[(QPainterPath, filled)] in 24x24 grid coordinates."""
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
    pm = QPixmap(_SIZE, _SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(_SIZE / 24.0, _SIZE / 24.0)
    pen = QPen(QColor(colour), 1.9)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    for path, filled in _shapes(name):
        p.setPen(pen)
        p.setBrush(QBrush(QColor(colour)) if filled else Qt.NoBrush)
        p.drawPath(path)
    p.end()
    return pm


def make_icon(name, normal="#9aa0b8", hover="#ffffff", checked="#b9a7ff", disabled="#555a70"):
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
