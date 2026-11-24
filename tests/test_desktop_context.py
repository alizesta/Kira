import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from kira.app.desktop_context import DesktopContext, MAX_SUMMARY_CHARS
from kira.app.desktop_capture_application import DesktopCaptureApplicationService


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

    def test_window_title_change_clears_previous_ocr_for_same_hwnd(self):
        context = DesktopContext()
        context.update_active_window(window(title="Document A"))
        context.set_visible_text("contents from document A", window_key=context.active_window_key)
        changed = context.update_active_window(window(title="Document B"))
        self.assertTrue(changed)
        self.assertNotIn("contents from document A", context.summary())
        self.assertIn("Document B", context.summary())

    def test_blocklist_denial_never_enters_context(self):
        context = DesktopContext()
        privacy = DesktopCaptureApplicationService({"desktop_vision_enabled": True})
        privacy.set_enabled(True)
        blocked = window(exe="bitwarden.exe", title="Vault")
        allowed, reason = privacy.evaluate_window(blocked)
        self.assertFalse(allowed)
        context.clear_sensitive(exe=blocked["exe"], reason=reason)
        self.assertEqual(context.summary(), "")
        self.assertIsNone(context.snapshot()["active_window"])
        self.assertEqual(context.snapshot()["visible_text"], "")

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
        self.assertEqual(summary, "")
        self.assertNotIn("secret account value", summary)
        snapshot = context.snapshot()
        self.assertIsNone(snapshot["active_window"])
        self.assertEqual(snapshot["visible_text"], "")
        self.assertEqual(snapshot["recent_events"][-1]["type"], "capture_blocked")
        self.assertIn("bitwarden.exe", snapshot["recent_events"][-1]["summary"])

    def test_summary_prioritizes_latest_visual_observations(self):
        context = DesktopContext(max_events=12)
        context.update_active_window(window())
        for index in range(1, 7):
            context.record_event(
                "visual_observation",
                f"screen-description-{index} " + ("detail " * 20),
                dedupe_key=f"visual:{index}",
            )

        summary = context.summary()

        self.assertIn("CURRENT SCREEN STATE (freshness: fresh;", summary)
        self.assertIn("screen-description-6", summary)
        self.assertIn("screen-description-5", summary)
        self.assertIn("screen-description-4", summary)
        self.assertNotIn("screen-description-1", summary)
        self.assertLess(summary.index("screen-description-6"), summary.index("screen-description-5"))
        self.assertLessEqual(len(summary), MAX_SUMMARY_CHARS)

    def test_small_summary_budget_keeps_the_latest_screen_observation(self):
        context = DesktopContext()
        context.update_active_window(window())
        context.record_event(
            "visual_observation",
            "LATEST_SCREEN_STATE " + ("useful detail " * 12),
            dedupe_key="visual:latest",
        )

        summary = context.summary(max_chars=700)

        self.assertIn("LATEST_SCREEN_STATE", summary)
        self.assertLessEqual(len(summary), 700)


    def test_summary_separates_latest_state_from_history_and_marks_stale_age(self):
        now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
        context = DesktopContext(wall_clock=lambda: now)
        context.update_active_window(window())

        context.record_event("visual_observation", "OLD_WINDOW_STATE", dedupe_key="visual:old")
        context._events[-1] = replace(
            context._events[-1], timestamp=(now - timedelta(seconds=10)).isoformat()
        )
        context.record_event("visual_observation", "LATEST_KNOWN_STATE", dedupe_key="visual:latest")
        context._events[-1] = replace(
            context._events[-1], timestamp=(now - timedelta(seconds=90)).isoformat()
        )

        summary = context.summary()

        self.assertIn("CURRENT SCREEN STATE (freshness: stale; observation age: 1m 30s;", summary)
        self.assertIn("Latest known screen state: LATEST_KNOWN_STATE", summary)
        self.assertIn("Earlier visual observations (historical context only; not the current screen state):", summary)
        self.assertIn("OLD_WINDOW_STATE", summary)
        self.assertLess(summary.index("LATEST_KNOWN_STATE"), summary.index("OLD_WINDOW_STATE"))

    def test_summary_reports_cached_ocr_age_and_staleness(self):
        now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
        context = DesktopContext(wall_clock=lambda: now)
        context.update_active_window(window())
        context.set_visible_text("cached screen text", language="eng", confidence=0.9)
        context._events[-1] = replace(
            context._events[-1], timestamp=(now - timedelta(seconds=90)).isoformat()
        )

        summary = context.summary()

        self.assertIn("OCR observation freshness: stale; age: 1m 30s.", summary)
        self.assertIn("cached screen text", summary)

    def test_summary_marks_recent_observations_without_claiming_live_state(self):
        now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
        context = DesktopContext(wall_clock=lambda: now)
        context.update_active_window(window())
        context.record_event("visual_observation", "RECENT_STATE", dedupe_key="visual:recent")
        context._events[-1] = replace(
            context._events[-1], timestamp=(now - timedelta(seconds=30)).isoformat()
        )

        summary = context.summary()

        self.assertIn("CURRENT SCREEN STATE (freshness: recent; observation age: 30s;", summary)
        self.assertIn("Latest known screen state: RECENT_STATE", summary)

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
