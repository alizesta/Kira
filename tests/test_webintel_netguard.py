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

    def test_destination_dns_is_checked_even_when_system_proxy_is_enabled(self):
        private_answer = [(netguard.socket.AF_INET, netguard.socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))]
        with (
            mock.patch.object(netguard, "_uses_proxy", return_value=True),
            mock.patch.object(netguard.socket, "getaddrinfo", return_value=private_answer) as resolve,
        ):
            with self.assertRaisesRegex(netguard.GuardError, "SSRF|داخلی"):
                netguard.check_host("https://example.com/")
        resolve.assert_called_once()

    def test_destination_dns_with_proxy_accepts_public_addresses(self):
        public_answer = [(netguard.socket.AF_INET, netguard.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with (
            mock.patch.object(netguard, "_uses_proxy", return_value=True),
            mock.patch.object(netguard.socket, "getaddrinfo", return_value=public_answer),
        ):
            netguard.check_host("https://example.com/")

    def test_proxy_can_bypass_only_the_known_filter_sinkhole_address(self):
        blocked_answer = [(netguard.socket.AF_INET, netguard.socket.SOCK_STREAM, 6, "", ("10.10.34.2", 443))]
        with (
            mock.patch.object(netguard, "_uses_proxy", return_value=True),
            mock.patch.object(netguard.socket, "getaddrinfo", return_value=blocked_answer),
        ):
            netguard.check_host("https://blocked.example/")

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

    def test_raster_images_require_explicit_opt_in(self):
        url = "https://cdn.example.com/cover.jpg"
        image = b"\\xff\\xd8\\xff" + b"jpeg"
        response = _Response(url, 200, {"Content-Type": "image/jpeg"}, image)
        session = mock.Mock()
        session.get.return_value = response
        session.cookies.clear = mock.Mock()
        with (
            mock.patch.object(netguard.requests, "Session", return_value=session),
            mock.patch.object(netguard, "check_host"),
            mock.patch.object(netguard, "_peer_blocked", return_value=False),
        ):
            with self.assertRaisesRegex(netguard.GuardError, "نوع فایل"):
                netguard.fetch(url)
        self.assertTrue(response.closed)

        response = _Response(url, 200, {"Content-Type": "image/jpeg"}, image)
        session = mock.Mock()
        session.get.return_value = response
        session.cookies.clear = mock.Mock()
        with (
            mock.patch.object(netguard.requests, "Session", return_value=session),
            mock.patch.object(netguard, "check_host"),
            mock.patch.object(netguard, "_peer_blocked", return_value=False),
        ):
            result = netguard.fetch(url, allow_images=True, max_bytes=1024)
        self.assertEqual(result.body, image)
        self.assertEqual(result.ctype, "image/jpeg")

        response = _Response(url, 200, {"Content-Type": "image/svg+xml"}, b"<svg/>")
        session = mock.Mock()
        session.get.return_value = response
        session.cookies.clear = mock.Mock()
        with (
            mock.patch.object(netguard.requests, "Session", return_value=session),
            mock.patch.object(netguard, "check_host"),
            mock.patch.object(netguard, "_peer_blocked", return_value=False),
        ):
            with self.assertRaisesRegex(netguard.GuardError, "نوع فایل"):
                netguard.fetch(url, allow_images=True)

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
