"""Tests for stable PortAudio microphone identities across Windows host APIs."""
import unittest

from kira.audio_devices import input_device_entries, resolve_input_device


class _SoundDevice:
    @staticmethod
    def query_devices():
        return [
            {"name": "Headset (B20)", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 2},
            {"name": "Speakers", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Headset (B20)", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 2},
        ]

    @staticmethod
    def query_hostapis():
        return [{"name": "MME"}, {"name": "Windows WASAPI"}]


class _SoundDeviceWithWasapiDefault(_SoundDevice):
    class default:
        device = (2, 0)


class _ReorderedSoundDevice:
    @staticmethod
    def query_devices():
        return [
            {"name": "Speakers", "hostapi": 0, "max_input_channels": 0},
            {"name": "Headset (B20)", "hostapi": 1, "max_input_channels": 1},
            {"name": "Headset (B20)", "hostapi": 0, "max_input_channels": 1},
        ]

    @staticmethod
    def query_hostapis():
        return [{"name": "MME"}, {"name": "Windows WASAPI"}]


class AudioDeviceSelectionTests(unittest.TestCase):
    def test_same_name_input_endpoints_are_not_collapsed(self):
        entries = input_device_entries(_SoundDevice)
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            [entry["label"] for entry in entries],
            ["Headset (B20) — MME", "Headset (B20) — Windows WASAPI"],
        )
        self.assertNotEqual(entries[0]["value"], entries[1]["value"])

    def test_saved_host_api_identity_selects_the_correct_duplicate(self):
        entries = input_device_entries(_SoundDevice)
        wasapi = next(entry for entry in entries if entry["hostapi"] == "Windows WASAPI")
        self.assertEqual(resolve_input_device(_SoundDevice, wasapi["value"]), 2)

    def test_host_api_identity_survives_device_index_reordering(self):
        entries = input_device_entries(_SoundDevice)
        wasapi = next(entry for entry in entries if entry["hostapi"] == "Windows WASAPI")
        self.assertEqual(resolve_input_device(_ReorderedSoundDevice, wasapi["value"]), 1)

    def test_legacy_name_only_setting_remains_supported(self):
        self.assertEqual(resolve_input_device(_SoundDevice, "Headset (B20)"), 0)

    def test_legacy_name_setting_prefers_the_current_system_default_endpoint(self):
        self.assertEqual(
            resolve_input_device(_SoundDeviceWithWasapiDefault, "Headset (B20)"),
            2,
        )

    def test_empty_or_disconnected_selection_uses_system_default(self):
        self.assertIsNone(resolve_input_device(_SoundDevice, ""))
        self.assertIsNone(resolve_input_device(_SoundDevice, "Headset removed"))


if __name__ == "__main__":
    unittest.main()
