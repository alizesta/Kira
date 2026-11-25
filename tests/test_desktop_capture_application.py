"""Qt-free privacy tests for Live Desktop Vision."""
import unittest
from kira.app.desktop_capture_application import DesktopCaptureApplicationService


def make_window(exe="browser.exe", title="Work tab",
                path=r"C:\Program Files\Browser\browser.exe"):
    return {"hwnd": 10, "pid": 20, "exe": exe, "title": title,
            "path": path, "rect": (0, 0, 1280, 720)}


class DesktopCapturePolicyTests(unittest.TestCase):
    def test_live_vision_always_starts_disabled(self):
        settings = {"desktop_vision_enabled": True}
        service = DesktopCaptureApplicationService(settings)
        self.assertFalse(service.enabled)
        self.assertFalse(settings["desktop_vision_enabled"])

    def test_unknown_window_or_missing_capture_anchor_fails_closed(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        self.assertEqual(service.evaluate_window(None),
                         (False, "foreground_window_unidentified"))
        missing_anchor = make_window()
        missing_anchor["hwnd"] = 0
        self.assertEqual(service.evaluate_window(missing_anchor),
                         (False, "foreground_window_identity_incomplete"))

    def test_monitor_capture_allows_missing_optional_foreground_metadata(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        for field in ("exe", "title", "path"):
            window = make_window()
            window[field] = ""
            self.assertTrue(service.evaluate_window(window)[0], field)

    def test_monitor_capture_still_blocks_known_sensitive_metadata_when_other_fields_are_missing(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        password_manager = make_window("KeePassXC.exe", "", "")
        self.assertEqual(service.evaluate_window(password_manager),
                         (False, "blocked_exe"))
        private_window = make_window("", "Incognito", "")
        self.assertEqual(service.evaluate_window(private_window),
                         (False, "blocked_title"))

    def test_manual_enablement_is_required(self):
        service = DesktopCaptureApplicationService()
        self.assertEqual(service.evaluate_window(make_window()),
                         (False, "desktop_vision_disabled"))
        service.set_enabled(True)
        self.assertEqual(service.evaluate_window(make_window()), (True, "allowed"))

    def test_password_manager_and_private_title_are_blocked(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        self.assertEqual(
            service.evaluate_window(make_window("KeePassXC.exe", "Database",
                                                r"C:\Apps\KeePassXC.exe"))[1],
            "blocked_exe",
        )
        self.assertEqual(
            service.evaluate_window(make_window("chrome.exe", "Incognito",
                                                r"C:\Chrome\chrome.exe"))[1],
            "blocked_title",
        )

    def test_windows_settings_are_blocked(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        allowed, reason = service.evaluate_window(
            make_window("SystemSettings.exe", "Settings",
                        r"C:\Windows\SystemApps\SystemSettings.exe")
        )
        self.assertFalse(allowed)
        self.assertIn(reason, {"blocked_exe", "blocked_title"})

    def test_allowlist_only_overrides_the_matching_dimension(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        item = make_window("KeePassXC.exe", "Database", r"C:\Apps\KeePassXC.exe")
        self.assertFalse(service.evaluate_window(item)[0])
        self.assertTrue(service.add_allow_rule("exe", "keepassxc.exe"))
        self.assertTrue(service.evaluate_window(item)[0])
        private = make_window("chrome.exe", "Incognito", r"C:\Chrome\chrome.exe")
        service.add_allow_rule("exe", "chrome.exe")
        self.assertEqual(service.evaluate_window(private), (False, "blocked_title"))

    def test_monitor_selection_is_persisted(self):
        settings = {}
        service = DesktopCaptureApplicationService(settings)
        selected = r"\\.\DISPLAY2"
        self.assertEqual(service.set_selected_monitor(selected), selected)
        self.assertEqual(settings["desktop_vision_monitor_id"], selected)


if __name__ == "__main__":
    unittest.main()
