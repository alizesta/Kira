"""Unit tests for Gemini Live credential selection and device resolution."""
import unittest

from kira.gemini_live import resolve_google_api_key, _device_index


class _AudioDevices:
    @staticmethod
    def query_devices():
        return [
            {"name": "USB Headset", "max_input_channels": 1, "max_output_channels": 2},
            {"name": "HDMI Display", "max_input_channels": 0, "max_output_channels": 2},
        ]


class GeminiLiveTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
