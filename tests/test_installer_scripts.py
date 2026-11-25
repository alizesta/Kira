"""Regression checks for Windows installer/update entry points."""
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

    def test_installer_generates_all_hash_locks_before_installing_dependencies(self):
        uv_install = 'python -m pip install --upgrade uv --retries 10 --timeout 60'
        generate = 'python scripts\\generate_dependency_locks.py --uv ".venv\\Scripts\\uv.exe"'
        core_install = 'python install_deps.py requirements.txt --constraints constraints.txt'
        self.assertIn(uv_install, self.installer)
        self.assertIn(generate, self.installer)
        self.assertIn('if errorlevel 1 goto netfail', self.installer)
        self.assertLess(self.installer.index(uv_install), self.installer.index(generate))
        self.assertLess(self.installer.index(generate), self.installer.index(core_install))
        self.assertIn('if defined KIRA_PYPI_INDEX', self.installer)

    def test_updater_triggers_dependency_setup_when_lock_generator_or_lock_files_change(self):
        self.assertIn('if /I "%%F"=="scripts/generate_dependency_locks.py" set "NEEDS_INSTALL=1"', self.updater)
        self.assertIn(r'^dependency-locks/.*\.txt        self.assertIn("python -m kira.setup_manager --interactive", self.installer)
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

    def test_optional_audio_group_uses_the_shared_dependency_resolver(self):
        self.assertIn(
            "python install_deps.py requirements-audio.txt --constraints constraints.txt",
            self.installer,
        )
        self.assertNotIn("for %%P in (%PKGS%) do", self.installer)
        self.assertNotIn("python -m pip install --upgrade --retries 10 --timeout 60 %%P", self.installer)

    def test_runtime_dependencies_are_grouped_and_dev_tools_stay_out_of_core(self):
        core = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        development = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        self.assertIn("ruff", development)
        for optional in ("psutil", "dxcam", "hf_xet"):
            self.assertNotIn(optional, core)
        for group in (
            "requirements-audio.txt",
            "requirements-ocr.txt",
            "requirements-system-optional.txt",
        ):
            self.assertIn(f"install_deps.py {group}", self.installer)

    def test_dependency_installation_preflights_and_checks_the_full_graph(self):
        installer = (ROOT / "install_deps.py").read_text(encoding="utf-8")
        self.assertIn('"--dry-run"', installer)
        self.assertIn('"--report"', installer)
        self.assertIn('[sys.executable, "-m", "pip", "check"]', (ROOT / "kira" / "local_voice.py").read_text(encoding="utf-8"))
        self.assertNotIn("for requirement in requirements", installer)
        self.assertIn("upgrade: bool = False", installer)

    def test_voice_setup_uses_shared_constraints_and_does_not_upgrade_by_default(self):
        setup = (ROOT / "scripts" / "setup_local_voice.py").read_text(encoding="utf-8")
        self.assertIn('"constraints.txt"', setup)
        self.assertIn('"constraints-voice.txt"', setup)
        self.assertIn("install_deps.py", setup)
        self.assertIn("str(REQ)", setup)
        self.assertNotIn('"--upgrade"', setup)

    def test_kitten_dependencies_are_explicit_and_keep_the_onnx_install_path(self):
        engine = (ROOT / "requirements-voice-kitten-engine.txt").read_text(encoding="utf-8")
        runtime = (ROOT / "requirements-voice-kitten.txt").read_text(encoding="utf-8")
        source = (ROOT / "kira" / "kitten_tts.py").read_text(encoding="utf-8")
        self.assertIn("kittenml", engine)
        self.assertIn("onnxruntime", runtime)
        self.assertIn('extra_args=("--no-deps",)', source)
        self.assertNotIn("torch", runtime.casefold())
        self.assertIn("requirements-voice-kitten.txt", source)

    def test_updater_reinstalls_when_constraint_files_change(self):
        self.assertIn(r'^constraints.*\.txt$', self.updater)

    def test_updater_and_model_setup_emit_a_traceable_tool_call_stage(self):
        model_setup = (ROOT / "scripts" / "setup_local_chat_model.py").read_text(encoding="utf-8")
        self.assertIn("TOOL_CALL_TEST_TIMEOUT = (20, 300)", model_setup)
        self.assertIn("Running native tool-calling smoke test", model_setup)
        self.assertIn("Native tool-calling smoke test passed", model_setup)
        self.assertNotIn('set "PKGS=Pillow ', self.installer)


if __name__ == "__main__":
    unittest.main()
, self.updater)

    def test_installer_keeps_ollama_setup_separate_from_python_dependency_groups(self):
        self.assertIn("python -m kira.setup_manager --interactive", self.installer)
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

    def test_optional_audio_group_uses_the_shared_dependency_resolver(self):
        self.assertIn(
            "python install_deps.py requirements-audio.txt --constraints constraints.txt",
            self.installer,
        )
        self.assertNotIn("for %%P in (%PKGS%) do", self.installer)
        self.assertNotIn("python -m pip install --upgrade --retries 10 --timeout 60 %%P", self.installer)

    def test_runtime_dependencies_are_grouped_and_dev_tools_stay_out_of_core(self):
        core = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        development = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        self.assertIn("ruff", development)
        for optional in ("psutil", "dxcam", "hf_xet"):
            self.assertNotIn(optional, core)
        for group in (
            "requirements-audio.txt",
            "requirements-ocr.txt",
            "requirements-system-optional.txt",
        ):
            self.assertIn(f"install_deps.py {group}", self.installer)

    def test_dependency_installation_preflights_and_checks_the_full_graph(self):
        installer = (ROOT / "install_deps.py").read_text(encoding="utf-8")
        self.assertIn('"--dry-run"', installer)
        self.assertIn('"--report"', installer)
        self.assertIn('[sys.executable, "-m", "pip", "check"]', (ROOT / "kira" / "local_voice.py").read_text(encoding="utf-8"))
        self.assertNotIn("for requirement in requirements", installer)
        self.assertIn("upgrade: bool = False", installer)

    def test_voice_setup_uses_shared_constraints_and_does_not_upgrade_by_default(self):
        setup = (ROOT / "scripts" / "setup_local_voice.py").read_text(encoding="utf-8")
        self.assertIn('"constraints.txt"', setup)
        self.assertIn('"constraints-voice.txt"', setup)
        self.assertIn("install_deps.py", setup)
        self.assertIn("str(REQ)", setup)
        self.assertNotIn('"--upgrade"', setup)

    def test_kitten_dependencies_are_explicit_and_keep_the_onnx_install_path(self):
        engine = (ROOT / "requirements-voice-kitten-engine.txt").read_text(encoding="utf-8")
        runtime = (ROOT / "requirements-voice-kitten.txt").read_text(encoding="utf-8")
        source = (ROOT / "kira" / "kitten_tts.py").read_text(encoding="utf-8")
        self.assertIn("kittenml", engine)
        self.assertIn("onnxruntime", runtime)
        self.assertIn('extra_args=("--no-deps",)', source)
        self.assertNotIn("torch", runtime.casefold())
        self.assertIn("requirements-voice-kitten.txt", source)

    def test_updater_reinstalls_when_constraint_files_change(self):
        self.assertIn(r'^constraints.*\.txt$', self.updater)

    def test_updater_and_model_setup_emit_a_traceable_tool_call_stage(self):
        model_setup = (ROOT / "scripts" / "setup_local_chat_model.py").read_text(encoding="utf-8")
        self.assertIn("TOOL_CALL_TEST_TIMEOUT = (20, 300)", model_setup)
        self.assertIn("Running native tool-calling smoke test", model_setup)
        self.assertIn("Native tool-calling smoke test passed", model_setup)
        self.assertNotIn('set "PKGS=Pillow ', self.installer)


if __name__ == "__main__":
    unittest.main()
