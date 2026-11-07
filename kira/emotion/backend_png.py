"""Avatar backend for the current avatar: one flat PNG animated by the existing soft-body rig and
procedural face overlays (kira/face.py, kira/rig.py - both unchanged).

This is the only emotion module that knows about Qt / the PNG avatar. A future backend (several
PNG expressions, eye/mouth layers, sprite sequences, Live2D, VRM) implements the same small contract:
    consume engine.Frame  ->  frame.face (lid, raise, open, blush, smile), frame.pose,
                              frame.base_mood, frame.speaking
and the library, engine and parser stay as they are.

What the PNG can and cannot show: see emotion_library/avatar/profile.json and README_EMOTION_LIBRARY.md.
"""
import numpy as np

from ..face import FaceAnimator
from ..rig import Rig, CH, LIMITS


class EmotionRig(Rig):
    """Soft-body rig plus an additive 'emotion pose' layer.

    The overlay is added only while drawing (it never enters the spring simulation), so it cannot
    accumulate, fight the idle physics or stay stuck: clear it and the body is exactly as before.
    """

    def __init__(self):
        super().__init__()
        self.overlay = {}

    def set_overlay(self, pose, scale):
        ov = {}
        if scale > 0:
            for (part, channel), value in pose.items():
                if part in self.parts and channel in CH:
                    ov.setdefault(part, np.zeros(4))[CH[channel]] += value * scale
        self.overlay = ov

    def field(self, X, Y):
        if not self.overlay:
            return super().field(X, Y)
        saved = {}
        try:
            for name, delta in self.overlay.items():
                part = self.parts[name]
                saved[name] = part.pos
                ang, trans = LIMITS[name]
                pos = part.pos + delta
                pos[0] = max(-ang, min(ang, pos[0]))
                pos[1] = max(-trans, min(trans, pos[1]))
                pos[2] = max(-trans, min(trans, pos[2]))
                part.pos = pos
            return super().field(X, Y)
        finally:
            for name, pos in saved.items():
                self.parts[name].pos = pos


class EmotionFaceAnimator(FaceAnimator):
    """FaceAnimator whose expression is decided by the EmotionDirector.

    * set_expression(name, hold) keeps working for all existing callers; known emotion names are
      routed through the director, anything else (e.g. 'sleepy') falls through to the old behaviour.
    * Each frame the director's blended face channels drive the existing eyelid / cheek / mouth /
      blush overlays and its pose drives the rig. When the director is idle nothing is overridden, so
      the original idle animation (breathing, blinking, look-at, boredom) runs exactly as before.
    """
    director = None
    _passthrough = False
    _driving = False
    _serial_seen = 0

    def __init__(self, parent=None, director=None):
        super().__init__(parent)
        self.director = director
        self.rig = EmotionRig()

    # ---- legacy API, now routed through the emotion system ----
    def set_expression(self, name, hold=None):
        d = self.director
        if d is None:
            return FaceAnimator.set_expression(self, name, hold)
        if d.request_direct(name, hold):
            self._passthrough = False
            self._sync_mood(d.base_mood())
            return
        d.release_direct()                       # unknown name (e.g. 'sleepy'): old behaviour owns the face
        self._passthrough = True
        self._serial_seen = d.engine.serial
        FaceAnimator.set_expression(self, name, hold)

    def _sync_mood(self, base):
        """Keep the rig's discrete mood posture / breathing in line with the dominant emotion."""
        if not self._passthrough and base and base != self.expr:
            FaceAnimator.set_expression(self, base)

    # ---- per frame ----
    def _tick(self):
        d = self.director
        frame = None
        if self._passthrough and d is not None and d.engine.serial != self._serial_seen:
            self._passthrough = False            # a reply / event asked for an emotion: the director takes over again
        if d is not None and not self._passthrough:
            frame = d.tick()
            if not self.sleeping:
                self._sync_mood(frame.base_mood)
            self.rig.set_overlay(frame.pose if (frame.active and not self.sleeping) else {}, float(self.rig.intensity))
        else:
            self.rig.set_overlay({}, 0.0)
        FaceAnimator._tick(self)
        if frame is not None and frame.active and not self.sleeping:
            if self._driving:
                face = frame.face
                self.cur["lid"], self.cur["raise_"] = face["lid"], face["raise"]
                self.cur["open"], self.cur["blush"], self.cur["smile"] = face["open"], face["blush"], face["smile"]
            else:                                # just became active: start from what is on screen now
                d.engine.seed_face({"lid": self.cur["lid"], "raise": self.cur["raise_"], "open": self.cur["open"],
                                    "blush": self.cur["blush"], "smile": self.cur["smile"]})
                self._driving = True
        else:
            self._driving = False
