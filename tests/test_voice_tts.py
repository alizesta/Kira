"""Regression tests for the Windows SAPI TTS fallback."""
import unittest

from kira.voice import SAPI_SCRIPT


class SapiTtsTests(unittest.TestCase):
    def test_culture_is_captured_before_synthesizer_is_disposed(self):
        capture = "$culture = $s.Voice.Culture.Name"
        dispose = "$s.Dispose()"
        report = "Write-Output $culture"
        self.assertIn(capture, SAPI_SCRIPT)
        self.assertIn(dispose, SAPI_SCRIPT)
        self.assertIn(report, SAPI_SCRIPT)
        self.assertLess(SAPI_SCRIPT.index(capture), SAPI_SCRIPT.index(dispose))
        self.assertLess(SAPI_SCRIPT.index(dispose), SAPI_SCRIPT.index(report))


if __name__ == "__main__":
    unittest.main()
