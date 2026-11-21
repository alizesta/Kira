"""Soft-body puppet rig for the flat Kira picture (v1.5).

One flat PNG cannot be truly layered, so every body part owns a soft region and
moves with spring physics; the picture is warped by the sum of those motions
(including stretch, so joints do not tear). Moods change posture and rhythm.
Coordinates are original image pixels (1024 x 1536).
"""
import math
import random
import numpy as np

CH = {"ang": 0, "tx": 1, "ty": 2, "sc": 3}
MOODS = ["neutral", "happy", "excited", "sad", "bored", "angry", "shy", "surprised", "thinking", "sleepy"]


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


class Part:
    def __init__(self, center, radii, pivot, inner, k=70.0, c=9.0):
        self.c, self.r, self.p, self.inner, self.k, self.c_damp = center, radii, pivot, inner, k, c
        self.pos = np.zeros(4)      # ang(deg), tx, ty, scale
        self.vel = np.zeros(4)
        self.target = np.zeros(4)

    def weight(self, X, Y):
        d = np.sqrt(((X - self.c[0]) / self.r[0]) ** 2 + ((Y - self.c[1]) / self.r[1]) ** 2)
        return 1.0 - _smooth((d - self.inner) / (1.0 - self.inner))


#            center       radii       pivot      inner  stiffness damping
# Coordinates are in "reference pixels" of the 832 x 1248 character picture.
PARTS = {
    "head":    ((420, 100), (125, 135), (418, 195), 0.62, 70, 9),
    "body":    ((415, 480), (215, 310), (415, 570), 0.45, 70, 9),
    "chest":   ((415, 300), (125, 100), (415, 365), 0.35, 36, 4.2),     # soft, bouncy follow-through
    "skirt":   ((410, 560), (210, 80), (410, 480), 0.40, 44, 5.0),      # clothes: swings with the hips
    "arm_l":   ((268, 220), (78, 100), (305, 305), 0.45, 70, 9),        # waving arm (viewer's left)
    "arm_r":   ((592, 500), (70, 200), (545, 335), 0.40, 70, 9),
    "leg_l":   ((365, 900), (72, 340), (372, 640), 0.75, 70, 10),
    "leg_r":   ((468, 910), (66, 340), (466, 640), 0.75, 70, 10),
    "hair_l":  ((265, 390), (105, 240), (325, 150), 0.30, 50, 5.5),
    "hair_r":  ((592, 330), (85, 230), (520, 135), 0.30, 50, 5.5),
    "strap_l": ((255, 760), (62, 125), (272, 640), 0.35, 38, 4.0),      # hanging belt ribbons
    "strap_r": ((580, 770), (58, 135), (575, 650), 0.35, 38, 4.0),
}

REGIONS = [
    ("face", (412, 128), (40, 50)),
    ("hair", (420, 50), (85, 60)),
    ("hand", (265, 200), (44, 52)),
    ("arm_l", (285, 335), (78, 100)),
    ("arm_r", (625, 650), (32, 52)),
    ("arm_r", (595, 500), (52, 150)),
    ("clothes", (255, 760), (55, 120)),
    ("clothes", (580, 770), (50, 130)),
    ("hair", (265, 420), (80, 200)),
    ("hair", (600, 330), (62, 200)),
    ("torso", (415, 330), (115, 150)),
    ("torso", (410, 540), (170, 90)),
    ("legs", (410, 840), (115, 240)),
    ("feet", (410, 1170), (115, 80)),
]


def region_at(x, y):
    for name, (cx, cy), (rx, ry) in REGIONS:
        if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
            return name
    return None


# safety limits (angle deg, translation px) so big kicks never tear the picture
LIMITS = {"head": (14, 22), "body": (5, 34), "chest": (8, 22), "skirt": (7, 24), "arm_l": (34, 22), "arm_r": (26, 22),
          "leg_l": (3.0, 12), "leg_r": (3.0, 12), "hair_l": (14, 24), "hair_r": (14, 24),
          "strap_l": (16, 18), "strap_r": (16, 18)}

# breathing speed (rad/s), breathing depth, general energy per mood
MOOD_BREATH = {"neutral": (2.0, 1.0), "happy": (2.8, 1.1), "excited": (4.6, 1.5), "sad": (1.5, 1.3),
               "bored": (1.25, 1.2), "angry": (3.6, 1.4), "shy": (3.2, 0.9), "surprised": (4.2, 1.5),
               "thinking": (1.8, 0.9), "sleepy": (1.05, 1.5)}


class Rig:
    def __init__(self):
        self.parts = {n: Part(*a) for n, a in PARTS.items()}
        self.intensity = 0.32
        self.bphase = 0.0
        self._next_event = 3.0
        self._sigh_until = 0.0

    def kick(self, part, channel, impulse):
        p = self.parts.get(part)
        if p is not None:
            p.vel[CH[channel]] += impulse * self.intensity

    # ---- random life: small spontaneous movements ----
    def _idle_event(self, t, mood):
        if mood in ("sleepy",):
            self.kick("head", "ty", -20)
            return
        r = random.random()
        if mood in ("neutral", "happy", "excited"):
            if r < 0.30:
                self.kick("arm_l", "ang", random.choice((-1, 1)) * 22)
            elif r < 0.55:
                self.kick("head", "ang", random.choice((-1, 1)) * 22)
            elif r < 0.75:
                self.kick("hair_l", "ang", 70); self.kick("hair_r", "ang", -70)
            elif r < 0.90:
                self.kick("body", "tx", random.choice((-1, 1)) * 24)
            else:
                self.kick("body", "ty", -110); self.kick("chest", "ty", 60)       # little hop
        elif mood == "bored":
            if r < 0.5:
                self.kick("body", "tx", random.choice((-1, 1)) * 20)
            else:
                self._sigh_until = t + 2.4
        elif mood == "angry":
            self.kick("head", "ty", 12); self.kick("arm_r", "ang", -35)
        elif mood == "sad":
            self._sigh_until = t + 2.6
        else:
            self.kick("head", "ang", random.choice((-1, 1)) * 15)

    def update(self, t, dt, lx, ly, talk, mood="neutral"):
        I = self.intensity
        P = self.parts
        speed, depth = MOOD_BREATH.get(mood, (2.0, 1.0))
        sigh = 2.2 if t < self._sigh_until else 1.0          # deep sigh breath
        self.bphase += dt * speed * (0.55 if sigh > 1 else 1.0)
        ph = self.bphase
        breath = math.sin(ph + 0.45 * math.sin(ph))          # quicker inhale, slower exhale
        B = breath * depth * sigh
        if t >= self._next_event:
            self._idle_event(t, mood)
            self._next_event = t + random.uniform(2.5, 6.0)

        bv = P["body"].vel        # velocity of body -> secondary motion of soft parts
        # ---------- base idle (exaggerated) ----------
        h_ang = lx * 9 + math.sin(t * 0.9) * 2.0 + talk * math.sin(t * 7) * 2.6
        h_tx, h_ty = lx * 16, ly * 8 + B * 2.0 + talk * 3.0
        b_tx, b_ty, b_sc = lx * 6 + math.sin(t * 0.6) * 5, B * 2.4, B * 0.006
        al = math.sin(t * 2.6) * 11 + math.sin(t * 0.8) * 3
        ar = math.sin(t * 1.0 + 1) * 3.5 + B * 1.2
        ll, lr = math.sin(t * 0.7) * 1.2, math.sin(t * 0.7 + 2.2) * 1.2
        hl = math.sin(t * 1.3) * 4 - lx * 3 - bv[1] * 0.03
        hr = math.sin(t * 1.15 + 1.3) * 4 - lx * 3 - bv[1] * 0.03
        al_amp = 1.0
        # ---------- mood posture ----------
        if mood == "happy":
            b_ty += math.sin(t * 6.5) * 6; h_ang += math.sin(t * 3.2) * 4; al += math.sin(t * 5) * 10
            hl += math.sin(t * 6.5 + 1) * 4; hr += math.sin(t * 6.5 + 2) * 4
        elif mood == "excited":
            b_ty += -abs(math.sin(t * 7.5)) * 14; h_ang += math.sin(t * 4) * 6; al += math.sin(t * 7) * 16
            ar += math.sin(t * 7 + 1) * 8; hl += math.sin(t * 7.5) * 7; hr += math.sin(t * 7.5 + 1) * 7
        elif mood == "sad":
            h_ty += 18; h_ang += -8; b_ty += 8; b_sc -= 0.004; al_amp = 0.25; hl += 4; hr -= 4
        elif mood == "bored":
            h_ang += 10 + math.sin(t * 0.5) * 3; h_ty += 9; b_tx += math.sin(t * 0.45) * 14; al_amp = 0.2
            ar += math.sin(t * 0.6) * 4
        elif mood == "angry":
            b_tx += math.sin(t * 28) * 1.8; h_ty += 9; h_ang += -3; ar += -11; al_amp = 0.4
            hl += math.sin(t * 9) * 3; hr += math.sin(t * 9 + 1) * 3
        elif mood == "shy":
            h_ang += 11; h_ty += 8; b_tx += -9; al_amp = 0.35; al += 10
        elif mood == "surprised":
            h_ty += -11; b_ty += -5; hl += 4; hr -= 4; ar += -6
        elif mood == "thinking":
            h_ang += -9; h_tx += 11; al_amp = 0.5; b_tx += math.sin(t * 0.8) * 4
        elif mood == "sleepy":
            h_ty += 22; h_ang += 12 + math.sin(t * 0.5) * 3; b_ty += 7; al_amp = 0.08; ar *= 0.2
            ll *= 0.2; lr *= 0.2
        al *= al_amp

        def tgt(name, ang=0.0, tx=0.0, ty=0.0, sc=0.0):
            P[name].target[:] = (ang * I, tx * I, ty * I, sc * I)

        tgt("head", h_ang, h_tx, h_ty)
        tgt("body", 0.8 * math.sin(t * 0.6), b_tx, b_ty, b_sc)
        # chest: breathing + lagging follow-through of body movement (soft secondary motion)
        tgt("chest", 0, -bv[1] * 0.04, -B * 7 - bv[2] * 0.06, B * 0.016)
        tgt("arm_l", al); tgt("arm_r", ar)
        tgt("leg_l", ll); tgt("leg_r", lr)
        tgt("hair_l", hl); tgt("hair_r", hr)
        # clothes: ribbons and skirt swing with a delay behind the body (secondary motion)
        sk = math.sin(t * 1.1) * 2.2 - bv[1] * 0.04
        tgt("skirt", sk, -bv[1] * 0.05, 0, B * 0.004)
        tgt("strap_l", math.sin(t * 1.4) * 3.0 - bv[1] * 0.05 + lx * -2)
        tgt("strap_r", math.sin(t * 1.3 + 1.0) * 3.0 - bv[1] * 0.05 + lx * -2)
        dt = min(dt, 0.05)
        for _ in range(3):
            h = dt / 3
            for p in P.values():
                acc = p.k * (p.target - p.pos) - p.c_damp * p.vel
                p.vel += acc * h
                p.pos += p.vel * h
        for name, p in P.items():
            la, lt = LIMITS[name]
            for i, lim in ((0, la), (1, lt), (2, lt)):
                if abs(p.pos[i]) > lim:
                    p.pos[i] = math.copysign(lim, p.pos[i])
                    p.vel[i] *= 0.3

    def field(self, X, Y):
        """Displacement (dx, dy) at image points X, Y (numpy arrays)."""
        dx = np.zeros_like(X, dtype=np.float64)
        dy = np.zeros_like(dx)
        for p in self.parts.values():
            ang, tx, ty, sc = p.pos
            if abs(ang) < 1e-4 and abs(tx) < 1e-4 and abs(ty) < 1e-4 and abs(sc) < 1e-6:
                continue
            w = p.weight(X, Y)
            rx, ry = X - p.p[0], Y - p.p[1]
            th = math.radians(ang)
            c, s = math.cos(th), math.sin(th)
            k = 1.0 + sc
            dx += w * (k * (c * rx - s * ry) - rx + tx)
            dy += w * (k * (s * rx + c * ry) - ry + ty)
        return dx, dy

    def affine(self, X, Y, e=14.0):
        """Per-point displacement and local 2x2 Jacobian (so tiles stretch with the field)."""
        # One batched field() call over all five sample sets: identical maths, but the per-part numpy
        # overhead is paid once instead of five times (this runs for every visible avatar, every frame).
        n = len(X)
        fx, fy = self.field(np.concatenate((X, X + e, X - e, X, X)), np.concatenate((Y, Y, Y, Y + e, Y - e)))
        dx, dxp, dxm, dxu, dxd = (fx[i * n:(i + 1) * n] for i in range(5))
        dy, dyp, dym, dyu, dyd = (fy[i * n:(i + 1) * n] for i in range(5))
        a = 1 + (dxp - dxm) / (2 * e)      # d x'/d x
        b = (dyp - dym) / (2 * e)          # d y'/d x
        c = (dxu - dxd) / (2 * e)          # d x'/d y
        d = 1 + (dyu - dyd) / (2 * e)      # d y'/d y
        lim = lambda v, lo, hi: np.clip(v, lo, hi)
        return dx, dy, lim(a, .6, 1.5), lim(b, -.6, .6), lim(c, -.6, .6), lim(d, .6, 1.5)
