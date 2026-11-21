"""KittenTTS runtime dependency regression tests."""
from unittest import TestCase, mock

from kira import kitten_tts


class KittenRuntimeDependencyTests(TestCase):
    @mock.patch("importlib.util.find_spec", return_value=object())
    @mock.patch("kira.kitten_tts.version", side_effect=["2.4.0", "0.36.2"])
    @mock.patch("kira.kitten_tts._run")
    def test_incompatible_hub_version_triggers_pinned_reinstall(
        self, run, package_version, _find_spec
    ):
        self.assertTrue(kitten_tts.install_runtime())
        self.assertEqual(package_version.call_count, 2)
        dependency_command = run.call_args_list[1].args[0]
        self.assertIn("huggingface-hub>=0.34.0,<1.0", dependency_command)

    @mock.patch("importlib.util.find_spec", return_value=object())
    @mock.patch("kira.kitten_tts.version", return_value="0.36.2")
    @mock.patch("kira.kitten_tts._run")
    def test_compatible_hub_version_skips_install(
        self, run, _package_version, _find_spec
    ):
        self.assertTrue(kitten_tts.install_runtime())
        run.assert_not_called()
