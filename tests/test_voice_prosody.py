"""Pure regression tests for emotion-aware Persian speech prosody."""

import io
import unittest
import wave
from unittest import mock

import numpy as np

from kira.voice_prosody import (
    EMOTION_PROFILES, NEUTRAL, apply_audio_effects, expand_persian_numbers,
    join_wavs_with_pauses, resolve_prosody, split_comma_clauses,
)


def _wav(samples, rate=24000):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return stream.getvalue()


class EmotionProsodyTests(unittest.TestCase):
    def test_every_emotional_runtime_label_has_a_voice_profile(self):
        from kira.emotion.runtime import EMOTIONS
        self.assertEqual(set(EMOTION_PROFILES), EMOTIONS)
        for profile in EMOTION_PROFILES.values():
            self.assertEqual(set(profile), set(NEUTRAL))

    def test_intensity_zero_is_neutral_and_emotion_profiles_are_bounded(self):
        self.assertEqual({key: resolve_prosody(["sad"], 0)[key] for key in NEUTRAL}, NEUTRAL)
        for emotion in EMOTION_PROFILES:
            profile = resolve_prosody([emotion], 100)
            self.assertGreaterEqual(profile["length_scale"], 0.82)
            self.assertLessEqual(profile["length_scale"], 1.22)
            self.assertGreaterEqual(profile["noise_scale"], 0.5)
            self.assertLessEqual(profile["noise_scale"], 0.9)
            self.assertGreaterEqual(profile["pitch_semitones"], -0.55)
            self.assertLessEqual(profile["pitch_semitones"], 0.55)

    def test_sad_speaks_slower_and_quieter_than_excited(self):
        sad = resolve_prosody(["sad"], 100)
        excited = resolve_prosody(["excited"], 100)
        self.assertGreater(sad["length_scale"], NEUTRAL["length_scale"])
        self.assertLess(excited["length_scale"], NEUTRAL["length_scale"])
        self.assertLess(sad["gain_db"], excited["gain_db"])
        self.assertGreater(sad["pause_sentence_ms"], excited["pause_sentence_ms"])

    def test_secondary_emotion_is_blended_without_exceeding_bounds(self):
        profile = resolve_prosody(["happy", "sad"], 80)
        self.assertEqual(profile["emotion_ids"], ("happy", "sad"))
        self.assertGreaterEqual(profile["length_scale"], 0.82)
        self.assertLessEqual(profile["length_scale"], 1.22)

    def test_comma_clause_split_preserves_punctuation_and_text(self):
        self.assertEqual(split_comma_clauses("سلام، خوبی؟ بعداً می‌بینمت؛ فعلاً"),
                         ["سلام،", "خوبی؟ بعداً می‌بینمت؛", "فعلاً"])
        self.assertEqual(split_comma_clauses("مبلغ 1,000 تومان"), ["مبلغ 1,000 تومان"])

    def test_wav_join_inserts_requested_silence(self):
        first, second = _wav([1000] * 10, 1000), _wav([2000] * 10, 1000)
        joined = join_wavs_with_pauses([(first, 100), (second, 0)])
        with wave.open(io.BytesIO(joined), "rb") as result:
            self.assertEqual(result.getnframes(), 120)
            samples = np.frombuffer(result.readframes(120), dtype="<i2")
        self.assertTrue(np.all(samples[:10] == 1000))
        self.assertTrue(np.all(samples[10:110] == 0))
        self.assertTrue(np.all(samples[110:] == 2000))

    def test_wav_join_rejects_inconsistent_sample_rates(self):
        with self.assertRaises(ValueError):
            join_wavs_with_pauses([(_wav([1] * 10, 1000), 0), (_wav([1] * 10, 2000), 0)])

    def test_gain_postprocessing_changes_loudness_without_invalidating_wav(self):
        source = _wav([10000] * 100, 24000)
        result = apply_audio_effects(source, {"gain_db": 1.0, "pitch_semitones": 0})
        with wave.open(io.BytesIO(result), "rb") as audio:
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        self.assertGreater(float(np.mean(np.abs(samples))), 10000)
        self.assertEqual(len(samples), 100)

    def test_pitch_postprocessing_uses_subtle_duration_compensated_ffmpeg_filter(self):
        from types import SimpleNamespace

        source = _wav([1000] * 100, 24000)
        with mock.patch("kira.voice_prosody.shutil.which", return_value="ffmpeg"):
            with mock.patch(
                "kira.voice_prosody.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=source),
            ) as run:
                result = apply_audio_effects(
                    source, {"gain_db": 0, "pitch_semitones": 0.4}
                )
        self.assertEqual(result, source)
        command = run.call_args.args[0]
        audio_filter = command[command.index("-af") + 1]
        self.assertIn("asetrate=", audio_filter)
        self.assertIn("atempo=", audio_filter)
        self.assertEqual(run.call_args.kwargs["timeout"], 8)

    def test_pitch_postprocessing_gracefully_skips_when_ffmpeg_is_missing(self):
        source = _wav([1000] * 100, 24000)
        with mock.patch("kira.voice_prosody.shutil.which", return_value=None):
            self.assertEqual(apply_audio_effects(source, {"gain_db": 0, "pitch_semitones": 0.4}), source)

    def test_persian_numbers_and_jalali_dates_are_spoken_as_words(self):
        self.assertEqual(expand_persian_numbers("۳ تا کتاب"), "سه تا کتاب")
        self.assertEqual(expand_persian_numbers("تاریخ ۱۴۰۵/۰۸/۲۸"),
                         "تاریخ بیست و هشتم آبان هزار و چهارصد و پنج")
        self.assertEqual(expand_persian_numbers("Version 3.5"), "Version 3.5")
        self.assertEqual(expand_persian_numbers("Version ۳.۵"), "Version ۳.۵")
        self.assertEqual(expand_persian_numbers("کارت RX 6600 XT"), "کارت RX 6600 XT")
        self.assertEqual(expand_persian_numbers("قیمت 12.5"), "قیمت دوازده ممیز پنج")
        self.assertEqual(expand_persian_numbers("تاریخ 2026-11-19"),
                         "تاریخ نوزدهم نوامبر دو هزار و بیست و شش")
        self.assertEqual(expand_persian_numbers("ساعت 18:30"), "ساعت هجده و سی دقیقه")


if __name__ == "__main__":
    unittest.main()
