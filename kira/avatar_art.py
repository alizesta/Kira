"""Geometry for the pictures of the non-Kira characters (pure Python, no Qt, so it is unit-testable anywhere).

Kira's animated PNG is a cut-out sitting on the 832 x 1248 reference canvas that the soft-body rig (kira/rig.py)
is calibrated for. Ren's and Mika's pictures are rectangular paintings with their own background, so each one is
fitted into that same canvas (height-fitted and centred). The rig, the click regions and the look-at logic keep working
unchanged; only the face overlays (eyelids / mouth patches, measured on Kira's face) are switched off for them.

A picture is drawn slightly larger than the frame the user sees (BLEED reference pixels on every side) and the
view is clipped to that frame, so the sway of the rig never shows a gap at the picture's border.
"""
from __future__ import annotations

REF_W, REF_H = 832, 1248              # reference canvas shared with kira/face.py and kira/rig.py
BLEED = 24                            # reference pixels of picture kept outside the visible frame
CARD_W, CARD_H = 520, 680             # crop shown in the narrow chat-page card (same size as Kira's crop)
KIRA_CARD = (150.0, 0.0, float(CARD_W), float(CARD_H))


def layout(src_w, src_h):
    """Where a src_w x src_h picture goes on the reference canvas.

    Returns a dict of (x, y, w, h) tuples in reference pixels:
      art     - where the whole picture is drawn
      content - the visible frame (art inset by BLEED); the floating companion window shows exactly this
      card    - the head-and-torso crop for the chat-page card (aspect of Kira's crop, inside the frame)
    plus window_ratio = frame height / frame width (used to size the floating window).
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError("picture size must be positive")
    scale = min(REF_W / src_w, REF_H / src_h)
    aw, ah = src_w * scale, src_h * scale
    ax, ay = (REF_W - aw) / 2.0, (REF_H - ah) / 2.0
    b = min(BLEED, aw / 4.0, ah / 4.0)
    cx, cy, cw, ch = ax + b, ay + b, aw - 2 * b, ah - 2 * b
    card_w = min(float(CARD_W), cw)
    card_h = card_w * CARD_H / CARD_W
    if card_h > ch:
        card_h = ch
        card_w = card_h * CARD_W / CARD_H
    card = (cx + (cw - card_w) / 2.0, cy, card_w, card_h)
    return {"art": (ax, ay, aw, ah), "content": (cx, cy, cw, ch), "card": card, "window_ratio": ch / cw}


def cover_crop(src_w, src_h, dst_w, dst_h):
    """Source rectangle (x, y, w, h) that fills dst_w x dst_h without distortion.

    Used for the small character portrait: the crop is centred horizontally and biased toward the top (faces)."""
    if min(src_w, src_h, dst_w, dst_h) <= 0:
        raise ValueError("sizes must be positive")
    want = dst_w / dst_h
    have = src_w / src_h
    if abs(have - want) < 1e-6:
        return (0.0, 0.0, float(src_w), float(src_h))
    if have > want:                                   # too wide: trim the sides
        w = src_h * want
        return ((src_w - w) / 2.0, 0.0, w, float(src_h))
    h = src_w / want                                  # too tall: trim the bottom more than the top
    return (0.0, (src_h - h) * 0.25, float(src_w), h)
