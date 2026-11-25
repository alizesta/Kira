"""Unit tests for Gemini Live credential selection and device resolution."""
import unittest

from kira.gemini_live import LiveVideoFrameGate, resolve_google_api_key, _device_index


class _AudioDevices:
    @staticmethod
    def query_devices():
        return [
            {"name": "USB Headset", "max_input_channels": 1, "max_output_channels": 2},
            {"name": "HDMI Display", "max_input_channels": 0, "max_output_channels": 2},
        ]


class _DuplicateAudioDevices:
    @staticmethod
    def query_devices():
        return [
            {"name": "USB Headset", "hostapi": 0, "max_input_channels": 1},
            {"name": "USB Headset", "hostapi": 1, "max_input_channels": 1},
        ]

    @staticmethod
    def query_hostapis():
        return [{"name": "MME"}, {"name": "Windows WASAPI"}]


class _Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


class GeminiLiveTests(unittest.TestCase):
    def test_live_video_gate_limits_valid_jpeg_to_one_fps(self):
        clock = _Clock()
        gate = LiveVideoFrameGate(clock=clock)
        jpeg = b"\xff\xd8sample-frame\xff\xd9"
        self.assertTrue(gate.accept(jpeg))
        self.assertFalse(gate.accept(jpeg))
        clock.value += 0.999
        self.assertFalse(gate.accept(jpeg))
        clock.value += 0.002
        self.assertTrue(gate.accept(jpeg))

    def test_live_video_gate_rejects_invalid_and_oversized_frames(self):
        gate = LiveVideoFrameGate(max_bytes=12, clock=_Clock())
        self.assertFalse(gate.accept(b""))
        self.assertFalse(gate.accept(b"not-a-jpeg"))
        self.assertFalse(gate.accept(b"\xff\xd8" + b"x" * 20 + b"\xff\xd9"))

    def test_live_video_gate_reset_allows_immediate_next_frame(self):
        gate = LiveVideoFrameGate(clock=_Clock())
        jpeg = b"\xff\xd8sample\xff\xd9"
        self.assertTrue(gate.accept(jpeg))
        self.assertFalse(gate.accept(jpeg))
        gate.reset()
        self.assertTrue(gate.accept(jpeg))

    def test_selected_google_connection_key_is_used(self):
        settings = {
            "providers": {
                "google-ai": {"service": "google", "api_key": "google-secret"},
                "openrouter": {"service": "openrouter", "api_key": "other-secret"},
            }
        }
        self.assertEqual(resolve_google_api_key(settings, "google-ai"), "google-secret")

    def test_selected_missing_connection_does_not_leak_another_provider_key(self):
        settings = {
            "providers": {
                "google-ai": {"service": "google", "api_key": "google-secret"},
                "openrouter": {"service": "openrouter", "api_key": "other-secret"},
            }
        }
        self.assertEqual(resolve_google_api_key(settings, "deleted-google"), "")

    def test_selected_google_connection_with_empty_key_does_not_use_another_account(self):
        settings = {
            "providers": {
                "selected-google": {"service": "google", "api_key": ""},
                "other-google": {"service": "google", "api_key": "other-secret"},
            }
        }
        self.assertEqual(resolve_google_api_key(settings, "selected-google"), "")

    def test_auto_selection_only_uses_google_service_or_google_endpoint(self):
        settings = {
            "providers": {
                "openrouter": {"service": "openrouter", "api_key": "wrong"},
                "custom-google": {
                    "base_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "google-secret",
                },
            }
        }
        self.assertEqual(resolve_google_api_key(settings), "google-secret")

    def test_missing_google_key_returns_empty(self):
        self.assertEqual(resolve_google_api_key({"providers": {}}), "")

    def test_selected_audio_device_is_resolved_by_direction(self):
        self.assertEqual(
            _device_index(_AudioDevices, "USB Headset", input_device=True), 0
        )
        self.assertEqual(
            _device_index(_AudioDevices, "HDMI Display", input_device=False), 1
        )

    def test_missing_selected_audio_device_uses_system_default(self):
        self.assertIsNone(
            _device_index(_AudioDevices, "Missing Headset", input_device=True)
        )


    def test_gemini_live_uses_the_host_api_selected_in_voice_settings(self):
        from kira.audio_devices import input_device_entries

        entries = input_device_entries(_DuplicateAudioDevices)
        wasapi = next(entry for entry in entries if entry["hostapi"] == "Windows WASAPI")
        self.assertEqual(
            _device_index(_DuplicateAudioDevices, wasapi["value"], input_device=True),
            1,
        )


if __name__ == "__main__":
    unittest.main()
