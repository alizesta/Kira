import unittest
from pathlib import Path

from kira import avatar_art as art


class AvatarArtGeometryTests(unittest.TestCase):
    def test_full_body_picture_is_height_fitted_and_centred(self):
        lay = art.layout(720, 1280)
        ax, ay, aw, ah = lay["art"]
        self.assertAlmostEqual(ah, art.REF_H)
        self.assertAlmostEqual(aw, 720 * art.REF_H / 1280)
        self.assertAlmostEqual(ax, (art.REF_W - aw) / 2)
        self.assertAlmostEqual(ay, 0)

    def test_frame_is_inset_by_the_bleed_so_sway_never_shows_the_edge(self):
        lay = art.layout(720, 1280)
        ax, ay, aw, ah = lay["art"]
        cx, cy, cw, ch = lay["content"]
        self.assertAlmostEqual(cx - ax, art.BLEED)
        self.assertAlmostEqual(cy - ay, art.BLEED)
        self.assertAlmostEqual(aw - cw, 2 * art.BLEED)
        self.assertAlmostEqual(ah - ch, 2 * art.BLEED)
        self.assertAlmostEqual(lay["window_ratio"], ch / cw)

    def test_card_crop_matches_kiras_crop_and_stays_inside_the_frame(self):
        for size in ((720, 1280), (784, 1168), (1000, 1000), (400, 1600)):
            lay = art.layout(*size)
            cx, cy, cw, ch = lay["content"]
            x, y, w, h = lay["card"]
            self.assertGreaterEqual(x, cx - 1e-6)
            self.assertGreaterEqual(y, cy - 1e-6)
            self.assertLessEqual(x + w, cx + cw + 1e-6)
            self.assertLessEqual(y + h, cy + ch + 1e-6)
            self.assertAlmostEqual(w / h, art.CARD_W / art.CARD_H, places=3)
        full = art.layout(720, 1280)["card"]
        self.assertAlmostEqual(full[2], art.CARD_W)
        self.assertAlmostEqual(full[3], art.CARD_H)

    def test_kira_card_uses_the_entire_body_canvas(self):
        self.assertEqual(art.KIRA_CARD, (0.0, 0.0, 832.0, 1248.0))
        self.assertEqual(art.KIRA_CARD[3], art.REF_H)

    def test_invalid_sizes_are_rejected(self):
        with self.assertRaises(ValueError):
            art.layout(0, 100)
        with self.assertRaises(ValueError):
            art.cover_crop(100, 100, 0, 10)

    def test_cover_crop_fills_without_distortion(self):
        for src in ((784, 1168), (720, 1280), (1600, 900), (144, 180)):
            x, y, w, h = art.cover_crop(*src, 144, 180)
            self.assertAlmostEqual(w / h, 144 / 180, places=4)
            self.assertGreaterEqual(x, -1e-9)
            self.assertGreaterEqual(y, -1e-9)
            self.assertLessEqual(x + w, src[0] + 1e-6)
            self.assertLessEqual(y + h, src[1] + 1e-6)

    def test_tall_portrait_crop_keeps_the_face_end(self):
        x, y, w, h = art.cover_crop(784, 1168, 144, 180)
        self.assertLess(y, (1168 - h) / 2 + 1e-6)         # top is trimmed less than the bottom

    def test_shipped_pictures_have_the_expected_sizes(self):
        root = Path(__file__).resolve().parents[1] / "assets" / "characters"
        try:
            from PIL import Image
        except Exception:                                  # pragma: no cover
            self.skipTest("Pillow not installed")
        for cid in ("ren", "mika"):
            with Image.open(root / f"{cid}_portrait.jpg") as im:
                self.assertEqual(im.size, (784, 1168))
            with Image.open(root / f"{cid}_full.png") as im:          # background removed: transparent PNG, same size as the original picture
                self.assertEqual(im.size, (720, 1280))
                self.assertEqual(im.mode, "RGBA")
                self.assertEqual(im.getpixel((2, 2))[3], 0)               # corners are transparent
                self.assertGreater(im.getpixel((im.width // 2, im.height // 2))[3], 200)   # the character itself is opaque


if __name__ == "__main__":
    unittest.main()
