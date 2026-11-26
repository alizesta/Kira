import unittest

from kira.location import detect_ip_region


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class LocationTests(unittest.TestCase):
    def test_ip_lookup_returns_only_a_human_confirmable_region(self):
        calls = {}

        def requester(url, **kwargs):
            calls["url"] = url
            calls["kwargs"] = kwargs
            return _Response({
                "city": "Abadan",
                "region": "Khuzestan",
                "country_name": "Iran",
                "ip": "203.0.113.10",
                "latitude": 30.3,
                "longitude": 48.3,
            })

        result = detect_ip_region(requester=requester)
        self.assertEqual(result, {
            "region": "Abadan, Khuzestan, Iran",
            "source": "ip_estimate",
        })
        self.assertNotIn("ip", result)
        self.assertNotIn("latitude", result)
        self.assertNotIn("longitude", result)
        self.assertIn("timeout", calls["kwargs"])

    def test_ip_lookup_fails_closed_on_provider_error(self):
        result = detect_ip_region(
            requester=lambda *_args, **_kwargs: _Response({"error": True})
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
