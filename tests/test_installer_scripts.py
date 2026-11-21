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
        self.assertIn('call "%KIRA_UPDATER_TEMP%" %*', self.updater)
        self.assertLess(
            self.updater.index('copy /y "%~f0" "%KIRA_UPDATER_TEMP%"'),
            self.updater.index('git fetch --no-tags origin'),
        )

    def test_updater_disables_git_pagers_for_noninteractive_file_listing(self):
        self.assertIn('set "GIT_PAGER=cat"', self.updater)
        self.assertIn('set "GIT_TERMINAL_PROMPT=0"', self.updater)
        self.assertIn('git --no-pager diff --name-status "%BRANCH%" "origin/%BRANCH%"', self.updater)
        self.assertIn('git --no-pager diff --name-only "%BRANCH%" "origin/%BRANCH%"', self.updater)
    def test_updater_verifies_files_are_synchronized_before_reporting_success(self):
        self.assertIn('git diff --quiet HEAD "origin/%BRANCH%"', self.updater)
        self.assertIn("echo [FILES] All changed project files are now applied and verified.", self.updater)
        self.assertIn("echo [DONE] Project files are synchronized with origin/%BRANCH%.", self.updater)
        self.assertIn(":sync_fail", self.updater)
        self.assertLess(
            self.updater.index('git diff --quiet HEAD "origin/%BRANCH%"'),
            self.updater.index("echo [OK] Incremental update completed successfully."),
        )

    def test_installer_never_installs_or_starts_ollama_or_downloads_chat_models(self):
        self.assertIn("Ollama model installation is currently disabled", self.installer)
        self.assertNotIn("Ollama.Ollama", self.installer)
        self.assertNotIn("ollama serve", self.installer)
        self.assertNotIn("setup_local_chat_model.py", self.installer)
        self.assertNotIn("OLLAMA_MODELS", self.installer)

    def test_updater_does_not_trigger_install_for_optional_ollama_model_script(self):
        self.assertNotIn('if /I "%%F"=="scripts/setup_local_chat_model.py" set "NEEDS_INSTALL=1"', self.updater)
        self.assertNotIn("KIRA_SKIP_OLLAMA_MODEL_DOWNLOAD", self.updater)

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
