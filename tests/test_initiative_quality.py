import math
import unittest

from kira.character.initiative import (
    DAY,
    MAX_CHECKINS_PER_DAY,
    InitiativeEngine,
    build_checkin_message,
)


def moment(memory_id, kind="event", text='2026-11-01: he said "I have an exam"', ts=0, group="moment"):
    return {"id": memory_id, "group": group, "kind": kind, "text": text, "ts": ts}


class InitiativeCandidateTests(unittest.TestCase):
    def setUp(self):
        self.engine = InitiativeEngine()
        self.now = 20 * DAY

    def test_only_recent_moment_events_and_promises_are_candidates(self):
        rows = [
            moment("fact", kind="event", group="fact", ts=self.now - 10),
            moment("joke", kind="joke", ts=self.now - 20),
            moment("summary", kind="event", group="summary", ts=self.now - 30),
            moment("event", kind="event", ts=self.now - 100),
            moment("promise", kind="promise", ts=self.now - 200),
            moment("old", kind="event", ts=self.now - 11 * DAY),
        ]
        self.assertEqual(
            self.engine.select_candidate(rows, now=self.now)["id"],
            "event",
        )

    def test_explicit_and_multiple_recent_ids_are_excluded(self):
        rows = [
            moment("newest", ts=self.now - 10),
            moment("second", ts=self.now - 20),
            moment("third", ts=self.now - 30),
        ]
        selected = self.engine.select_candidate(
            rows, now=self.now, exclude_id="newest", exclude_ids={"second"}
        )
        self.assertEqual(selected["id"], "third")

    def test_duplicate_ids_are_returned_at_most_once(self):
        rows = [
            moment("same", text="older", ts=self.now - 50),
            moment("same", text="newer", ts=self.now - 10),
        ]
        selected = self.engine.select_candidate(rows, now=self.now)
        self.assertEqual(selected["text"], "newer")

    def test_future_expired_and_non_finite_timestamps_are_rejected(self):
        rows = [
            moment("future", ts=self.now + 120),
            moment("expired", ts=self.now - 11 * DAY),
            moment("nan", ts=float("nan")),
            moment("infinity", ts=float("inf")),
            moment("negative", ts=-1),
            moment("bad", ts="not-a-timestamp"),
        ]
        self.assertIsNone(self.engine.select_candidate(rows, now=self.now))

    def test_small_clock_skew_is_tolerated_but_far_future_rows_are_not(self):
        rows = [
            moment("skew", ts=self.now + 30),
            moment("far", ts=self.now + 120),
        ]
        self.assertEqual(self.engine.select_candidate(rows, now=self.now)["id"], "skew")

    def test_rows_without_ids_receive_stable_legacy_ids(self):
        row = moment("", text='2026-11-01: he said "a trip"', ts=self.now - 10)
        first = self.engine.select_candidate([row], now=self.now)
        second = self.engine.select_candidate([row], now=self.now)
        self.assertTrue(first["id"].startswith("legacy-"))
        self.assertEqual(first["id"], second["id"])

    def test_future_tomorrow_event_is_not_checked_in_early(self):
        row = moment("tomorrow", text='2026-11-01: he said "I have an exam tomorrow"', ts=self.now - 10)
        self.assertIsNone(self.engine.select_candidate([row], now=self.now))
        selected = self.engine.select_candidate([row], now=self.now + DAY + 1)
        self.assertEqual(selected["id"], "tomorrow")

    def test_future_persian_day_after_tomorrow_is_deferred(self):
        row = moment("day-after", text='2026-11-01: he said "پس فردا امتحان دارم"', ts=self.now - 10)
        self.assertIsNone(self.engine.select_candidate([row], now=self.now + DAY))
        self.assertEqual(
            self.engine.select_candidate([row], now=self.now + 2 * DAY + 1)["id"],
            "day-after",
        )

    def test_future_next_week_event_is_deferred(self):
        row = moment("next-week", text='2026-11-01: he said "The interview is next week"', ts=self.now - 10)
        self.assertIsNone(self.engine.select_candidate([row], now=self.now + 6 * DAY))
        self.assertEqual(
            self.engine.select_candidate([row], now=self.now + 7 * DAY + 1)["id"],
            "next-week",
        )

    def test_blank_or_control_only_memory_is_rejected(self):
        rows = [
            moment("blank", text="  \n\t  ", ts=self.now - 10),
            moment("control", text="\x00\x01", ts=self.now - 20),
        ]
        self.assertIsNone(self.engine.select_candidate(rows, now=self.now))


class InitiativeEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = InitiativeEngine()
        self.now = 100_000.0
        self.last_interaction = self.now - 50 * 60

    def test_user_opt_in_is_required(self):
        result = self.engine.evaluate(
            now=self.now,
            last_interaction=self.last_interaction,
            enabled=False,
            has_relevant_memory=True,
        )
        self.assertFalse(result["eligible"])

    def test_busy_inactive_or_quiet_context_blocks_check_in(self):
        for kwargs in (
            {"busy": True},
            {"app_active": False},
            {"quiet_hours": True},
        ):
            result = self.engine.evaluate(
                now=self.now,
                last_interaction=self.last_interaction,
                enabled=True,
                has_relevant_memory=True,
                **kwargs,
            )
            self.assertFalse(result["eligible"])

    def test_minimum_idle_boundary_is_enforced(self):
        before = self.engine.evaluate(
            now=self.now,
            last_interaction=self.now - self.engine.minimum_idle_seconds + 1,
            enabled=True,
            has_relevant_memory=True,
        )
        due = self.engine.evaluate(
            now=self.now,
            last_interaction=self.now - self.engine.minimum_idle_seconds,
            enabled=True,
            has_relevant_memory=True,
        )
        self.assertFalse(before["eligible"])
        self.assertTrue(due["eligible"])

    def test_zero_unknown_or_invalid_last_interaction_is_not_treated_as_infinite_idle(self):
        unknown = self.engine.evaluate(now=self.now, last_interaction=0, enabled=True, has_relevant_memory=True)
        invalid = self.engine.evaluate(now=self.now, last_interaction=float("nan"), enabled=True, has_relevant_memory=True)
        future = self.engine.evaluate(now=self.now, last_interaction=self.now + 120, enabled=True, has_relevant_memory=True)
        self.assertFalse(unknown["eligible"])
        self.assertFalse(invalid["eligible"])
        self.assertFalse(future["eligible"])

    def test_four_hour_cooldown_is_enforced(self):
        self.engine.last_initiative = self.now - 3 * 3600
        result = self.engine.evaluate(
            now=self.now,
            last_interaction=self.last_interaction,
            enabled=True,
            has_relevant_memory=True,
        )
        self.assertEqual(result["reason"], "cooldown")
        self.engine.last_initiative = self.now - 4 * 3600
        self.assertTrue(
            self.engine.evaluate(
                now=self.now,
                last_interaction=self.last_interaction,
                enabled=True,
                has_relevant_memory=True,
            )["eligible"]
        )

    def test_daily_limit_is_enforced(self):
        result = self.engine.evaluate(
            now=self.now,
            last_interaction=self.last_interaction,
            enabled=True,
            has_relevant_memory=True,
            sent_today=MAX_CHECKINS_PER_DAY,
        )
        self.assertEqual(result["reason"], "daily_limit")

    def test_last_sent_time_corruption_fails_closed(self):
        self.engine.last_initiative = math.nan
        result = self.engine.evaluate(
            now=self.now,
            last_interaction=self.last_interaction,
            enabled=True,
            has_relevant_memory=True,
        )
        self.assertFalse(result["eligible"])

    def test_quiet_hours_wrap_midnight(self):
        self.assertFalse(InitiativeEngine.is_quiet_hour(local_hour=21))
        self.assertTrue(InitiativeEngine.is_quiet_hour(local_hour=22))
        self.assertTrue(InitiativeEngine.is_quiet_hour(local_hour=8))
        self.assertFalse(InitiativeEngine.is_quiet_hour(local_hour=9))

    def test_mark_sent_rejects_non_finite_or_negative_timestamps(self):
        for value in (math.nan, math.inf, -1):
            with self.assertRaises(ValueError):
                self.engine.mark_sent(value)
        self.assertEqual(self.engine.mark_sent(self.now), self.now)
        self.assertEqual(self.engine.last_initiative, self.now)


class InitiativeMessageTests(unittest.TestCase):
    def test_persian_event_message_uses_the_remembered_quote_not_storage_label(self):
        text = build_checkin_message(
            moment("event", text='2026-11-01: he said "فردا امتحان زبان دارم"', ts=100),
            language="fa",
        )
        self.assertIn("فردا امتحان زبان دارم", text)
        self.assertNotIn("he said", text)

    def test_promise_message_is_gentle_and_non_assertive(self):
        text = build_checkin_message(
            moment("promise", kind="promise", text='2026-11-01: he said "I will tell you about the trip"', ts=100),
            language="en",
        )
        self.assertIn("any update", text.lower())
        self.assertIn("I will tell you about the trip", text)

    def test_unexpected_memory_shape_uses_a_generic_honest_prompt(self):
        text = build_checkin_message(moment("event", text="old imported row", ts=100), language="fa")
        self.assertIn("موضوعی", text)
        self.assertNotIn("old imported row", text)

    def test_topic_is_bounded_and_control_characters_are_removed(self):
        source = "x" * 500
        text = build_checkin_message(
            moment("event", text=f'2026-11-01: he said "{source}"', ts=100),
            language="en",
            max_topic_chars=50,
        )
        self.assertLessEqual(len(text), 130)
        self.assertNotIn("\x00", text)


if __name__ == "__main__":
    unittest.main()
