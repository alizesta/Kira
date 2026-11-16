"""Tests for the staged transition from the legacy monolith to the app entry point."""
import unittest
from unittest import mock


class MainEntrypointTests(unittest.TestCase):
    def test_main_delegates_startup_to_the_composition_root(self):
        import kira.main as entrypoint

        with mock.patch("kira.app.bootstrap.run_application") as run_application:
            entrypoint.main()

        run_application.assert_called_once_with()

    def test_legacy_mainwindow_is_available_only_through_lazy_compatibility_export(self):
        import kira.main as entrypoint
        from kira.oldmain import MainWindow as LegacyMainWindow

        self.assertIs(entrypoint.MainWindow, LegacyMainWindow)
        self.assertNotIn("MainWindow", vars(entrypoint))

    def test_bootstrap_constructs_the_preserved_legacy_window_directly(self):
        import inspect
        from kira.app import bootstrap

        source = inspect.getsource(bootstrap.run_application)
        self.assertIn("from ..oldmain import MainWindow", source)
        self.assertNotIn("from ..main import MainWindow", source)


if __name__ == "__main__":
    unittest.main()
