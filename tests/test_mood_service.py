"""Contract tests for MoodStateService operations used by Initiative orchestration."""
import unittest
from unittest.mock import patch

from kira.services.mood_service import MoodStateService


class MoodStateServiceTests(unittest.TestCase):
    def test_current_forwards_the_shared_timestamp(self):
        service = MoodStateService()
        with patch("kira.services.mood_service.mood") as backend:
            backend.current.return_value = {"age": 120}
            result = service.current(now=1234.5)
        backend.current.assert_called_once_with(now=1234.5)
        self.assertEqual(result, {"age": 120})

    def test_mark_initiative_sent_forwards_character_scoped_marker(self):
        service = MoodStateService()
        with patch("kira.services.mood_service.mood") as backend:
            service.mark_initiative_sent(memory_id="memory-1", now=1234.5)
        backend.mark_initiative_sent.assert_called_once_with(
            memory_id="memory-1", now=1234.5
        )


if __name__ == "__main__":
    unittest.main()
