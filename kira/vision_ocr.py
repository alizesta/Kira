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
        encoded = str(image_attachment["b64"])
        if len(encoded) > 30_000_000:  # skip oversized user attachments before decoding
            return ""
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                return ""
            image.thumbnail((1280, 720))
            text = pytesseract.image_to_string(image, config="--psm 6", timeout=4)
        return " ".join(str(text or "").split())[:2400]
    except Exception:
        return ""


