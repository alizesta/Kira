"""Optional local OCR. No dependency is installed or downloaded by Kira.

Uses pytesseract + Pillow only when already available; otherwise returns an empty
string and visual-model analysis continues normally.
"""
from __future__ import annotations


def extract_local_text(image_attachment: dict) -> str:
    if not isinstance(image_attachment, dict) or not image_attachment.get("b64"):
        return ""
    try:
        import base64
        from io import BytesIO
        from PIL import Image
        import pytesseract
        raw = base64.b64decode(image_attachment["b64"], validate=True)
        with Image.open(BytesIO(raw)) as image:
            image.thumbnail((1280, 720))
            text = pytesseract.image_to_string(image, config="--psm 6")
        return " ".join(str(text or "").split())[:2400]
    except Exception:
        return ""


