"""KittenTTS runtime dependency regression tests."""
from pathlib import Path
from unittest import TestCase, mock

from kira import kitten_tts


class KittenRuntimeDependencyTests(TestCase):
    @mock.patch("importlib.util.find_spec", return_value=object())
    @mock.patch("importlib.metadata.version", side_effect=["2.4.0", "0.36.2"])
    @mock.patch("kira.kitten_tts._run")
    def test_incompatible_hub_version_triggers_pinned_reinstall(
        self, run, package_version, _find_spec
    ):
        self.assertTrue(kitten_tts.install_runtime())
        self.assertEqual(package_version.call_count, 2)
        self.assertEqual(run.call_count, 2)

        engine_call = run.call_args_list[0]
        runtime_call = run.call_args_list[1]
        self.assertEqual(engine_call.args[0][0], "-r")
        self.assertIn("--no-deps", engine_call.kwargs["extra_args"])
        self.assertFalse(engine_call.kwargs["check"])
        self.assertEqual(runtime_call.args[0][0], "-r")

        runtime_file = (
            Path(kitten_tts.__file__).resolve().parents[1]
            / "requirements-voice-kitten.txt"
        )
        requirements = runtime_file.read_text(encoding="utf-8")
        self.assertIn("huggingface-hub>=0.34.0,<1.0", requirements)

    @mock.patch("importlib.util.find_spec", return_value=object())
    @mock.patch("importlib.metadata.version", return_value="0.36.2")
    @mock.patch("kira.kitten_tts._run")
    def test_compatible_hub_version_skips_install(
        self, run, _package_version, _find_spec
    ):
        self.assertTrue(kitten_tts.install_runtime())
        run.assert_not_called()


if __name__ == "__main__":
    import unittest
    unittest.main()
