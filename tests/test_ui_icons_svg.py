import unittest
from pathlib import Path
from xml.etree import ElementTree


class SvgIconAssetTests(unittest.TestCase):
    def test_every_toolbar_icon_has_an_svg_asset(self):
        root = Path(__file__).resolve().parents[1] / "assets" / "icons"
        for name in (
            "attachment", "brain", "chat", "check", "chevron_up", "energy_bolt",
            "gamepad", "globe", "help", "menu", "mic", "monitor", "moon",
            "palette", "route", "search", "send", "settings", "speaker",
            "speaker_muted", "terminal", "user", "stop",
        ):
            with self.subTest(name=name):
                self.assertTrue((root / f"{name}.svg").is_file())

    def test_all_svg_assets_are_well_formed_xml(self):
        root = Path(__file__).resolve().parents[1] / "assets" / "icons"
        for path in root.glob("*.svg"):
            with self.subTest(path=path.name):
                ElementTree.parse(path)

    def test_every_mood_family_has_an_svg_asset(self):
        root = Path(__file__).resolve().parents[1] / "assets" / "icons"
        for name in ("happy", "soft", "sad", "angry", "curious", "playful",
                     "neutral", "fearful", "disgusted", "bored", "protective", "relieved"):
            with self.subTest(name=name):
                self.assertTrue((root / f"emotion_{name}.svg").is_file())


if __name__ == "__main__":
    unittest.main()
