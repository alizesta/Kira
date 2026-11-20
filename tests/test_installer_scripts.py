"""Regression checks for Windows installer/update entry points.

These tests are intentionally static so they can run on CI and on Windows without
starting Git, Ollama, PowerShell, or a model download.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.updater = (ROOT / "update_kira.bat").read_text(encoding="utf-8")
        cls.installer = (ROOT / "install.bat").read_text(encoding="utf-8")

    def test_updater_runs_a_stable_copy_before_fetching_and_replacing_itself(self):
        self.assertIn('copy /y "%~f0" "%KIRA_UPDATER_TEMP%"', self.updater)
        self.assertIn('start "Project Kira Updater"', self.updater)
        self.assertLess(
            self.updater.index('copy /y "%~f0" "%KIRA_UPDATER_TEMP%"'),
            self.updater.index('git fetch origin "%BRANCH%"'),
        )

    def test_installer_accepts_only_python_311_or_312(self):
        self.assertIn('if not errorlevel 1 set "PY=.venv\\Scripts\\python.exe"', self.installer)
        self.assertIn('sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)', self.installer)
        self.assertNotIn('if not errorlevel 1 set "PY=python"\n)', self.installer)

    def test_pillow_is_pinned_by_voice_requirements_not_upgraded_unbounded(self):
        self.assertIn('set "PKGS=sounddevice PyAudioWPatch miniaudio"', self.installer)

    def test_updater_and_model_setup_emit_a_traceable_tool_call_stage(self):
        model_setup = (ROOT / "scripts" / "setup_local_chat_model.py").read_text(encoding="utf-8")
        self.assertIn("TOOL_CALL_TEST_TIMEOUT = (20, 300)", model_setup)
        self.assertIn("Running native tool-calling smoke test", model_setup)
        self.assertIn("Native tool-calling smoke test passed", model_setup)
        self.assertNotIn('set "PKGS=Pillow ', self.installer)


if __name__ == "__main__":
    unittest.main()
