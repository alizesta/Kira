"""Kira face animation: blinking, expressions, talking mouth.

Everything is drawn as overlays on top of assets/kira_character.png.
Landmark coordinates are in the original image pixels (1024 x 1536).
If you replace the image, re-measure EYES, MOUTH and BLUSH below.
"""
import math
import random
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QObject, QTimer, QElapsedTimer, QRectF, QPointF, Signal
from PySide6.QtGui import (QCursor, QTransform, QPixmap, QPainter, QColor, QPen, QPainterPath,
                           QRadialGradient, QBrush, QFont, QImage)
from PySide6.QtWidgets import QWidget

from .rig import Rig, region_at
from . import avatar_art

IMG = Path(__file__).resolve().parent.parent / "assets" / "kira_character.png"

# Reference size of the character picture; all coordinates below use these pixels.
REF_W, REF_H = 832, 1248

# Landmarks in reference pixels. R / L are from the viewer's point of view.
EYES = [
    dict(c=(438, 106.5), hw=14, hh=7.5, ang=-20, skin=(236, 190, 186)),   # right eye
    dict(c=(388, 124), hw=12.5, hh=7.5, ang=-18, skin=(232, 184, 180)),   # left eye
]
MOUTH = dict(c=(424, 152), hw=12)
MOUTH_ANGLE = -14
BLUSH = [(446, 128), (394, 143)]
FACE_C = (412.0, 128.0)

# lid: eyelid closure 0..1 | raise: lower lid pushed up (smiling eyes)
# open: base mouth opening | blush: cheek colour 0..1
EXPRESSIONS = {
    "neutral":   dict(lid=0.00, raise_=0.00, open=0.00, blush=0.0),
    "happy":     dict(lid=0.30, raise_=0.22, open=0.00, blush=0.8),
    "sad":       dict(lid=0.30, raise_=0.00, open=0.00, blush=0.0),
    "surprised": dict(lid=0.00, raise_=0.00, open=0.62, blush=0.0),
    "thinking":  dict(lid=0.18, raise_=0.00, open=0.00, blush=0.0),
    "sleepy":    dict(lid=0.88, raise_=0.00, open=0.00, blush=0.15),
    "bored":     dict(lid=0.45, raise_=0.00, open=0.00, blush=0.0),
    "angry":     dict(lid=0.34, raise_=0.00, open=0.10, blush=0.35),
    "shy":       dict(lid=0.12, raise_=0.10, open=0.05, blush=1.0),
    "excited":   dict(lid=0.00, raise_=0.25, open=0.40, blush=0.6),
}

SMILE = {"neutral": 0.35, "happy": 1.0, "sad": -0.7, "surprised": 0.0, "thinking": 0.0, "sleepy": 0.15,
         "bored": -0.15, "angry": -0.5, "shy": 0.5, "excited": 1.0}
for _n, _d in EXPRESSIONS.items():
    _d.setdefault("smile", SMILE[_n])


class FaceAnimator(QObject):
    """Holds the animated state; any number of AvatarView widgets can draw it."""
    changed = Signal()
    mood_changed = Signal(str)
    gesture = Signal(str)                # body motion for the 3D (VRM) avatar: 'hop', 'wave', ... (kira/vrm_avatar.py)
    body = Signal(str)                   # chat-commanded body poses for the VRM avatar: JSON list of names (kira/body.py)
    art_changed = Signal()               # another character's picture (or Kira's own) is now shown

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pix = QPixmap(str(IMG))
        self.master = self.pix.toImage()
        # which picture is shown: Kira's animated PNG by default (face overlays on), or another character's art
        self._kira_art = (self.pix, self.master)
        self.art_serial = 0
        self.face_overlays = True
        self.body_enabled = False        # True once a VRM avatar is ready: the chat may then move the body (kira/body.py)
        self.kira_art_active = True      # False while another character's picture is shown (the VRM avatar is Kira's)
        self.motion_gain = 1.0
        self.full_rect = QRectF(0, 0, REF_W, REF_H)
        self.card_rect = QRectF(*avatar_art.KIRA_CARD)
        self.clip_rect = None
        self.window_ratio = None         # None = the companion window keeps its Kira proportions
        self.img_w, self.img_h = REF_W, REF_H
        self.rig = Rig()
        self.look_anchor = None          # callable -> QPoint (screen) the character "looks from"
        self.follow_strength = 1.0
        self._look = [0.0, 0.0]
        self.talking = 0.0
        self.last_touch = 0.0
        self.tile_cache = {}
        self.auto_bored = True
        self._yawn = 0.0
        self._next_yawn = 0.0
        self._build_tiles()
        if not self.pix.isNull():
            image = self.pix.toImage()
            for eye in EYES:
                _sample_skin(image, eye)
            MOUTH["skin"] = _median_skin(image, _mouth_ring(image.width() / REF_W), (232, 186, 176))
            MOUTH["lip"] = (212, 116, 112)
        self.cur = dict(EXPRESSIONS["neutral"])
        self.expr = "neutral"
        self.sleeping = False
        self.mouth = 0.0
        self._mouth_target = 0.0
        self.blink = 0.0
        self.t = 0.0
        self._blink_p = None
        self._next_blink = 2.0
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(lambda: self.set_expression("neutral"))
        self._clock = QElapsedTimer()
        self._clock.start()
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build_tiles(self, T=32):
        img = self.master.convertToFormat(QImage.Format_RGBA8888)
        w, h = img.width(), img.height()
        arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w, 3]
        kx, ky = w / REF_W, h / REF_H
        tiles = []
        for y0 in range(0, REF_H, T):
            for x0 in range(0, REF_W, T):
                x1, y1 = min(x0 + T, REF_W), min(y0 + T, REF_H)
                if arr[int(y0 * ky):int(y1 * ky) + 1, int(x0 * kx):int(x1 * kx) + 1].max() > 10:
                    tiles.append((x0, y0, x1, y1))
        self.tiles = tiles
        t = np.array(tiles, dtype=np.float64)
        self.tile_cx = (t[:, 0] + t[:, 2]) / 2
        self.tile_cy = (t[:, 1] + t[:, 3]) / 2

    def set_character_art(self, path=None):
        """Show a character's picture (path to an image file) or, with None / an unreadable file, Kira's own
        animated PNG. Only Kira's art gets the eyelid / mouth overlays: they are measured on her face."""
        image = QImage(str(path)) if path else QImage()
        if image.isNull():
            self.pix, self.master = self._kira_art
            self.face_overlays = True
            self.kira_art_active = True
            self.motion_gain = 1.0
            self.full_rect = QRectF(0, 0, REF_W, REF_H)
            self.card_rect = QRectF(*avatar_art.KIRA_CARD)
            self.clip_rect = None
            self.window_ratio = None
        else:
            lay = avatar_art.layout(image.width(), image.height())
            ax, ay, aw, ah = lay["art"]
            S = 2                                          # same 2x detail as Kira's 1664 x 2496 master
            canvas = QImage(REF_W * S, REF_H * S, QImage.Format_RGBA8888_Premultiplied)
            canvas.fill(0)
            art = scale_hq_image(image, max(1, round(aw * S)), max(1, round(ah * S)))
            q = QPainter(canvas)
            q.drawImage(round(ax * S), round(ay * S), art)
            q.end()
            self.master = canvas
            self.pix = QPixmap.fromImage(canvas)
            self.face_overlays = False
            self.kira_art_active = False
            self.motion_gain = 0.55                        # gentler sway: the rig regions are measured on Kira
            self.clip_rect = QRectF(*lay["content"])
            self.full_rect = QRectF(*lay["content"])
            self.card_rect = QRectF(*lay["card"])
            self.window_ratio = lay["window_ratio"]
        self._build_tiles()
        self.tile_cache.clear()
        self.art_serial += 1
        self.art_changed.emit()
        self.changed.emit()

    # ---- public API -------------------------------------------------
    def set_expression(self, name, hold=None):
        self.expr = name if name in EXPRESSIONS else "neutral"
        self.mood_changed.emit(self.expr)
        self._hold.stop()
        if hold and self.expr != "neutral":
            self._hold.start(int(hold * 1000))

    def touch(self):
        """Call on any user interaction (resets boredom)."""
        self.last_touch = self.t
        if self.expr == "bored":
            self.set_expression("neutral")

    def yawn(self):
        self._yawn = 2.0

    def set_sleeping(self, value):
        self.sleeping = bool(value)

    def set_mouth_target(self, level):
        self._mouth_target = max(0.0, min(1.0, float(level)))

    @property
    def yawn_amount(self):
        return math.sin(math.pi * max(0.0, min(1.0, 1 - self._yawn / 2.0))) if self._yawn > 0 else 0.0

    @property
    def lid(self):
        lid = 1 - (1 - self.cur["lid"]) * (1 - self.blink)
        return max(lid, self.yawn_amount * 0.85)

    # ---- internals --------------------------------------------------
    def _tick(self):
        now = self._clock.elapsed() / 1000.0
        dt = min(now - self._last, 0.1)
        self._last = now
        self.t = now
        tgt = EXPRESSIONS["sleepy" if self.sleeping else self.expr]
        k = 1 - math.exp(-dt * 10)
        for key in self.cur:
            self.cur[key] += (tgt[key] - self.cur[key]) * k
        self.mouth += (self._mouth_target - self.mouth) * (1 - math.exp(-dt * 28))
        lx = ly = 0.0
        if self.look_anchor is not None and not self.sleeping:
            c, cur = self.look_anchor(), QCursor.pos()
            lx = max(-1.0, min(1.0, (cur.x() - c.x()) / 600.0)) * self.follow_strength
            ly = max(-1.0, min(1.0, (cur.y() - c.y()) / 600.0)) * self.follow_strength
        self._look[0] += (lx - self._look[0]) * 0.1
        self._look[1] += (ly - self._look[1]) * 0.1
        self.talking += (min(1.0, self.mouth * 1.6) - self.talking) * 0.2
        mood = "sleepy" if self.sleeping else self.expr
        self.rig.update(now, dt, self._look[0], self._look[1], self.talking, mood)
        if (self.auto_bored and self.expr == "neutral" and not self.sleeping
                and now - self.last_touch > 45 and self.talking < 0.05):
            self.set_expression("bored")
            self._next_yawn = now + 4
        if self.expr == "bored" and now >= self._next_yawn and self._yawn <= 0:
            self.yawn()
            self._next_yawn = now + random.uniform(18, 32)
        if self._yawn > 0:
            self._yawn -= dt
        if self._blink_p is None:
            if not self.sleeping and now >= self._next_blink:
                self._blink_p = 0.0
        else:
            self._blink_p += dt / 0.16
            if self._blink_p >= 1.0:
                self._blink_p = None
                self.blink = 0.0
                gap = 0.2 if random.random() < 0.15 else random.uniform(2.2, 5.5)
                self._next_blink = now + gap
            else:
                self.blink = math.sin(math.pi * self._blink_p)
        self.changed.emit()


def _median_skin(img, pts, default):
    vals = []
    for (x, y) in pts:
        if 0 <= x < img.width() and 0 <= y < img.height():
            c = img.pixelColor(int(x), int(y))
            if c.red() > 185 and c.red() >= c.green() >= c.blue() - 12:
                vals.append((c.red(), c.green(), c.blue()))
    if len(vals) < 4:
        return default
    arr = np.array(vals)
    return tuple(int(v) for v in np.median(arr, axis=0))


def _sample_skin(img, eye):
    """Median colour of the skin just below / around the eye (works under hair shadows)."""
    k = img.width() / REF_W
    cx, cy = eye["c"]
    a = math.radians(eye["ang"])
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for i in range(16):
        t = math.pi * (0.1 + 0.8 * i / 15)               # lower half ring
        lx, ly = (eye["hw"] + 3) * math.cos(t), (eye["hh"] + 5 + 4 * (i % 2)) * math.sin(t)
        pts.append(((cx + lx * ca - ly * sa) * k, (cy + lx * sa + ly * ca) * k))
    eye["skin"] = _median_skin(img, pts, eye["skin"])


def _paint_eye(p, eye, lid, raise_):
    cx, cy = eye["c"]
    hw, hh = eye["hw"], eye["hh"]
    SS = 3
    W, H = 2 * (hw + 6), 2 * (hh + 7)
    img = QImage(W * SS, H * SS, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    q.scale(SS, SS)
    q.translate(W / 2, H / 2)
    skin = QColor(*eye["skin"])
    left, right, top, bottom = -hw - 6, hw + 6, -hh - 4, hh + 7
    q.setPen(Qt.NoPen)
    q.setBrush(skin)
    edge = -hh + lid * 1.45 * hh
    if lid > 0.02:
        path = QPainterPath()
        path.moveTo(left, top)
        path.lineTo(right, top)
        path.lineTo(right, edge)
        path.quadTo(0, edge + 3.0, left, edge)
        path.closeSubpath()
        q.drawPath(path)
    if raise_ > 0.02:
        e2 = hh * 0.6 - raise_ * 1.4 * hh
        path = QPainterPath()
        path.moveTo(left, bottom)
        path.lineTo(right, bottom)
        path.lineTo(right, e2)
        path.quadTo(0, e2 - 4.0, left, e2)
        path.closeSubpath()
        q.drawPath(path)
    # feather the patch so it blends into the surrounding skin
    q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    q.save()
    q.scale(1.0, (hh + 5) / (hw + 4))
    g = QRadialGradient(QPointF(0, 0), hw + 4)
    g.setColorAt(0.0, QColor(0, 0, 0, 255))
    g.setColorAt(0.72, QColor(0, 0, 0, 255))
    g.setColorAt(1.0, QColor(0, 0, 0, 0))
    q.setBrush(QBrush(g))
    q.drawRect(QRectF(-W, -H * 2, W * 2, H * 4))
    q.restore()
    q.setCompositionMode(QPainter.CompositionMode_SourceOver)
    if lid > 0.02:
        lash = QPainterPath()
        lash.moveTo(-hw - 1, edge)
        lash.quadTo(0, edge + 3.0 + 2 * lid, hw + 1, edge)
        pen = QPen(QColor(48, 28, 58), 2.3)
        pen.setCapStyle(Qt.RoundCap)
        q.setPen(pen)
        q.setBrush(Qt.NoBrush)
        q.drawPath(lash)
    q.end()
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.translate(cx, cy)
    p.rotate(eye["ang"])
    p.drawImage(QRectF(-W / 2, -H / 2, W, H), img)
    p.restore()


def _mouth_ring(k):
    cx, cy = MOUTH["c"]
    hw = MOUTH["hw"]
    return [((cx + (hw + 6) * math.cos(t)) * k, (cy + 11 * math.sin(t)) * k)
            for t in [i * math.pi / 8 for i in range(16)]]


def _paint_mouth(p, m, smile, talk_shape=0.0):
    """Redraws the whole mouth: skin patch, then lips / opening / teeth / tongue.
    m = opening 0..1, smile = corner lift (-1..1), talk_shape = -1 (narrow 'oo') .. +1 (wide 'ee')."""
    cx, cy = MOUTH["c"]
    W = MOUTH["hw"] * (1.0 + 0.14 * talk_shape * min(1.0, m * 2.0) + 0.08 * max(0.0, smile))
    g = m * 9.0                                   # opening height
    lift = smile * 1.8                            # corners go up when smiling
    skin = QColor(*MOUTH.get("skin", (232, 186, 176)))
    lip = QColor(*MOUTH.get("lip", (222, 140, 130)))
    lip_dark, lip_light = lip.darker(150), lip.lighter(112)
    p.save()
    p.translate(cx, cy)
    p.rotate(MOUTH_ANGLE)
    p.setRenderHint(QPainter.Antialiasing)
    # feathered skin patch hides the original lips
    p.setPen(Qt.NoPen)
    gr = QRadialGradient(QPointF(0, 1.5), W + 6)
    gr.setColorAt(0.0, QColor(skin.red(), skin.green(), skin.blue(), 255))
    gr.setColorAt(0.72, QColor(skin.red(), skin.green(), skin.blue(), 255))
    gr.setColorAt(1.0, QColor(skin.red(), skin.green(), skin.blue(), 0))
    p.save()
    p.scale(1.0, 0.62)
    p.setBrush(QBrush(gr))
    p.drawEllipse(QPointF(0, 2.4), W + 6, W + 6)
    p.restore()
    cl = -lift                                    # y of the mouth corners (negative = up)
    top_c, bot_c = -1.1 + (-lift * 0.3), g * 1.25 + 0.4
    # inside of the mouth
    inner = QPainterPath()
    inner.moveTo(-W * 0.92, cl * 0.9)
    inner.quadTo(0, top_c * 2 - cl * 0.9 * 0.0, W * 0.92, cl * 0.9)
    inner.quadTo(0, bot_c * 2 - cl * 0.9, -W * 0.92, cl * 0.9)
    inner.closeSubpath()
    if g > 0.9:
        p.setBrush(QColor(86, 24, 42))
        p.drawPath(inner)
        p.save()
        p.setClipPath(inner)
        p.setBrush(QColor(247, 241, 238))                          # upper teeth
        p.drawRect(QRectF(-W, -3, 2 * W, 3 + min(g * 0.5, 3.6)))
        if g > 3.0:
            p.setBrush(QColor(206, 96, 110))                       # tongue
            p.drawEllipse(QPointF(0, g * 0.95), W * 0.5, g * 0.36)
        p.restore()
    # upper lip
    ul = QPainterPath()
    ul.moveTo(-W, cl)
    ul.quadTo(-W * 0.45, -3.4 + cl * 0.2, 0, -2.6)
    ul.quadTo(W * 0.45, -3.4 + cl * 0.2, W, cl)
    ul.quadTo(0, top_c * 2 - 0.4, -W, cl)
    ul.closeSubpath()
    p.setBrush(lip)
    p.setPen(QPen(lip_dark, 0.9))
    p.drawPath(ul)
    # lower lip
    ll = QPainterPath()
    ll.moveTo(-W * 0.96, cl + 0.3)
    ll.quadTo(0, bot_c * 2 - cl, W * 0.96, cl + 0.3)
    ll.quadTo(0, g * 1.25 + 5.4, -W * 0.96, cl + 0.3)
    ll.closeSubpath()
    p.setBrush(lip_light)
    p.setPen(QPen(lip_dark, 0.8))
    p.drawPath(ll)
    # corner dimples
    p.setPen(Qt.NoPen)
    p.setBrush(lip_dark)
    p.drawEllipse(QPointF(-W, cl), 0.8, 0.8)
    p.drawEllipse(QPointF(W, cl), 0.8, 0.8)
    p.restore()


def paint_overlays(p, a):
    p.setRenderHint(QPainter.Antialiasing)
    if a.cur["blush"] > 0.02:
        for (x, y) in BLUSH:
            g = QRadialGradient(QPointF(x, y), 20)
            g.setColorAt(0, QColor(255, 105, 130, int(95 * a.cur["blush"])))
            g.setColorAt(1, QColor(255, 105, 130, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(x, y), 20, 14)
    lid, raise_ = a.lid, a.cur["raise_"]
    if lid > 0.02 or raise_ > 0.02:
        for eye in EYES:
            _paint_eye(p, eye, lid, raise_)
    m = min(1.0, max(a.cur["open"] + a.mouth, a.yawn_amount * 0.9))
    smile = a.cur.get("smile", 0.3)
    redraw = m > 0.04 or abs(smile - SMILE["neutral"]) > 0.12
    if redraw:
        shape = math.sin(a.t * 6.3) * 0.7 + math.sin(a.t * 2.9 + 1.0) * 0.3     # varies the mouth shape while talking
        _paint_mouth(p, m, smile, shape if a.mouth > 0.05 else 0.0)
    if a.sleeping:
        f = QFont("Segoe UI")
        f.setPixelSize(24)
        f.setBold(True)
        p.setFont(f)
        for i, (dx, size) in enumerate([(0, 30), (26, 24), (46, 18)]):
            ph = (a.t * 0.5 + i * 0.3) % 1.0
            p.setPen(QColor(190, 180, 255, int(255 * (1 - ph))))
            p.drawText(QPointF(470 + dx * 0.8, 70 - ph * 26 - i * 12), "z")


def scale_hq_image(img, w, h):
    """High quality (Lanczos, premultiplied alpha) downscale -> straight-alpha RGBA8888 QImage."""
    try:
        from PIL import Image
        rgba = img.convertToFormat(QImage.Format_RGBA8888)
        pil = Image.frombuffer("RGBA", (rgba.width(), rgba.height()), bytes(rgba.constBits()),
                               "raw", "RGBA", rgba.bytesPerLine(), 1)
        data = pil.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA").tobytes()
        return QImage(data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    except Exception:
        return img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGBA8888)


class AvatarView(QWidget):
    """Draws the character (or a crop of it) as warped tiles + face overlays."""
    clicked = Signal(str)

    def __init__(self, animator, src=None, parent=None, draggable=False, view="full"):
        """view="full": the whole visible picture (floating companion); view="card": the head-and-torso crop of
        the narrow chat-page card. Both follow the active character's picture; an explicit src overrides them."""
        super().__init__(parent)
        self.anim = animator
        self._fixed_src = src
        self._view = view
        self.draggable = draggable
        self._key = None
        self._geo = None
        self._press = None
        self._moved = False
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        animator.changed.connect(self.update)

    @property
    def src(self):
        if self._fixed_src is not None:
            return self._fixed_src
        return self.anim.card_rect if self._view == "card" else self.anim.full_rect

    def _build(self, dpr, pw, ph):
        a = self.anim
        key = (pw, ph, round(dpr, 2), a.art_serial)
        cached = a.tile_cache.get(key)
        if cached is None:
            img = scale_hq_image(a.master, pw, ph)
            arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(ph, img.bytesPerLine() // 4, 4)[:, :pw, :]
            E = 4                                          # overlap margin in device pixels
            pad = np.pad(arr, ((E, E), (E, E), (0, 0)))
            sdx, sdy = pw / a.img_w, ph / a.img_h
            pms, dsts, bx, by = [], [], [], []
            for (x0, y0, x1, y1) in a.tiles:
                sx0, sx1 = round(x0 * sdx), round(x1 * sdx)
                sy0, sy1 = round(y0 * sdy), round(y1 * sdy)
                t = np.ascontiguousarray(pad[sy0:sy1 + 2 * E, sx0:sx1 + 2 * E])
                ring = np.ones(t.shape[:2], dtype=bool)
                ring[E:-E, E:-E] = False
                t[ring & (t[..., 3] < 250)] = 0            # margin keeps only fully opaque pixels
                al = t[..., 3:4].astype(np.float32) / 255.0
                t[..., :3] = (t[..., :3] * al).astype(np.uint8)
                qi = QImage(t.data, t.shape[1], t.shape[0], t.shape[1] * 4, QImage.Format_RGBA8888_Premultiplied).copy()
                pms.append(QPixmap.fromImage(qi))
                w_, h_ = t.shape[1] / dpr, t.shape[0] / dpr
                dsts.append(QRectF(-w_ / 2, -h_ / 2, w_, h_))
                bx.append((sx0 + sx1) / 2 / dpr)
                by.append((sy0 + sy1) / 2 / dpr)
            cached = (pms, dsts, np.array(bx), np.array(by))
            if len(a.tile_cache) >= 3:
                a.tile_cache.pop(next(iter(a.tile_cache)))
            a.tile_cache[key] = cached
        self._pms, self._dst_rects, self._bx, self._by = cached

    def paintEvent(self, event):
        a, src = self.anim, self.src
        if a.pix.isNull():
            return
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        s = min(w / src.width(), h / src.height())
        pw, ph = max(1, round(a.img_w * s * dpr)), max(1, round(a.img_h * s * dpr))
        if (pw, ph, a.art_serial) != self._key:
            self._key = (pw, ph, a.art_serial)
            self._build(dpr, pw, ph)
        ox = (w - src.width() * s) / 2 - src.x() * s
        oy = (h - src.height() * s) / 2 - src.y() * s
        self._geo = (ox, oy, s)
        dx, dy, m11, m12, m21, m22 = a.rig.affine(a.tile_cx, a.tile_cy)
        X, Y = self._bx + ox + dx * s, self._by + oy + dy * s
        vis = np.nonzero((X > -90) & (X < w + 90) & (Y > -90) & (Y < h + 90))[0].tolist()
        Xl, Yl = X.tolist(), Y.tolist()
        A, Bm, C, D = m11.tolist(), m12.tolist(), m21.tolist(), m22.tolist()
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if a.clip_rect is not None:                         # other characters: keep the sway inside the picture frame
            cr = a.clip_rect
            frame = QPainterPath()
            frame.addRoundedRect(QRectF(ox + cr.x() * s, oy + cr.y() * s, cr.width() * s, cr.height() * s),
                                 14 * s, 14 * s)
            p.setClipPath(frame)
        pms, dr = self._pms, self._dst_rects
        for i in vis:
            p.setTransform(QTransform(A[i], Bm[i], C[i], D[i], Xl[i], Yl[i]))
            p.drawPixmap(dr[i], pms[i], pms[i].rect())
        p.resetTransform()
        if a.face_overlays:                                 # eyelid / mouth overlays are measured on Kira's face only
            fx, fy, f11, f12, f21, f22 = a.rig.affine(np.array([FACE_C[0]]), np.array([FACE_C[1]]))
            p.translate(ox + (FACE_C[0] + fx[0]) * s, oy + (FACE_C[1] + fy[0]) * s)
            p.rotate(math.degrees(math.atan2(float(f12[0]), float(f11[0]))))
            p.scale(s, s)
            p.translate(-FACE_C[0], -FACE_C[1])
            paint_overlays(p, a)
        p.end()

    # ---- clicks / dragging ----
    def region_at(self, pos):
        if not self._geo:
            return None
        ox, oy, s = self._geo
        return region_at((pos.x() - ox) / s, (pos.y() - oy) / s)

    def _pet(self):
        return getattr(self.window(), "pet", None) if self.draggable else None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._win0 = self.window().frameGeometry().topLeft()
            self._moved = False
            if self._pet() is not None:
                self._pet().press(self._press)

    def mouseMoveEvent(self, e):
        if self._press is None or not self.draggable:
            return
        pet = self._pet()
        if pet is not None:
            pet.move(e.globalPosition().toPoint())
            self._moved = self._moved or pet._moved
            return
        d = e.globalPosition().toPoint() - self._press
        if d.manhattanLength() > 6:
            self._moved = True
        if self._moved:
            self.window().move(self._win0 + d)

    def mouseReleaseEvent(self, e):
        if self._press is not None:
            pet = self._pet()
            moved = pet.release() if pet is not None else self._moved
            if not moved:
                r = self.region_at(e.position())
                if r:
                    self.clicked.emit(r)
        self._press = None

    def contextMenuEvent(self, e):
        if self.draggable:
            self.window().hide()
