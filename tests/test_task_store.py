"""Persistence and identity regression tests for autonomous task state."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira.tools.tasks import TaskStore


class TaskStorePersistenceTests(unittest.TestCase):
    def test_task_ids_remain_unique_when_created_in_the_same_millisecond(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TaskStore(Path(temp))
            with mock.patch("kira.tools.tasks.time.time", return_value=1_800_000_000.0):
                plans = [
                    store.new(f"task {index}", session_id=("kira" if index % 2 else "ren"))
                    for index in range(100)
                ]

            ids = [plan.id for plan in plans]
            self.assertEqual(len(ids), len(set(ids)))

    def test_unreadable_task_file_is_preserved_instead_of_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "kira_tasks.json"
            original = b'{"version":1,"plans":[broken]}'
            path.write_bytes(original)

            store = TaskStore(Path(temp))

            self.assertTrue(store._load_failed)
            self.assertFalse(store.save())
            self.assertEqual(path.read_bytes(), original)

    def test_one_malformed_task_record_prevents_overwriting_the_original_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            writer = TaskStore(root)
            writer.new("valid task", session_id="kira")
            self.assertTrue(writer.save())
            path = root / "kira_tasks.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["plans"].append("malformed-record")
            path.write_text(json.dumps(data), encoding="utf-8")
            original = path.read_bytes()

            reader = TaskStore(root)

            self.assertEqual(len(reader.plans), 1)
            self.assertTrue(reader._load_failed)
            self.assertFalse(reader.save())
            self.assertEqual(path.read_bytes(), original)

    def test_session_clear_does_not_delete_shared_file_with_unreadable_records(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "kira_tasks.json"
            original = b'{"version":1,"plans":["malformed"]}'
            path.write_bytes(original)

            store = TaskStore(Path(temp))
            store.clear(session_id="kira")

            self.assertEqual(path.read_bytes(), original)

    def test_task_store_saves_valid_json_through_atomic_temp_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = TaskStore(root)
            with mock.patch("kira.tools.tasks.time.time", return_value=1_800_000_000.0):
                for index in range(20):
                    store.new(f"task {index}", session_id=f"character-{index % 3}")

            self.assertTrue(store.save())
            data = json.loads((root / "kira_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["plans"]), 20)
            self.assertEqual(len({plan["id"] for plan in data["plans"]}), 20)
            self.assertFalse(list(root.glob(".kira_tasks.json.*.tmp")))


    def test_verified_goal_is_reopened_after_restart_when_its_evidence_was_memory_only(self):
        from kira.tools.tasks import P_RUNNING, Step

        with tempfile.TemporaryDirectory() as temp:
            store = TaskStore(Path(temp))
            plan = store.new("finish a UI task", session_id="kira")
            plan.status = P_RUNNING
            plan.success_criteria = ["Wallpaper Engine has the requested wallpaper"]
            plan.goal_reviewed = True
            plan.goal_verified = True
            plan.steps.append(Step(1, "apply wallpaper", "ui_click", status="done"))
            self.assertTrue(store.save())

            restored = TaskStore(Path(temp))
            active = restored.active("kira")
            self.assertIsNotNone(active)
            self.assertFalse(active.goal_reviewed)
            self.assertFalse(active.goal_verified)
            self.assertIn("دوباره مشاهده", active.goal_review_reason)

    def test_reviewing_step_is_not_marked_done_after_restart(self):
        from kira.tools.tasks import Step, REVIEW, UNMET

        with tempfile.TemporaryDirectory() as temp:
            store = TaskStore(Path(temp))
            plan = store.new("verify a UI action", session_id="kira")
            plan.success_criteria = ["Wallpaper Engine is active"]
            step = Step(1, "read back final state", "window_active", status=REVIEW, result="review pending",
                        postcondition="Wallpaper Engine must be the active window")
            plan.steps.append(step)
            plan.done_sigs["pending"] = "executed; semantic review pending"
            self.assertTrue(store.save())

            restored = TaskStore(Path(temp))
            recovered = restored.active("kira").steps[0]
            self.assertEqual(recovered.status, UNMET)
            self.assertIn("دوباره مشاهده کن", recovered.error)
            self.assertEqual(recovered.postcondition, "Wallpaper Engine must be the active window")
            self.assertEqual(restored.active("kira").success_criteria, ["Wallpaper Engine is active"])
            self.assertIn("pending", restored.active("kira").done_sigs)


if __name__ == "__main__":
    unittest.main()
