import ast
import math
import tempfile
import unittest
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from kira.character.initiative import (
    DAY,
    MAX_CHECKINS_PER_DAY,
    InitiativeEngine,
    build_checkin_message,
    initiative_history_state,
    persisted_checkin_events,
    sessions_are_idle,
    _event_not_before,
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
        selected = self.engine.select_candidate([row], now=self.now + 2 * DAY + 1)
        self.assertEqual(selected["id"], "tomorrow")

    def test_future_persian_day_after_tomorrow_is_deferred(self):
        row = moment("day-after", text='2026-11-01: he said "پس فردا امتحان دارم"', ts=self.now - 10)
        self.assertIsNone(self.engine.select_candidate([row], now=self.now + DAY))
        self.assertEqual(
            self.engine.select_candidate([row], now=self.now + 3 * DAY + 1)["id"],
            "day-after",
        )

    def test_future_next_week_event_is_deferred(self):
        row = moment("next-week", text='2026-11-01: he said "The interview is next week"', ts=self.now - 10)
        self.assertIsNone(self.engine.select_candidate([row], now=self.now + 6 * DAY))
        self.assertEqual(
            self.engine.select_candidate([row], now=self.now + 8 * DAY + 1)["id"],
            "next-week",
        )

    def test_today_and_tonight_events_wait_until_the_local_day_has_ended(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        expected = datetime.combine(
            datetime.fromtimestamp(created).date() + timedelta(days=1),
            datetime_time.min,
        ).timestamp()
        for phrase in ("2026-11-19: he said \"امروز امتحان دارم\"", "2026-11-19: he said \"امشب جلسه دارم\"", "2026-11-19: he said \"I have a meeting tonight\""):
            self.assertEqual(_event_not_before(phrase, created), expected)

    def test_tomorrow_is_deferred_until_the_entire_tomorrow_date_has_passed(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        expected = datetime.combine(
            datetime.fromtimestamp(created).date() + timedelta(days=2),
            datetime_time.min,
        ).timestamp()
        self.assertEqual(_event_not_before("he said \"امتحان فردا دارم\"", created), expected)
        self.assertEqual(_event_not_before("he said \"The exam is tomorrow\"", created), expected)

    def test_numeric_relative_future_dates_are_deferred_in_english_and_persian(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        date = datetime.fromtimestamp(created).date()
        two_weeks_end = datetime.combine(date + timedelta(days=15), datetime_time.min).timestamp()
        three_days_end = datetime.combine(date + timedelta(days=4), datetime_time.min).timestamp()
        self.assertEqual(_event_not_before("he said \"The interview is in two weeks\"", created), two_weeks_end)
        self.assertEqual(_event_not_before("he said \"جلسه سه روز دیگر است\"", created), three_days_end)
        self.assertEqual(_event_not_before("he said \"جلسه ۳ روز آینده است\"", created), three_days_end)

    def test_weekday_and_weekend_dates_are_deferred_to_their_actual_calendar_day(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()  # Thursday
        date = datetime.fromtimestamp(created).date()
        next_week_end = datetime.combine(date + timedelta(days=11), datetime_time.min).timestamp()
        friday_end = datetime.combine(date + timedelta(days=2), datetime_time.min).timestamp()
        sunday_end = datetime.combine(date + timedelta(days=4), datetime_time.min).timestamp()
        next_friday_end = datetime.combine(date + timedelta(days=9), datetime_time.min).timestamp()
        self.assertEqual(_event_not_before("The interview is next week", created), next_week_end)
        self.assertEqual(_event_not_before("The interview is this Friday", created), friday_end)
        self.assertEqual(_event_not_before("The interview is next Friday", created), next_friday_end)
        self.assertEqual(_event_not_before("پنجشنبه هفته بعد امتحان دارم", created), next_friday_end - DAY)
        self.assertEqual(_event_not_before("آخر هفته امتحان دارم", created), friday_end)
        self.assertEqual(_event_not_before("The event is this weekend", created), sunday_end)

    def test_subday_durations_wait_until_after_the_expected_event(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        expected_end = datetime.combine(datetime.fromtimestamp(created).date() + timedelta(days=1), datetime_time.min).timestamp()
        self.assertEqual(_event_not_before('he said "I have an exam in two hours"', created), expected_end)
        self.assertEqual(_event_not_before('he said "دو ساعت دیگه جلسه دارم"', created), expected_end)
        self.assertEqual(_event_not_before('he said "I have a call in 30 minutes"', created), expected_end)

    def test_clock_time_without_a_date_fails_closed(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        self.assertTrue(math.isinf(_event_not_before('he said "My appointment is at 5pm"', created)))
        self.assertTrue(math.isinf(_event_not_before('he said "My appointment is 5pm"', created)))
        self.assertTrue(math.isinf(_event_not_before('he said "قرار ساعت پنج عصر دارم"', created)))
        self.assertNotEqual(_event_not_before('he said "My appointment is tomorrow at 5pm"', created), float("inf"))

    def test_next_month_boundary_handles_november_and_december_rollover(self):
        november = datetime(2026, 11, 19, 10, 30).timestamp()
        december = datetime(2026, 12, 19, 10, 30).timestamp()
        self.assertEqual(
            datetime.fromtimestamp(_event_not_before("next month exam", november)).date(),
            datetime(2027, 1, 1).date(),
        )
        self.assertEqual(
            datetime.fromtimestamp(_event_not_before("ماه بعد امتحان دارم", december)).date(),
            datetime(2027, 2, 1).date(),
        )
        self.assertEqual(
            datetime.fromtimestamp(_event_not_before("امتحان این ماه دارم", november)).date(),
            datetime(2026, 12, 1).date(),
        )
        self.assertTrue(math.isinf(_event_not_before("The event is next year", november)))

    def test_blank_or_control_only_memory_is_rejected(self):
        rows = [
            moment("blank", text="  \n\t  ", ts=self.now - 10),
            moment("control", text="\x00\x01", ts=self.now - 20),
        ]
        self.assertIsNone(self.engine.select_candidate(rows, now=self.now))


class InitiativeEligibilityTests(unittest.TestCase):
    def test_boolean_timestamps_are_rejected_as_corrupt(self):
        self.assertIsNone(_finite_number(True))
        self.assertIsNone(_finite_number(False))
        result = self.engine.evaluate(
            now=self.now,
            last_interaction=True,
            enabled=True,
            has_relevant_memory=True,
        )
        self.assertEqual(result["reason"], "invalid_activity_time")

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

    def test_invalid_daily_counts_fail_closed(self):
        for value in (True, -1, 1.5, float("nan"), float("inf"), "bad"):
            result = self.engine.evaluate(
                now=self.now, last_interaction=self.last_interaction,
                enabled=True, has_relevant_memory=True, sent_today=value,
            )
            self.assertEqual(result["reason"], "invalid_daily_count")

    def test_non_iterable_candidate_input_fails_closed(self):
        self.assertIsNone(self.engine.select_candidate(object(), now=self.now))

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


class InitiativeHistoryTests(unittest.TestCase):
    def test_malformed_non_iterable_recent_events_fail_closed_without_crashing(self):
        state = initiative_history_state([], recent_events=object(), now=20 * DAY)
        self.assertEqual(state["sent_today"], 0)
        self.assertEqual(state["history"], [])

    def test_non_iterable_exclusion_state_does_not_crash_candidate_selection(self):
        engine = InitiativeEngine()
        self.assertIsNone(engine.select_candidate([], now=100_000, exclude_ids=object()))

    def test_settings_and_runtime_events_share_one_daily_count(self):
        now = 20 * DAY
        state = initiative_history_state(
            [{"at": now - 10, "memory_id": "event-1"}],
            [{"name": "proactive_check_in", "at": now - 10, "detail": "event-1"}],
            last_memory_id="event-1",
            last_sent_at=now - 10,
            now=now,
        )
        self.assertEqual(state["sent_today"], 1)
        self.assertEqual(state["excluded_ids"], {"event-1"})

    def test_mirrored_history_with_small_timestamp_drift_counts_once(self):
        now = 20 * DAY
        state = initiative_history_state(
            [{"at": now - 10, "memory_id": "same"}],
            [{"name": "proactive_check_in", "at": now - 9.2, "detail": "same"}],
            last_memory_id="same", last_sent_at=now - 9.7, now=now,
        )
        self.assertEqual(state["sent_today"], 1)

    def test_distinct_sends_of_the_same_memory_still_count_separately(self):
        now = 20 * DAY
        state = initiative_history_state(
            [{"at": now - 100, "memory_id": "same"}, {"at": now - 50, "memory_id": "same"}],
            now=now,
        )
        self.assertEqual(state["sent_today"], 2)

    def test_recent_history_and_runtime_marker_enforce_daily_cap(self):
        now = 20 * DAY
        state = initiative_history_state(
            [{"at": now - 100, "memory_id": "one"}],
            [{"name": "proactive_check_in", "at": now - 50, "detail": "two"}],
            last_memory_id="two",
            last_sent_at=now - 50,
            now=now,
        )
        self.assertEqual(state["sent_today"], 2)
        self.assertEqual(state["excluded_ids"], {"one", "two"})

    def test_expired_malformed_and_unrelated_events_are_ignored(self):
        now = 20 * DAY
        state = initiative_history_state(
            [
                {"at": now - 11 * DAY, "memory_id": "expired"},
                {"at": "bad", "memory_id": "malformed"},
                {"at": now - 20, "memory_id": "valid"},
            ],
            [
                {"name": "user_message", "at": now - 10, "detail": "not-checkin"},
                {"name": "proactive_check_in", "at": now + 120, "detail": "future"},
            ],
            now=now,
        )
        self.assertEqual(state["sent_today"], 1)
        self.assertEqual(state["history"], [{"at": now - 20, "memory_id": "valid"}])
        self.assertEqual(state["excluded_ids"], {"valid"})

    def test_previous_local_day_does_not_consume_today_limit(self):
        now = 20 * DAY
        yesterday = now - DAY
        state = initiative_history_state(
            [{"at": yesterday, "memory_id": "yesterday"}],
            now=now,
        )
        self.assertEqual(state["sent_today"], 0)
        self.assertIn("yesterday", state["excluded_ids"])

    def test_same_memory_sent_at_two_different_times_counts_as_two_checkins(self):
        now = 20 * DAY
        first = now - 100
        second = now - 50
        state = initiative_history_state(
            [
                {"at": first, "memory_id": "same-memory"},
                {"at": second, "memory_id": "same-memory"},
            ],
            [
                {"name": "proactive_check_in", "at": first, "detail": "same-memory"},
                {"name": "proactive_check_in", "at": second, "detail": "same-memory"},
            ],
            last_memory_id="same-memory",
            last_sent_at=second,
            now=now,
        )
        self.assertEqual(state["sent_today"], 2)
        self.assertEqual(state["excluded_ids"], {"same-memory"})


class InitiativePersistenceRecoveryTests(unittest.TestCase):
    def test_chat_history_adapter_exposes_persisted_record_reader(self):
        from unittest.mock import Mock
        from kira.services.chat_history_service import SqliteChatHistoryService

        persistence = Mock()
        expected = [{"role": "assistant", "metadata": {"proactive": "initiative"}}]
        persistence.recent_message_records.return_value = expected
        service = object.__new__(SqliteChatHistoryService)
        service._persistence = persistence
        self.assertIs(service.recent_message_records(50, "ren"), expected)
        persistence.recent_message_records.assert_called_once_with(50, "ren")

    def test_persisted_checkin_message_recovers_after_interrupted_settings_write(self):
        now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc).timestamp()
        records = [{
            "role": "assistant", "created_at": "2026-11-19 11:59:00",
            "metadata": {"proactive": "initiative", "memory_id": "mem-1"},
        }]
        events = persisted_checkin_events(records, now=now)
        state = initiative_history_state([], recent_events=events, now=now)
        self.assertEqual(len(events), 1)
        self.assertEqual(state["sent_today"], 1)
        self.assertEqual(state["excluded_ids"], {"mem-1"})

    def test_persisted_recovery_ignores_bad_role_metadata_timestamps_and_expired_records(self):
        now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc).timestamp()
        records = [
            {"role": "user", "created_at": "2026-11-19 11:59:00", "metadata": {"proactive": "initiative"}},
            {"role": "assistant", "created_at": "bad", "metadata": {"proactive": "initiative"}},
            {"role": "assistant", "created_at": "2026-11-19 12:05:00", "metadata": {"proactive": "initiative"}},
            {"role": "assistant", "created_at": "2026-11-01 12:00:00", "metadata": {"proactive": "initiative"}},
            {"role": "assistant", "created_at": "2026-11-19 11:59:00", "metadata": "{bad json"},
            {"role": "assistant", "created_at": "2026-11-19 11:59:00", "status": "failed", "metadata": {"proactive": "initiative"}},
        ]
        self.assertEqual(persisted_checkin_events(records, now=now), [])

    def test_repository_returns_recoverable_initiative_metadata(self):
        from kira.chat.persistence import ChatPersistence, SqliteChatRepository

        with tempfile.TemporaryDirectory() as temp:
            store = ChatPersistence(SqliteChatRepository(Path(temp) / "chat.sqlite3"))
            store.init_db()
            self.assertTrue(store.add_message(
                "assistant", "check in", character_id="ren", status="complete",
                metadata={"proactive": "initiative", "memory_id": "durable-1"},
            ))
            records = store.recent_message_records(limit=20, character_id="ren")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["metadata"]["memory_id"], "durable-1")
            now = datetime.now(timezone.utc).timestamp()
            recovered = persisted_checkin_events(records, now=now)
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["detail"], "durable-1")
            expected_at = datetime.fromisoformat(records[0]["created_at"]).replace(tzinfo=timezone.utc).timestamp()
            self.assertAlmostEqual(recovered[0]["at"], expected_at, places=3)

    def test_repository_inspection_failure_is_not_reported_as_empty_history(self):
        from kira.chat.persistence import ChatPersistence, PersistenceError, SqliteChatRepository

        with tempfile.TemporaryDirectory() as temp:
            store = ChatPersistence(SqliteChatRepository(Path(temp) / "missing" / "chat.sqlite3"))
            with self.assertRaises(PersistenceError):
                store.recent_message_records(limit=5, character_id="ren")


class InitiativeSessionGuardTests(unittest.TestCase):
    def test_every_character_session_must_be_idle_and_have_no_draft(self):
        self.assertTrue(sessions_are_idle([SimpleNamespace(busy=False, draft="")]))
        self.assertFalse(sessions_are_idle([
            SimpleNamespace(busy=False, draft=""),
            SimpleNamespace(busy=True, draft=""),
        ]))
        self.assertFalse(sessions_are_idle([
            SimpleNamespace(busy=False, draft=""),
            SimpleNamespace(busy=False, draft="  unsent draft  "),
        ]))
        self.assertFalse(sessions_are_idle(None))
        self.assertFalse(sessions_are_idle([]))
        self.assertFalse(sessions_are_idle([None]))
        self.assertFalse(sessions_are_idle([SimpleNamespace(draft="")]))
        self.assertFalse(sessions_are_idle([SimpleNamespace(busy="false", draft="")]))
        self.assertFalse(sessions_are_idle([SimpleNamespace(busy=False, draft=[]) ]))

    def test_session_controller_imports_math_used_by_idle_guard(self):
        source = Path(__file__).resolve().parents[1] / "kira" / "ui" / "main_window_session.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        self.assertTrue(any(
            isinstance(node, ast.Import) and any(alias.name == "math" for alias in node.names)
            for node in tree.body
        ))


class InitiativeIntegrationImportTests(unittest.TestCase):
    def test_session_controller_imports_every_initiative_dependency_it_uses(self):
        source = Path(__file__).resolve().parents[1] / "kira" / "ui" / "main_window_session.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "main_window_session_support":
                imported.update(alias.asname or alias.name for alias in node.names)

        required = {
            "InitiativeEngine",
            "build_checkin_message",
            "initiative_history_state",
            "persona_memory",
        }
        self.assertTrue(required.issubset(imported), sorted(required - imported))


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


    def test_quote_extraction_preserves_embedded_quotation_marks(self):
        text = build_checkin_message(
            moment("event", text='2026-11-01: he said "I said "hello" yesterday"', ts=100),
            language="en",
        )
        self.assertIn('I said "hello" yesterday', text)

    def test_topic_truncation_does_not_cut_the_final_word(self):
        text = build_checkin_message(
            moment("event", text='2026-11-01: he said "alpha beta gamma delta epsilon"', ts=100),
            language="en",
            max_topic_chars=25,
        )
        self.assertIn("alpha beta gamma delta", text)
        self.assertNotIn("epsi", text)


    def test_numeric_gregorian_absolute_dates_are_deferred_until_the_date_ends(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        expected = datetime(2026, 11, 26, 0, 0).timestamp()
        self.assertEqual(_event_not_before('he said "Exam on 2026-11-25"', created), expected)
        self.assertEqual(_event_not_before('he said "Exam on 25/11/2026"', created), expected)

    def test_numeric_jalali_absolute_dates_are_converted_and_conservatively_buffered(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        expected = datetime(2026, 11, 24, 0, 0).timestamp()
        self.assertEqual(_event_not_before('he said "امتحان 1405/09/01"', created), expected)
        self.assertEqual(_event_not_before('he said "امتحان ۱۴۰۵/۰۹/۰۱"', created), expected)

    def test_invalid_absolute_dates_fail_closed_instead_of_becoming_due_immediately(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        self.assertTrue(math.isinf(_event_not_before('he said "امتحان 2026-02-30"', created)))
        self.assertTrue(math.isinf(_event_not_before('he said "امتحان 1405/13/01"', created)))


    def test_unsupported_named_month_and_ambiguous_numeric_dates_fail_closed(self):
        created = datetime(2026, 11, 19, 10, 30).timestamp()
        self.assertTrue(math.isinf(_event_not_before('he said "جلسه ۲۵ آذر ۱۴۰۵"', created)))
        self.assertTrue(math.isinf(_event_not_before('he said "meeting on November 25, 2026"', created)))
        self.assertTrue(math.isinf(_event_not_before('he said "appointment 11/25"', created)))


if __name__ == "__main__":
    unittest.main()
