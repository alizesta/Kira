"""Microphone input: noise handling, pauses, end of speech, barge-in (synthetic audio, no microphone needed) and text clean-up."""
import unittest
from unittest import mock

import numpy as np

from tests import helpers  # noqa: F401
from kira.speech_text import clean_transcript, grace_for, initial_prompt, is_hallucination, merge_text, normalize_fa
from kira.vad import BLOCK, RATE, Segmenter

RNG = np.random.default_rng(1)


def room(n):                                    # quiet hiss + strong 60 Hz hum (fan / mains)
    return (RNG.standard_normal(n) * 0.004 + 0.02 * np.sin(2 * np.pi * 60 * np.arange(n) / RATE)).astype(np.float32)


def voice(n, amp=0.08):
    t = np.arange(n) / RATE
    tone = sum(np.sin(2 * np.pi * f * t + k) for k, f in enumerate((180, 420, 900, 1600))) / 4
    return (amp * tone * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))).astype(np.float32)


def calibrated(sens=100):
    seg = Segmenter(sens)
    while seg.calibrate(room(BLOCK)):
        pass
    return seg


def run(seg, sig, **kw):
    events = []
    for i in range(0, len(sig) - BLOCK + 1, BLOCK):
        events += seg.feed(sig[i:i + BLOCK], **kw)
    return events


def kinds(events):
    return [e[0] for e in events]


class ShenavaOnlyTests(unittest.TestCase):
    def test_listener_transcribes_only_through_shenava(self):
        from kira.listener import Listener
        from kira import local_voice
        listener = Listener(settings={})
        audio = np.zeros(RATE, dtype=np.float32)
        with mock.patch.object(local_voice, "transcribe_shenava", return_value="سلام") as transcribe:
            self.assertEqual(listener._transcribe(None, audio), "سلام")
        transcribe.assert_called_once()
        self.assertEqual(listener.via, "local:shenava")


class LocalASRFallbackTests(unittest.TestCase):
    def test_listener_defaults_to_shenava_as_sole_local_asr(self):
        from kira.listener import Listener
        listener = Listener(settings={})
        self.assertEqual(listener.settings.get("local_voice_asr_backend", "shenava"), "shenava")
        self.assertTrue(callable(listener._transcribe))



class LivePartialRecognitionTests(unittest.TestCase):
    def test_growing_audio_hypotheses_replace_earlier_words(self):
        from kira.listener import Listener

        class ActiveSegment:
            block = BLOCK
            def __init__(self):
                self.buf = [np.zeros(BLOCK, dtype=np.float32) for _ in range(32)]
            def snapshot(self):
                return np.zeros(RATE, dtype=np.float32)

        listener = Listener(settings={})
        emitted = []
        listener.partial_heard.connect(emitted.append)
        segment = ActiveSegment()
        with mock.patch("kira.listener.time.monotonic", side_effect=(10.0, 11.0)):
            with mock.patch.object(listener, "_transcribe", side_effect=("من فردا", "من امروز")):
                listener._maybe_emit_partial(segment, None)
                segment.buf.extend([np.zeros(BLOCK, dtype=np.float32) for _ in range(16)])
                listener._maybe_emit_partial(segment, None)
        self.assertEqual(emitted, ["من فردا", "من امروز"])
        self.assertNotIn("فردا", emitted[-1])

    def test_partial_hypotheses_are_not_emitted_for_recognizer_hallucinations(self):
        from kira.listener import Listener

        class ActiveSegment:
            block = BLOCK
            buf = [np.zeros(BLOCK, dtype=np.float32) for _ in range(32)]
            def snapshot(self):
                return np.zeros(RATE, dtype=np.float32)

        listener = Listener(settings={})
        emitted = []
        listener.partial_heard.connect(emitted.append)
        with mock.patch("kira.listener.time.monotonic", return_value=10.0):
            with mock.patch.object(listener, "_transcribe", return_value="Thanks for watching!"):
                listener._maybe_emit_partial(ActiveSegment(), None)
        self.assertEqual(emitted, [])


class SegmenterTests(unittest.TestCase):
    def test_hum_and_a_click_are_not_speech(self):
        click = np.zeros(4000, dtype=np.float32)
        click[1000:1300] = 0.3
        self.assertEqual(run(calibrated(), np.concatenate([room(RATE), click + room(4000), room(RATE)])), [])

    def test_snapshot_returns_active_audio_without_resetting_segmenter(self):
        segmenter = calibrated()
        signal = voice(RATE) + room(RATE)
        run(segmenter, signal)
        self.assertTrue(segmenter.speaking)
        before = len(segmenter.buf)
        snapshot = segmenter.snapshot()
        self.assertEqual(len(snapshot), before * BLOCK)
        self.assertTrue(segmenter.speaking)
        self.assertEqual(len(segmenter.buf), before)

    def test_sentence_is_found_and_the_trailing_silence_is_trimmed(self):
        ev = run(calibrated(), np.concatenate([room(RATE // 2), voice(RATE * 2) + room(RATE * 2), room(RATE * 2)]))
        self.assertEqual(kinds(ev), ["start", "segment"])
        seconds = len(ev[1][1]) / RATE
        self.assertTrue(2.0 <= seconds <= 3.1, seconds)          # ~2 s of speech + pre-roll + short tail, not the 2 s of silence

    def test_short_pause_is_one_sentence_long_pause_is_two(self):
        def segments(pause):
            sig = np.concatenate([voice(RATE) + room(RATE), room(int(RATE * pause)), voice(RATE) + room(RATE), room(RATE * 2)])
            return kinds(run(calibrated(), sig)).count("segment")
        self.assertEqual(segments(0.4), 1)
        self.assertEqual(segments(1.3), 2)

    def test_lower_sensitivity_ignores_a_quieter_voice(self):
        quiet = np.concatenate([room(RATE // 2), voice(RATE, 0.025) + room(RATE), room(RATE * 2)])
        self.assertIn("segment", kinds(run(calibrated(200), quiet)))
        self.assertNotIn("segment", kinds(run(calibrated(50), quiet)))

    def test_barge_in_only_for_a_voice_louder_than_kiras_echo(self):
        n = RATE * 3
        echo = voice(n, 0.03) + room(n)
        self.assertEqual(run(calibrated(), echo, kira_speaking=True, kira_level=0.5), [])
        person = echo + np.concatenate([np.zeros(RATE * 2, np.float32), voice(RATE, 0.12)])
        self.assertEqual(kinds(run(calibrated(), person, kira_speaking=True, kira_level=0.5))[:2], ["barge", "start"])


class TextTests(unittest.TestCase):
    def test_colloquial_persian_is_tidied(self):
        self.assertEqual(normalize_fa("من می خوام نمی دونم كجا برم"), "من می‌خوام نمی‌دونم کجا برم")
        self.assertEqual(normalize_fa("اسلامی  است"), "اسلامی است")        # "...می" at the end of a word is untouched

    def test_invented_text_is_dropped(self):
        for text in ("زیرنویس توسط جامعه امارا", "Thanks for watching!", "بله بله بله بله", "...", ""):
            self.assertTrue(is_hallucination(text), text)
        self.assertFalse(is_hallucination("ساعت چنده؟"))
        self.assertEqual(clean_transcript("زیرنویس"), "")

    def test_pause_grace_depends_on_how_the_sentence_ends(self):
        self.assertLess(grace_for("ساعت چنده؟"), grace_for("ساعت چنده"))
        self.assertLess(grace_for("ساعت چنده"), grace_for("می‌خوام بدونم که"))
        self.assertGreater(grace_for("آره،"), grace_for("آره."))
        self.assertEqual(merge_text("اگه فردا", "هوا خوب بود"), "اگه فردا هوا خوب بود")

    def test_prompt_is_colloquial_for_persian(self):
        self.assertIn("می‌خوام", initial_prompt("fa"))
        self.assertTrue(initial_prompt("fa").startswith("کیرا"))


class SpeechFixesTests(unittest.TestCase):
    def make(self, data):
        import json
        import tempfile
        from pathlib import Path
        from kira.speech_fixes import SpeechFixes
        path = Path(tempfile.mkdtemp()) / "speech_fixes.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        fixes = SpeechFixes(path)
        fixes.refresh()
        return fixes

    def test_whole_word_fixes_and_hotwords(self):
        fixes = self.make({"hotwords": ["اهواز"], "replace": {"چطورین": "چطورید", "من میرم": "من می‌رم"}})
        self.assertEqual(clean_transcript("سلام چطورین؟ من میرم اهواز", "fa", fixes), "سلام چطورید؟ من می‌رم اهواز")
        self.assertEqual(fixes.hotwords_text(), "اهواز")
        self.assertIn("اهواز", initial_prompt("fa", fixes.hotwords_text()))

    def test_part_of_a_longer_word_is_not_replaced(self):
        fixes = self.make({"replace": {"را": "X"}})
        self.assertEqual(fixes.apply("کیرا را دیدم"), "کیرا X دیدم")

    def test_broken_file_keeps_last_good_content_and_never_raises(self):
        fixes = self.make({"replace": {"الف": "ب"}})
        fixes.path.write_text("{not json", encoding="utf-8")
        import os
        os.utime(fixes.path, (9999999999, 9999999999))
        fixes.refresh()
        self.assertTrue(fixes.error)
        self.assertEqual(fixes.apply("الف"), "ب")

    def test_example_file_is_created_but_never_overwritten(self):
        from pathlib import Path
        import tempfile
        from kira.speech_fixes import SpeechFixes
        path = Path(tempfile.mkdtemp()) / "x.json"
        SpeechFixes(path).ensure_file()
        self.assertIn("hotwords", path.read_text(encoding="utf-8"))
        path.write_text("{}", encoding="utf-8")
        SpeechFixes(path).ensure_file()
        self.assertEqual(path.read_text(encoding="utf-8"), "{}")

    def test_voice_note_only_for_spoken_messages(self):
        from kira.personality import build_system_prompt
        self.assertIn("SPOKEN", build_system_prompt({}, voice_input=True))
        self.assertNotIn("SPOKEN", build_system_prompt({}))


if __name__ == "__main__":
    unittest.main()
