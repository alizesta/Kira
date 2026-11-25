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

    def test_unknown_or_incomplete_identity_fails_closed(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        self.assertEqual(service.evaluate_window(None),
                         (False, "foreground_window_unidentified"))
        missing_path = make_window()
        missing_path["path"] = ""
        self.assertEqual(service.evaluate_window(missing_path),
                         (False, "foreground_window_identity_incomplete"))

    def test_manual_enablement_is_required(self):
        service = DesktopCaptureApplicationService()
        self.assertEqual(service.evaluate_window(make_window()),
                         (False, "desktop_vision_disabled"))
        service.set_enabled(True)
        self.assertEqual(service.evaluate_window(make_window()), (True, "allowed"))

    def test_live_monitor_accepts_partial_identity_but_regular_policy_does_not(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        for missing in ("title", "exe", "path"):
            item = make_window()
            item[missing] = ""
            self.assertEqual(
                service.evaluate_window(item),
                (False, "foreground_window_identity_incomplete"),
            )
            self.assertEqual(
                service.evaluate_window(item, allow_partial_identity=True),
                (True, "allowed"),
            )
        unidentified = make_window(exe="", title="", path="")
        self.assertEqual(
            service.evaluate_window(unidentified, allow_partial_identity=True),
            (False, "foreground_window_identity_incomplete"),
        )

    def test_partial_live_identity_still_checks_every_available_privacy_field(self):
        service = DesktopCaptureApplicationService()
        service.set_enabled(True)
        private = make_window(exe="", title="Incognito", path="")
        self.assertEqual(
            service.evaluate_window(private, allow_partial_identity=True),
            (False, "blocked_title"),
        )
        private["title"] = ""
        private["path"] = r"C:\\Apps\\KeePassXC.exe"
        self.assertEqual(
            service.evaluate_window(private, allow_partial_identity=True),
            (False, "blocked_exe"),
        )

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
