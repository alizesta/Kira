"""Regression tests for discovering cached local Piper voices."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import local_voice


class LocalVoiceDiscoveryTests(unittest.TestCase):
    def test_mana_piper_snapshot_is_listed_with_snapshot_path(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            snapshot = (
                cache / "models--MahtaFetrat--Mana-Persian-Piper"
                / "snapshots" / "ad9dd8518bedf517bd7cbc9f63b8e5c844bf5bc0"
            )
            snapshot.mkdir(parents=True)
            model = snapshot / "fa_IR-mana-medium.onnx"
            model.write_bytes(b"test model")
            Path(str(model) + ".json").write_text("{}", encoding="utf-8")

            with mock.patch.dict(os.environ, {"HF_HUB_CACHE": str(cache)}):
                discovered = local_voice.discover_cached_models()

            matches = [item for item in discovered["tts"] if item["path"] == str(model)]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["name"], "Mana Persian Piper")
            self.assertEqual(matches[0]["repo_id"], "MahtaFetrat/Mana-Persian-Piper")
            self.assertFalse(str(matches[0]["path"]).endswith("blobs"))


if __name__ == "__main__":
    unittest.main()
