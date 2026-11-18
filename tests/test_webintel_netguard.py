"""Privacy regressions for the manually redirected WebIntel fetcher."""
import unittest
from unittest import mock

from kira.webintel import netguard


class _Response:
    def __init__(self, url, status_code, headers=None, body=b""):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self.encoding = "utf-8"
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size=32768):
        yield self._body

    def close(self):
        self.closed = True


class NetguardRedirectPrivacyTests(unittest.TestCase):
    def test_response_cookies_are_cleared_before_following_redirects(self):
        start = "https://example.com/start"
        target = "https://cdn.example.com/final"
        redirect = _Response(start, 302, {"Location": target, "Set-Cookie": "session=private; Domain=.example.com"})
        final = _Response(
            target,
            200,
            {"Content-Type": "text/plain; charset=utf-8", "Content-Length": "5", "Set-Cookie": "other=value"},
            b"hello",
        )
        session = mock.Mock()
        session.get.side_effect = [redirect, final]
        session.cookies.clear = mock.Mock()

        with (
            mock.patch.object(netguard.requests, "Session", return_value=session),
            mock.patch.object(netguard, "check_host"),
            mock.patch.object(netguard, "_peer_blocked", return_value=False),
        ):
            result = netguard.fetch(start)

        self.assertEqual(result.body, b"hello")
        self.assertEqual(session.get.call_count, 2)
        self.assertGreaterEqual(session.cookies.clear.call_count, 4)
        self.assertTrue(redirect.closed)
        self.assertTrue(final.closed)
        session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
