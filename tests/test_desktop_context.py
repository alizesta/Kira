import unittest

from kira.app.desktop_context import DesktopContext, MAX_SUMMARY_CHARS


def window(hwnd=10, pid=20, exe="notepad.exe", title="Notes"):
    return {
        "hwnd": hwnd, "pid": pid, "exe": exe, "title": title,
        "path": r"C:\Windows\notepad.exe", "rect": (0, 0, 800, 600),
    }


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class DesktopContextTests(unittest.TestCase):
    def test_summary_is_bounded_to_2000_characters(self):
        clock = FakeClock()
        context = DesktopContext(clock=clock)
        context.update_active_window(window(title="A" * 160))
        context.set_visible_text("screen " * 400, language="eng", confidence=0.9)
        summary = context.summary()
        self.assertLessEqual(len(summary), MAX_SUMMARY_CHARS)

    def test_window_switch_clears_previous_window_text(self):
        context = DesktopContext()
        context.update_active_window(window())
        key = context.active_window_key
        self.assertTrue(context.set_visible_text("private previous screen", window_key=key))
        context.update_active_window(window(hwnd=11, pid=21, exe="code.exe", title="project.py"))
        self.assertNotIn("private previous screen", context.summary())
        self.assertIn("code.exe", context.summary())

    def test_duplicate_text_and_events_are_not_added_repeatedly(self):
        context = DesktopContext(max_events=3)
        context.update_active_window(window())
        key = context.active_window_key
        self.assertTrue(context.set_visible_text("same text", window_key=key))
        self.assertFalse(context.set_visible_text("same text", window_key=key))
        self.assertTrue(context.record_event("window_changed", "Window changed", dedupe_key="window:1"))
        self.assertFalse(context.record_event("window_changed", "Window changed", dedupe_key="window:1"))
        snapshot = context.snapshot()
        event_types = [item["type"] for item in snapshot["recent_events"]]
        self.assertEqual(event_types.count("visible_text_updated"), 1)
        self.assertLessEqual(len(event_types), 3)

    def test_privacy_clear_purges_text_window_and_prior_events(self):
        context = DesktopContext()
        context.update_active_window(window())
        context.set_visible_text("secret account value", window_key=context.active_window_key)
        context.clear_sensitive(exe="bitwarden.exe", reason="blocked_exe")
        summary = context.summary()
        self.assertNotIn("secret account value", summary)
        self.assertNotIn("notepad.exe", summary)
        self.assertNotIn("Notes", summary)
        self.assertIn("bitwarden.exe", summary)

    def test_stop_and_dispose_clear_ram_context(self):
        context = DesktopContext()
        context.update_active_window(window())
        context.set_visible_text("temporary text", window_key=context.active_window_key)
        context.stop()
        self.assertEqual(context.summary(), "")
        context.start()
        context.update_active_window(window())
        context.dispose()
        self.assertEqual(context.summary(), "")


if __name__ == "__main__":
    unittest.main()
