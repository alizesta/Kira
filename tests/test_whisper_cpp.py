"""Regression tests for the managed whisper.cpp Vulkan backend."""

import io
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from kira import whisper_cpp


class WhisperCppAudioTests(unittest.TestCase):
    def test_wav_bytes_are_mono_pcm16_at_requested_rate(self):
        payload = whisper_cpp._wav_bytes(np.array([-1.0, 0.0, 1.0], dtype=np.float32), 16000)
        with wave.open(io.BytesIO(payload), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnframes(), 3)
            samples = np.frombuffer(wav.readframes(3), dtype="<i2")
        self.assertEqual(samples[0], -32767)
        self.assertEqual(samples[1], 0)
        self.assertEqual(samples[2], 32767)

    def test_wav_bytes_reject_empty_audio_and_invalid_sample_rate(self):
        with self.assertRaises(ValueError):
            whisper_cpp._wav_bytes(np.zeros(0, dtype=np.float32), 16000)
        with self.assertRaises(ValueError):
            whisper_cpp._wav_bytes(np.ones(4, dtype=np.float32), 1000)

    def test_response_parser_supports_text_and_segment_payloads(self):
        self.assertEqual(
            whisper_cpp.parse_transcription_response({"text": "  سلام   دنیا  "}),
            "سلام دنیا",
        )
        self.assertEqual(
            whisper_cpp.parse_transcription_response(
                {"segments": [{"text": "سلام"}, {"text": " دنیا"}]}
            ),
            "سلام دنیا",
        )
        self.assertEqual(whisper_cpp.parse_transcription_response([]), "")

    def test_runtime_extractor_accepts_only_pinned_runtime_filenames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "runtime.zip"
            destination = root / "runtime"
            with zipfile.ZipFile(archive, "w") as bundle:
                for name in whisper_cpp.RUNTIME_FILES:
                    bundle.writestr(f"release/bin/{name}", b"verified-test-binary")
                bundle.writestr("release/README.txt", b"not installed")
            whisper_cpp._extract_runtime(archive, destination)
            self.assertEqual(
                {path.name for path in destination.iterdir()},
                set(whisper_cpp.RUNTIME_FILES),
            )

    def test_runtime_extractor_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "runtime.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../../whisper-server.exe", b"malicious")
            with self.assertRaises(RuntimeError):
                whisper_cpp._extract_runtime(archive, root / "runtime")


class WhisperCppInstallTests(unittest.TestCase):
    def test_download_verification_rejects_wrong_digest_and_removes_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "payload.bin"

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def raise_for_status(self):
                    return None

                def iter_content(self, chunk_size):
                    yield b"untrusted"

            with patch("requests.get", return_value=FakeResponse()):
                with self.assertRaises(RuntimeError):
                    whisper_cpp._download_verified(
                        "https://example.invalid/payload", target, "0" * 64
                    )
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".part").exists())


if __name__ == "__main__":
    unittest.main()
