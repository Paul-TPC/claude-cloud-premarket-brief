import requests

from brief.net import USER_AGENT, Fetcher, domain_key, redact
from conftest import fake_session, fixture_bytes


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def _fetcher(handler):
    clock = FakeClock()
    session, adapter = fake_session(handler)
    return Fetcher(session, sleep=clock.sleep, clock=clock), adapter, clock


def test_domain_key():
    assert domain_key("www.twse.com.tw") == domain_key("openapi.twse.com.tw") == "twse.com.tw"
    assert domain_key("tw.stock.yahoo.com") == "yahoo.com"
    assert domain_key("api.telegram.org") == "telegram.org"


def test_interval_between_same_domain():
    f, adapter, clock = _fetcher(lambda req: (200, b"{}"))
    f.get("https://www.twse.com.tw/a")
    f.get("https://openapi.twse.com.tw/b")
    f.get("https://tw.stock.yahoo.com/rss")  # 不同網域不用等
    f.get("https://www.twse.com.tw/c")
    assert clock.sleeps == [3.0, 3.0]
    assert adapter.requests[0].headers["User-Agent"] == USER_AGENT


def test_timeout_is_passed():
    seen = {}

    class Spy(requests.Session):
        def request(self, *a, **kw):
            seen.update(kw)
            raise requests.Timeout("slow")

    f = Fetcher(Spy(), sleep=lambda s: None)
    r = f.get("https://example.com/")
    assert seen["timeout"] == 15
    assert not r.ok and "Timeout" in r.error


def test_retry_once_on_connection_error():
    calls = []

    def handler(req):
        calls.append(req.url)
        return requests.ConnectionError("reset") if len(calls) == 1 else (200, b"{}")

    f, _, clock = _fetcher(handler)
    r = f.get("https://www.twse.com.tw/x")
    assert r.ok and len(calls) == 2
    assert clock.sleeps == [3.0]  # 重試也要守同網域間隔


def test_retry_only_once():
    f, adapter, _ = _fetcher(lambda req: requests.ConnectionError("down"))
    r = f.get("https://www.twse.com.tw/x")
    assert not r.ok and len(adapter.requests) == 2


def test_no_retry_on_404():
    f, adapter, _ = _fetcher(lambda req: (404, b"nope"))
    r = f.get("https://www.twse.com.tw/x")
    assert r.error == "HTTP 404" and len(adapter.requests) == 1


def test_block_page_with_200_is_failure_and_retried():
    f, adapter, _ = _fetcher(lambda req: (200, fixture_bytes("twse_blocked_200.html")))
    r = f.get("https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule")
    assert not r.ok and "擋" in r.error and r.status == 200
    assert len(adapter.requests) == 2


def test_block_then_success():
    bodies = [(307, fixture_bytes("twse_blocked_307.html")), (200, b'{"stat":"OK"}')]
    f, _, _ = _fetcher(lambda req: bodies.pop(0))
    r = f.get("https://www.twse.com.tw/x")
    assert r.ok and r.response.content == b'{"stat":"OK"}'


def test_redact_unregistered_token_shape():
    # 沒登記過、但長得像 bot token 的字串也要遮掉。執行時才組出來，原始碼裡不放像 token 的字串。
    token = "1" * 9 + ":" + "x" * 35
    assert redact(f"https://api.telegram.org/bot{token}/getMe") == "https://api.telegram.org/bot***/getMe"
