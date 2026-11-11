from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from kira.vrm.metadata import VrmFileError, inspect_vrm
from kira.characters.registry import _normalise_profile


def write_glb(path: Path, document: dict) -> None:
    payload = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(payload)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def vrm1_document() -> dict:
    return {
        "asset": {"version": "2.0", "generator": "Ai1 VRM unit test"},
        "extensionsUsed": ["VRMC_vrm", "VRMC_springBone"],
        "extensions": {
            "VRMC_vrm": {
                "meta": {
                    "name": "Kira Test",
                    "authors": ["Local creator"],
                    "avatarPermission": "onlyAuthor",
                    "modification": "prohibited",
                    "commercialUsage": "personalNonProfit",
                },
                "humanoid": {
                    "humanBones": {
                        "hips": {"node": 0},
                        "spine": {"node": 1},
                        "head": {"node": 2},
                    }
                },
                "expressions": {
                    "preset": {"blink": {}, "aa": {}, "happy": {}},
                    "custom": {"smile_soft": {}},
                },
            },
            "VRMC_springBone": {"springs": [{"name": "hair"}]},
        },
        "nodes": [{"name": "Hips"}, {"name": "Spine"}, {"name": "Head"}],
    }


class VrmMetadataTests(unittest.TestCase):
    def test_inspects_vrm_1_humanoid_expressions_and_license_without_rewriting(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "kira.vrm"
            original = vrm1_document()
            write_glb(path, original)
            before = path.read_bytes()

            info = inspect_vrm(path)

            self.assertEqual(info.vrm_version, "1.0")
            self.assertEqual(info.title, "Kira Test")
            self.assertEqual(info.authors, ("Local creator",))
            self.assertEqual(set(info.humanoid_bones), {"hips", "spine", "head"})
            self.assertEqual(set(info.expressions), {"blink", "aa", "happy", "smile_soft"})
            self.assertEqual(info.spring_bone_groups, 1)
            self.assertEqual(info.license_metadata["avatarPermission"], "onlyAuthor")
            self.assertEqual(path.read_bytes(), before)

    def test_rejects_a_plain_glb_without_vrm_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ordinary.vrm"
            write_glb(path, {"asset": {"version": "2.0"}, "nodes": []})
            with self.assertRaises(VrmFileError):
                inspect_vrm(path)

    def test_rejects_invalid_glb_header(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.vrm"
            path.write_bytes(b"not a GLB")
            with self.assertRaises(VrmFileError):
                inspect_vrm(path)

    def test_rejects_vrm_without_humanoid_bones(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "no-rig.vrm"
            document = vrm1_document()
            document["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"] = {}
            write_glb(path, document)
            with self.assertRaises(VrmFileError):
                inspect_vrm(path)

    def test_character_profile_keeps_a_private_avatar_path_and_migrates_old_profiles(self):
        old = _normalise_profile({"id": "kira", "name": "Kira"})
        self.assertEqual(old["avatar_model_path"], "")
        selected = _normalise_profile({
            "id": "kira",
            "name": "Kira",
            "avatar_model_path": r"C:\Users\Local\AppData\Kira\characters\kira\avatar.vrm",
        })
        self.assertEqual(selected["avatar_model_path"], r"C:\Users\Local\AppData\Kira\characters\kira\avatar.vrm")


if __name__ == "__main__":
    unittest.main()
