"""Downloads the three small JavaScript libraries the VRM viewer needs (pure Python, no Qt).

Files go to assets/vrm/vendor/. Run automatically on first start (kira/vrm_avatar.py) and by install_deps.py;
can also be run by hand:  python -m kira.vrm_vendor
If the download is impossible, put the same files there yourself - the viewer only reads local files.
"""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "assets" / "vrm" / "vendor"
THREE = "0.160.0"
VRM = "2.1.3"
CDN = "https://cdn.jsdelivr.net/npm/"
# local path (relative to VENDOR) -> url
FILES = {
    "three.module.js": f"{CDN}three@{THREE}/build/three.module.js",
    "addons/loaders/GLTFLoader.js": f"{CDN}three@{THREE}/examples/jsm/loaders/GLTFLoader.js",
    "addons/utils/BufferGeometryUtils.js": f"{CDN}three@{THREE}/examples/jsm/utils/BufferGeometryUtils.js",
    "three-vrm.module.js": f"{CDN}@pixiv/three-vrm@{VRM}/lib/three-vrm.module.js",
}


def missing():
    return [name for name in FILES if not (VENDOR / name).is_file() or (VENDOR / name).stat().st_size < 2000]


def ready():
    return not missing()


def download(log=print):
    """Fetch every missing file. Returns True when all are present. Never raises."""
    ok = True
    for name in missing():
        target = VENDOR / name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(FILES[name], headers={"User-Agent": "Kira"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if len(data) < 2000 or b"<html" in data[:200].lower():
                raise ValueError("unexpected content")
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(target)
            log(f"VRM viewer file downloaded: {name}")
        except Exception as exc:                              # noqa: BLE001 - optional feature, never stop the app
            ok = False
            log(f"VRM viewer file NOT downloaded: {name} ({exc})")
    return ok and ready()


if __name__ == "__main__":
    sys.exit(0 if download() else 1)
