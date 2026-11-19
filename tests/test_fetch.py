import threading
import time
import unittest

from site_audit.audit import check_page_assets, discover_pages
from site_audit.guard import Target
from site_audit import http_fetch
from site_audit.http_fetch import BLOCK_MESSAGE, HostPacer, HttpResult, _request_bytes, fetch


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

    def test_one_forbidden_address_keeps_the_host_open(self):
        clock = FakeClock()
        pacer = HostPacer(gap=0, inflight=2, clock=clock.monotonic, sleep=clock.sleep)

        def transport(target, method, read_body, body=b"", headers=None):
            if target.path == "/private":
                return 403, [], b""
            return _ok(target, method, read_body, body, headers)

        blocked = fetch("https://example.com/private", resolve=_public_resolve, pacer=pacer, transport=transport)
        after = fetch("https://example.com/a", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(blocked.error, BLOCK_MESSAGE)
        self.assertEqual(after.status, 200)
        self.assertFalse(pacer.any_closed())

    def test_three_forbidden_in_a_row_stop_the_host_then_reopen(self):
        clock = FakeClock()
        pacer = HostPacer(gap=0, inflight=2, clock=clock.monotonic, sleep=clock.sleep, cooldown=60)
        calls = []
        answer = [403]

        def transport(target, method, read_body, body=b"", headers=None):
            calls.append(target.url)
            return answer[0], [], b"<p></p>"

        for name in ("a", "b", "c"):
            fetch(f"https://example.com/{name}", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertTrue(pacer.any_closed())
        sent = len(calls)
        held = fetch("https://example.com/d", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(held.error, BLOCK_MESSAGE)
        self.assertEqual(len(calls), sent)

        clock.now += 60
        answer[0] = 200
        again = fetch("https://example.com/d", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(again.status, 200)
        self.assertEqual(again.error, "")
        self.assertFalse(pacer.any_closed())

    def test_timeout_is_sent_once_more(self):
        clock = FakeClock()
        pacer = HostPacer(gap=0, inflight=2, clock=clock.monotonic, sleep=clock.sleep)
        calls = []

        def transport(target, method, read_body, body=b"", headers=None):
            calls.append(target.url)
            if len(calls) == 1:
                raise TimeoutError()
            return _ok(target, method, read_body, body, headers)

        result = fetch("https://example.com/a", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(result.status, 200)
        self.assertEqual(len(calls), 2)

        def always(target, method, read_body, body=b"", headers=None):
            calls.append(target.url)
            raise TimeoutError()

        slow = fetch("https://example.com/b", resolve=_public_resolve, pacer=pacer, transport=always)
        self.assertEqual(slow.error, "시간 초과")
        self.assertEqual(len(calls), 4)

    def test_icon_character_is_sent_as_ascii(self):
        target = Target(
            url="https://example.com/icon\uf06e",
            scheme="https",
            hostname="example.com",
            port=443,
            path="/icon\uf06e",
            ip="93.184.216.34",
        )
        payload = _request_bytes(target, "GET")
        head = payload.split(b"\r\n\r\n", 1)[0]
        self.assertTrue(head.isascii())
        self.assertIn(b"GET /icon%EF%81%AE HTTP/1.1\r\n", payload)
        plain = Target(
            url="https://example.com/a%20b?q=1",
            scheme="https",
            hostname="example.com",
            port=443,
            path="/a%20b?q=1",
            ip="93.184.216.34",
        )
        self.assertIn(b"GET /a%20b?q=1 HTTP/1.1\r\n", _request_bytes(plain, "GET"))

    def test_encode_error_releases_the_host_slot(self):
        clock = FakeClock()
        pacer = HostPacer(gap=0, inflight=2, clock=clock.monotonic, sleep=clock.sleep)
        calls = []

        def transport(target, method, read_body, body=b"", headers=None):
            calls.append(target.path)
            if "\uf06e" in target.path:
                raise UnicodeEncodeError("ascii", target.path, 0, 1, "ordinal not in range(128)")
            return _ok(target, method, read_body, body, headers)

        bad = fetch("https://example.com/icon\uf06e", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(bad.error, "이 주소는 요청할 수 없습니다.")
        good = fetch("https://example.com/next", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(good.status, 200)
        self.assertEqual(good.error, "")
        self.assertEqual(calls, ["/icon\uf06e", "/next"])
        with pacer._lock:
            self.assertEqual(pacer._hosts["example.com"]["open"], 0)

    def test_one_odd_asset_does_not_stop_the_page(self):
        icon = "/icon\uf06e".encode()
        html = b'<html lang="en"><body><a href="' + icon + b'">i</a><a href="/ok">o</a></body></html>'

        def fake(url, read_body=True, **_kwargs):
            if "\uf06e" in url:
                raise UnicodeEncodeError("ascii", url, 61, 62, "ordinal not in range(128)")
            return HttpResult(url=url, status=200, content_type="text/html", body=html if read_body else b"")

        checked = check_page_assets(
            "https://example.com/",
            rules={"path_contains": {}},
            fetch_one=fake,
            resolve=_public_resolve,
        )
        self.assertTrue(checked["ok"])

    def test_blocked_link_does_not_fail_the_page(self):
        html = b'<html lang="en"><body><a href="https://social.example/share">s</a><a href="/gone">g</a></body></html>'

        def fake(url, read_body=True, **_kwargs):
            if "social.example" in url:
                return HttpResult(url=url, status=403, content_type="", body=b"", error=BLOCK_MESSAGE)
            if url.endswith("/gone"):
                return HttpResult(url=url, status=404, content_type="text/html", body=b"")
            return HttpResult(url=url, status=200, content_type="text/html", body=html)

        checked = check_page_assets("https://example.com/", rules={"path_contains": {}}, fetch_one=fake, resolve=_public_resolve)
        self.assertTrue(checked["ok"])
        broken = [row["url"] for view in checked["viewports"] for row in view["brokenLinks"]]
        self.assertIn("https://example.com/gone", broken)
        self.assertNotIn("https://social.example/share", broken)

    def test_stopped_host_reports_wait_and_slows_down(self):
        clock = FakeClock()
        pacer = HostPacer(gap=1.0, inflight=2, clock=clock.monotonic, sleep=clock.sleep, cooldown=90)
        answer = [429]
        started = []

        def transport(target, method, read_body, body=b"", headers=None):
            started.append(clock.now)
            return answer[0], [], b"<p></p>"

        self.assertEqual(pacer.hold_seconds("example.com"), 0)
        fetch("https://example.com/a", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(pacer.hold_seconds("example.com"), 90)
        clock.now += 30
        self.assertEqual(pacer.hold_seconds("example.com"), 60)
        self.assertEqual(pacer.hold_seconds("example.org"), 0)

        clock.now += 60
        answer[0] = 200
        started.clear()
        fetch("https://example.com/b", resolve=_public_resolve, pacer=pacer, transport=transport)
        fetch("https://example.com/c", resolve=_public_resolve, pacer=pacer, transport=transport)
        self.assertEqual(started[1] - started[0], 1.5)

    def test_slow_paths_keep_their_own_longer_gap(self):
        clock = FakeClock()
        pacer = HostPacer(gap=1.0, inflight=2, clock=clock.monotonic, sleep=clock.sleep, slow_gap=15)
        started = {}

        def transport(target, method, read_body, body=b"", headers=None):
            started[target.path] = clock.now
            return _ok(target, method, read_body, body, headers)

        kept = http_fetch._slow_paths
        http_fetch._slow_paths = ("/support/",)
        try:
            for path in ("/support/a", "/business/a", "/support/b", "/business/b"):
                fetch(f"https://example.com{path}", resolve=_public_resolve, pacer=pacer, transport=transport)
        finally:
            http_fetch._slow_paths = kept
        self.assertEqual(started["/business/a"], 1.0)
        self.assertEqual(started["/support/b"], 15.0)
        self.assertEqual(started["/business/b"], 16.0)

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
