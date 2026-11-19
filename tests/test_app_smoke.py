import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).with_name("_app_smoke_runner.py")


class RealApplicationSmokeTest(unittest.TestCase):
    def test_application_starts_and_every_tab_button_is_usable(self):
        with tempfile.TemporaryDirectory() as data_dir:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", KIRA_DATA_DIR=data_dir)
            result = subprocess.run([sys.executable, str(RUNNER)], env=env, capture_output=True,
                                    text=True, timeout=240)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output[-3000:])
        marker = [line for line in result.stdout.splitlines() if line.startswith("APP_SMOKE_ERRORS")]
        self.assertTrue(marker, output[-3000:])
        self.assertEqual(marker[0], "APP_SMOKE_ERRORS 0", output[-3000:])


if __name__ == "__main__":
    unittest.main()
