"""Read-only inspection helpers for VRM 0.x / 1.0 GLB files.

The model is never rewritten here. In particular, license metadata is reported verbatim;
it is not treated as proof of ownership or silently changed by the application.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import struct
from typing import Any

_GLTF_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_MAX_JSON_CHUNK = 16 * 1024 * 1024
_MAX_MODEL_BYTES = 512 * 1024 * 1024


class VrmFileError(ValueError):
    """The selected file is not a readable VRM/GLB model."""


@dataclass(frozen=True)
class VrmInfo:
    path: str
    size_bytes: int
    gltf_version: int
    vrm_version: str
    title: str
    authors: tuple[str, ...]
    humanoid_bones: tuple[str, ...]
    expressions: tuple[str, ...]
    spring_bone_groups: int
    license_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_glb_json(path: Path) -> tuple[dict[str, Any], int]:
    try:
        size = path.stat().st_size
        if size < 20 or size > _MAX_MODEL_BYTES:
            raise VrmFileError(f"حجم فایل معتبر نیست: {size} بایت.")
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12 or header[:4] != _GLTF_MAGIC:
                raise VrmFileError("فایل انتخاب‌شده GLB/VRM معتبر نیست.")
            _magic, version, declared_length = struct.unpack("<4sII", header)
            if version != 2:
                raise VrmFileError(f"نسخه GLB پشتیبانی نمی‌شود: {version}.")
            if declared_length != size:
                raise VrmFileError("طول ثبت‌شده در هدر GLB با اندازه فایل یکسان نیست.")

            offset = 12
            while offset + 8 <= size:
                stream.seek(offset)
                chunk_header = stream.read(8)
                if len(chunk_header) != 8:
                    break
                chunk_length, chunk_type = struct.unpack("<II", chunk_header)
                offset += 8
                if chunk_length > size - offset:
                    raise VrmFileError("ساختار chunk فایل GLB خراب است.")
                if chunk_type == _JSON_CHUNK:
                    if chunk_length > _MAX_JSON_CHUNK:
                        raise VrmFileError("بخش JSON فایل بیش از حد بزرگ است.")
                    raw = stream.read(chunk_length)
                    try:
                        return json.loads(raw.decode("utf-8").rstrip("\x00 \t\r\n")), version
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise VrmFileError("اطلاعات JSON داخل فایل VRM قابل خواندن نیست.") from exc
                offset += chunk_length
    except OSError as exc:
        raise VrmFileError(f"فایل VRM خوانده نشد: {exc}") from exc
    raise VrmFileError("بخش JSON در فایل GLB پیدا نشد.")


def inspect_vrm(path: str | Path) -> VrmInfo:
    """Validate the GLB container and return useful VRM metadata without modifying it."""
    model_path = Path(path).expanduser()
    if model_path.suffix.lower() != ".vrm":
        raise VrmFileError("پسوند فایل باید .vrm باشد.")
    if not model_path.is_file():
        raise VrmFileError("فایل VRM پیدا نشد.")
    model_path = model_path.resolve()
    document, gltf_version = _read_glb_json(model_path)
    asset = document.get("asset") or {}
    if str(asset.get("version", "")) != "2.0":
        raise VrmFileError("این فایل glTF 2.0 نیست.")

    extensions = document.get("extensions") or {}
    vrm1 = extensions.get("VRMC_vrm")
    vrm0 = extensions.get("VRM")
    if isinstance(vrm1, dict):
        vrm_version = "1.0"
        meta = vrm1.get("meta") or {}
        humanoid = vrm1.get("humanoid") or {}
        human_bones = humanoid.get("humanBones") or {}
        bones = tuple(sorted(str(name) for name in human_bones if isinstance(name, str)))
        expression_block = vrm1.get("expressions") or {}
        preset = expression_block.get("preset") or {}
        custom = expression_block.get("custom") or {}
        expressions = tuple(sorted({str(name) for name in (*preset.keys(), *custom.keys())}))
        springs = (extensions.get("VRMC_springBone") or {}).get("springs") or []
        license_keys = (
            "avatarPermission", "allowExcessivelyViolentUsage", "allowExcessivelySexualUsage",
            "commercialUsage", "allowPoliticalOrReligiousUsage", "allowAntisocialOrHateUsage",
            "creditNotation", "modification", "otherLicenseUrl", "licenseUrl",
        )
        license_metadata = {key: meta[key] for key in license_keys if key in meta}
    elif isinstance(vrm0, dict):
        vrm_version = "0.x"
        meta = vrm0.get("meta") or {}
        humanoid = vrm0.get("humanoid") or {}
        raw_bones = humanoid.get("humanBones") or []
        bones = tuple(sorted({
            str(item.get("bone")) for item in raw_bones
            if isinstance(item, dict) and item.get("bone")
        }))
        blend_groups = (vrm0.get("blendShapeMaster") or {}).get("blendShapeGroups") or []
        expressions = tuple(sorted({
            str(item.get("presetName") or item.get("name"))
            for item in blend_groups if isinstance(item, dict) and (item.get("presetName") or item.get("name"))
        }))
        springs = []
        license_keys = (
            "allowedUserName", "violentUssageName", "sexualUssageName", "commercialUssageName",
            "otherPermissionUrl", "licenseName", "otherLicenseUrl",
        )
        license_metadata = {key: meta[key] for key in license_keys if key in meta}
    else:
        raise VrmFileError("فایل GLB انتخاب‌شده افزونه VRM 1.0 یا VRM 0.x ندارد.")

    if not bones:
        raise VrmFileError("ساختار Humanoid در مدل پیدا نشد؛ این فایل برای آواتار VRM کامل نیست.")

    authors_raw = meta.get("authors") or meta.get("author") or []
    if isinstance(authors_raw, str):
        authors = (authors_raw,) if authors_raw.strip() else ()
    elif isinstance(authors_raw, list):
        authors = tuple(str(item) for item in authors_raw if str(item).strip())
    else:
        authors = ()

    title = str(meta.get("name") or meta.get("title") or model_path.stem).strip()
    return VrmInfo(
        path=str(model_path),
        size_bytes=model_path.stat().st_size,
        gltf_version=gltf_version,
        vrm_version=vrm_version,
        title=title[:160],
        authors=authors[:20],
        humanoid_bones=bones,
        expressions=expressions,
        spring_bone_groups=len(springs),
        license_metadata=license_metadata,
    )
