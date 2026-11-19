"""Regression tests for the local speech audio cache."""

import hashlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from kira.voice import _atomic_write, _load_cached_audio, _valid_cached_envelope


def _wav_payload(frames=2400, sample_rate=24000):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x10\x00" * frames)
    return output.getvalue()


def _metadata(payload, frames=2400, sample_rate=24000):
    return {
        "version": 1,
        "wav_sha256": hashlib.sha256(payload).hexdigest(),
        "frames": frames,
        "sample_rate": sample_rate,
        "envelope": [0.5, 0.5, 0.5],
    }


class VoiceAudioCacheTests(unittest.TestCase):
    def test_valid_envelope_requires_exact_frame_bucket_count(self):
        self.assertTrue(_valid_cached_envelope([0.5, 0.4, 0.3], 2400, 24000))
        self.assertFalse(_valid_cached_envelope([0.5], 2400, 24000))

    def test_invalid_envelope_values_are_rejected(self):
        self.assertFalse(_valid_cached_envelope([float("nan"), 0.5, 0.3], 2400, 24000))
        self.assertFalse(_valid_cached_envelope([0.2, -0.1, 0.3], 2400, 24000))
        self.assertFalse(_valid_cached_envelope([0.2, 1.1, 0.3], 2400, 24000))

    def test_cache_round_trip_validates_audio_digest_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            wav_path = Path(temp) / "speech.wav"
            meta_path = Path(temp) / "speech.json"
            payload = _wav_payload()
            wav_path.write_bytes(payload)
            meta_path.write_text(json.dumps(_metadata(payload)), encoding="utf-8")

            self.assertEqual(_load_cached_audio(wav_path, meta_path), [0.5, 0.5, 0.5])

            wav_path.write_bytes(_wav_payload(frames=2401))
            self.assertIsNone(_load_cached_audio(wav_path, meta_path))

    def test_cache_rejects_stale_or_invalid_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            wav_path = Path(temp) / "speech.wav"
            meta_path = Path(temp) / "speech.json"
            payload = _wav_payload()
            wav_path.write_bytes(payload)
            record = _metadata(payload)
            record["envelope"] = [0.5]
            meta_path.write_text(json.dumps(record), encoding="utf-8")
            self.assertIsNone(_load_cached_audio(wav_path, meta_path))

    def test_atomic_write_replaces_complete_payload_without_temp_leaks(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "speech.wav"
            target.write_bytes(b"old")
            _atomic_write(str(target), b"new complete audio")
            self.assertEqual(target.read_bytes(), b"new complete audio")
            self.assertEqual([path.name for path in Path(temp).iterdir()], ["speech.wav"])


if __name__ == "__main__":
    unittest.main()

