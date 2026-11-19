"""Persian TTS text normalization regression tests."""

import unittest

from kira.local_voice import normalize_persian_tts_text


class PersianTtsTextTests(unittest.TestCase):
    def test_arabic_letter_variants_are_normalized(self):
        self.assertEqual(normalize_persian_tts_text("كتاب يكي"), "کتاب یکی")

    def test_formatting_controls_and_tatweel_are_removed(self):
        self.assertEqual(
            normalize_persian_tts_text("سـلام\u200f\u200b دنیا"),
            "سلام دنیا",
        )

    def test_zwnj_is_preserved_and_common_prefixes_are_joined(self):
        self.assertEqual(
            normalize_persian_tts_text("من می روم و نمی خواهم"),
            "من می‌روم و نمی‌خواهم",
        )

    def test_persian_plural_and_comparative_suffixes_are_joined(self):
        self.assertEqual(
            normalize_persian_tts_text("کتاب ها و سریع تر"),
            "کتاب‌ها و سریع‌تر",
        )

    def test_common_technical_terms_get_persian_pronunciation(self):
        self.assertEqual(
            normalize_persian_tts_text("مدل ChatGPT روی GPU و RAM اجرا می شود؟"),
            "مدل چت‌جی‌پی‌تی روی جی‌پی‌یو و رَم اجرا می‌شود؟",
        )

    def test_voice_engine_and_provider_names_get_readable_pronunciation(self):
        self.assertEqual(
            normalize_persian_tts_text(
                "Whisper.cpp Vulkan با Qwen3-ASR و OpenRouter و FFmpeg"
            ),
            "ویسپر دات سی‌پلاس‌پلاس وولکان با کوئن سه اِی‌اِس‌آر و اوپن‌روتر و اِف‌اِف‌اِم‌پِگ",
        )

    def test_english_only_text_is_not_rewritten(self):
        source = "Use ChatGPT, GPU and RAM."
        self.assertEqual(normalize_persian_tts_text(source), source)

    def test_persian_punctuation_is_normalized(self):
        self.assertEqual(
            normalize_persian_tts_text("سلام, خوبی? بله; ممنون"),
            "سلام، خوبی؟ بله؛ ممنون",
        )

    def test_normalization_is_idempotent(self):
        source = "كتاب ها، ChatGPT می رود؟"
        normalized = normalize_persian_tts_text(source)
        self.assertEqual(normalize_persian_tts_text(normalized), normalized)


if __name__ == "__main__":
    unittest.main()
