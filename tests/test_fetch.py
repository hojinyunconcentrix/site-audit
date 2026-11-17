import threading
import time
import unittest

from site_audit.audit import discover_pages
from site_audit.http_fetch import BLOCK_MESSAGE, HostPacer, HttpResult, fetch


def _public_resolve(host, port, type=None):
    return [(None, None, None, None, ("93.184.216.34", port))]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _ok(target, method, read_body, body=b"", headers=None):
    return 200, [("Content-Type", "text/html")], b"<p></p>"


class HostPaceTests(unittest.TestCase):
    def test_same_host_waits_between_requests(self):
        clock = FakeClock()
        pacer = HostPacer(gap=0.4, inflight=2, clock=clock.monotonic, sleep=clock.sleep)
        started = []

        def transport(target, method, read_body, body=b"", headers=None):
            started.append(clock.now)
            return _ok(target, method, read_body, body, headers)

        fetch("https://example.com/a", resolve=_public_resolve, pacer=pacer, transport=transport)
        fetch("https://example.com/b", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(started, [0.0, 0.4])

    def test_retries_once_then_stops_the_host(self):
        clock = FakeClock()
        pacer = HostPacer(gap=0.4, inflight=2, clock=clock.monotonic, sleep=clock.sleep, max_pause=15)
        calls = []

        def transport(target, method, read_body, body=b"", headers=None):
            calls.append(target.url)
            return 429, [("Retry-After", "2")], b""

        first = fetch("https://example.com/a", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(first.error, BLOCK_MESSAGE)
        self.assertEqual(first.status, 429)
        self.assertEqual(len(calls), 2)
        self.assertGreaterEqual(clock.now, 2)

        second = fetch("https://example.com/b", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(second.error, BLOCK_MESSAGE)
        self.assertEqual(len(calls), 2)

    def test_retry_after_is_capped(self):
        clock = FakeClock()
        pacer = HostPacer(gap=0, inflight=2, clock=clock.monotonic, sleep=clock.sleep, max_pause=15)
        answers = [503, 200]

        def transport(target, method, read_body, body=b"", headers=None):
            status = answers.pop(0)
            headers = [("Retry-After", "999")] if status == 503 else []
            return status, headers, b"<p></p>"

        result = fetch("https://example.com/a", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(result.status, 200)
        self.assertEqual(result.error, "")
        self.assertEqual(clock.now, 15)

    def test_other_host_stays_open(self):
        clock = FakeClock()
        pacer = HostPacer(gap=0, inflight=2, clock=clock.monotonic, sleep=clock.sleep)
        seen = []

        def transport(target, method, read_body, body=b"", headers=None):
            seen.append(target.hostname)
            if target.hostname == "example.com":
                return 403, [], b""
            return _ok(target, method, read_body, body, headers)

        blocked = fetch("https://example.com/a", resolve=_public_resolve, pacer=pacer, transport=transport)
        other = fetch("https://example.org/a", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(blocked.error, BLOCK_MESSAGE)
        self.assertEqual(other.status, 200)
        self.assertIn("example.org", seen)

    def test_at_most_two_connections(self):
        entered = threading.Semaphore(0)
        release = threading.Event()
        current = []
        lock = threading.Lock()
        pacer = HostPacer(gap=0, inflight=2, clock=time.monotonic, sleep=time.sleep)

        def transport(target, method, read_body, body=b"", headers=None):
            with lock:
                current.append(1)
            entered.release()
            self.assertTrue(release.wait(2))
            with lock:
                current.pop()
            return _ok(target, method, read_body, body, headers)

        threads = []
        for index in range(4):
            thread = threading.Thread(
                target=lambda number=index: fetch(
                    f"https://example.com/{number}",
                    resolve=_public_resolve,
                    pacer=pacer,
                    transport=transport,
                )
            )
            threads.append(thread)
            thread.start()
        self.assertTrue(entered.acquire(timeout=1))
        self.assertTrue(entered.acquire(timeout=1))
        time.sleep(0.15)
        with lock:
            self.assertEqual(len(current), 2)
        release.set()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_discover_shows_limit_message(self):
        def fake(url, read_body=True, **_kwargs):
            return HttpResult(url=url, status=429, content_type="", body=b"", error=BLOCK_MESSAGE)

        listing = discover_pages("https://example.com/", rules={"path_contains": {}}, fetch_one=fake, resolve=_public_resolve)
        self.assertFalse(listing.ok)
        self.assertEqual(listing.message, BLOCK_MESSAGE)
