"""Privacy regressions for the manually redirected WebIntel fetcher."""
import time
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
    def test_peer_check_fails_closed_for_uninspectable_direct_connections(self):
        response = mock.Mock()
        response.url = "https://example.com/"
        with mock.patch.object(netguard, "_uses_proxy", return_value=False):
            self.assertTrue(netguard._peer_blocked(response))

        with mock.patch.object(netguard, "_uses_proxy", return_value=True):
            self.assertFalse(netguard._peer_blocked(response))

    def test_shared_non_global_address_space_is_rejected(self):
        for address in ("100.64.0.1", "192.0.0.1", "198.18.0.1"):
            with self.subTest(address=address):
                self.assertTrue(netguard._ip_blocked(netguard.ipaddress.ip_address(address)))
        self.assertFalse(netguard._ip_blocked(netguard.ipaddress.ip_address("8.8.8.8")))

    def test_peer_check_rejects_private_address_and_accepts_public_address(self):
        response = mock.Mock()
        response.url = "https://example.com/"
        sock = mock.Mock()
        response.raw._connection.sock = sock

        with mock.patch.object(netguard, "_uses_proxy", return_value=False):
            sock.getpeername.return_value = ("127.0.0.1", 443)
            self.assertTrue(netguard._peer_blocked(response))
            sock.getpeername.return_value = ("8.8.8.8", 443)
            self.assertFalse(netguard._peer_blocked(response))

    def test_total_deadline_stops_a_slow_trickling_response(self):
        class SlowResponse:
            def __init__(self):
                self.closed = False

            def iter_content(self, chunk_size=32768):
                yield b"partial"
                while not self.closed:
                    # The next chunk arrives only after the total deadline.
                    time.sleep(0.2)
                    if not self.closed:
                        yield b"x"

            def close(self):
                self.closed = True

        response = SlowResponse()
        started = time.monotonic()
        body, truncated = netguard._read_body_with_deadline(
            response,
            started,
            total_timeout=0.08,
            max_bytes=4096,
        )

        self.assertEqual(body, b"partial")
        self.assertTrue(truncated)
        self.assertTrue(response.closed)
        self.assertLess(time.monotonic() - started, 0.5)

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
