"""Regression tests for Persian app-name resolution and safe launch planning."""
import unittest
from unittest.mock import patch

from kira.tools import apps as app_tools
from kira.tools import appcatalog


class PersianAppResolutionTests(unittest.TestCase):
    def setUp(self):
        self.opera = appcatalog.AppEntry("Opera GX")
        self.opera.add("startmenu", "lnk", r"C:\\Users\\Test\\Opera GX.lnk",
                       install_dir=r"C:\\Program Files\\Opera GX")

    def resolve_with_catalog(self, query, entries=None):
        entries = [self.opera] if entries is None else entries
        with patch.object(app_tools.appcatalog, "menu_apps", return_value=entries), \
             patch.object(app_tools.appcatalog, "deep_apps", return_value=entries), \
             patch.object(app_tools.appcatalog, "uwp_apps", return_value=[]):
            return app_tools.resolve_app(query)

    def test_persian_sentence_extracts_opera_gx_name_on_first_attempt(self):
        state, entry = self.resolve_with_catalog("برنامه‌ی اپرا جی ایکس رو باز کن")
        self.assertEqual(state, "app")
        self.assertIs(entry, self.opera)

    def test_polite_persian_request_and_common_pronunciation(self):
        state, entry = self.resolve_with_catalog("لطفاً برام اوپرا جی ایکس رو باز کن")
        self.assertEqual(state, "app")
        self.assertIs(entry, self.opera)

    def test_builtin_app_name_is_resolved_from_persian_sentence(self):
        self.assertEqual(app_tools.resolve_app("نوت‌پد رو باز کن"), ("builtin", "notepad"))

    def test_other_common_persian_aliases_map_to_installed_names(self):
        self.assertEqual(app_tools._query_key("وینداسکرایب رو اجرا کن"), "windscribe")
        self.assertEqual(app_tools._query_key("دیسکورد"), "discord")
        self.assertEqual(app_tools._query_key("کروم"), "googlechrome")

    def test_ambiguous_or_generic_name_is_not_guessed(self):
        state, _ = self.resolve_with_catalog("مرورگر")
        self.assertEqual(state, "none")


class BrokenShortcutFallbackTests(unittest.TestCase):
    def test_missing_shortcut_target_does_not_block_install_folder_exe(self):
        entry = appcatalog.AppEntry("Opera GX")
        shortcut = r"C:\\Users\\Test\\Opera GX.lnk"
        target = r"C:\\Old Location\\opera.exe"
        fallback = r"C:\\Program Files\\Opera GX\\opera.exe"
        entry.add("startmenu", "lnk", shortcut, install_dir=r"C:\\Program Files\\Opera GX")

        def is_file(path):
            return str(path).lower() == shortcut.lower()

        with patch.object(app_tools.os.path, "isfile", side_effect=is_file), \
             patch.object(app_tools.appcatalog, "lnk_exes", return_value=[target]), \
             patch.object(app_tools.appcatalog, "find_main_exe", return_value=fallback), \
             patch.object(app_tools.appcatalog, "is_safe_exe", return_value=True):
            plan = app_tools._launch_plan(entry)

        self.assertEqual(plan, [("exe", fallback, False)])

    def test_existing_shortcut_keeps_shortcut_as_first_choice(self):
        entry = appcatalog.AppEntry("Opera GX")
        shortcut = r"C:\\Users\\Test\\Opera GX.lnk"
        target = r"C:\\Program Files\\Opera GX\\opera.exe"
        entry.add("startmenu", "lnk", shortcut)

        with patch.object(app_tools.os.path, "isfile", return_value=True), \
             patch.object(app_tools.appcatalog, "lnk_exes", return_value=[target]), \
             patch.object(app_tools.appcatalog, "is_safe_exe", return_value=True):
            plan = app_tools._launch_plan(entry)

        self.assertEqual(plan[0], ("lnk", shortcut, True))


if __name__ == "__main__":
    unittest.main()
