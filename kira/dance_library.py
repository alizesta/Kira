"""Dance files the user dropped into assets/vrm/animations/ (pure Python, no Qt).

Supported: VRM Animation (.vrma) and Mixamo (.fbx, "FBX Binary", "Without Skin"). The viewer picks one at random when music starts.
"""
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "assets" / "vrm" / "animations"
EXTENSIONS = {".vrma": "vrma", ".fbx": "fbx"}
MIXAMO_URL = "https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack&query=dance"


def ensure_folder() -> Path:
    FOLDER.mkdir(parents=True, exist_ok=True)
    return FOLDER


def scan(folder: Path | None = None, base_url: str = "") -> list[dict]:
    """[{name, url, kind}] sorted by name; url is relative to the viewer's web root (assets/vrm/) unless base_url is given."""
    folder = Path(folder) if folder else FOLDER
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        kind = EXTENSIONS.get(path.suffix.lower())
        if kind and path.is_file() and path.stat().st_size > 0:
            out.append({"name": path.stem, "kind": kind, "url": f"{base_url}animations/{urllib.parse.quote(path.name)}"})
    return out
