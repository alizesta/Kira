import io
import json
import unittest
from unittest import mock

from kira import user_location


class UserLocationTests(unittest.TestCase):
    def test_ip_result_is_only_an_unconfirmed_suggestion(self):
        payload = json.dumps({"city": "Frankfurt am Main", "country_name": "Germany"}).encode()
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = payload
        with mock.patch.object(user_location, "urlopen", return_value=response):
            suggestion = user_location.detect_ip_location()
        self.assertEqual(suggestion["city"], "Frankfurt am Main")
        self.assertEqual(suggestion["country"], "Germany")
        self.assertFalse(suggestion["confirmed"])

    def test_ip_failure_returns_empty_suggestion_without_raising(self):
        with mock.patch.object(user_location, "urlopen", side_effect=TimeoutError):
            suggestion = user_location.detect_ip_location()
        self.assertEqual(suggestion["city"], "")
        self.assertFalse(suggestion["confirmed"])

    def test_confirmation_persists_city_and_country(self):
        settings = {"user_location": {}}
        with mock.patch.object(user_location, "load_settings", return_value=settings), \
             mock.patch.object(user_location, "save_settings") as save:
            location = user_location.confirm_location("Abadan", "Iran")
        self.assertTrue(location["confirmed"])
        self.assertEqual(location["city"], "Abadan")
        self.assertEqual(location["country"], "Iran")
        save.assert_called_once_with(settings)
        self.assertEqual(settings["user_location"]["source"], "user")

    def test_blank_location_cannot_be_confirmed(self):
        with self.assertRaises(ValueError):
            user_location.confirm_location("", "Germany")


if __name__ == "__main__":
    unittest.main()
