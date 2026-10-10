"""對外請求：逾時、重試、同網域間隔、User-Agent，以及錯誤訊息遮蔽。"""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote, urlsplit

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
TIMEOUT = 15  # 秒
RETRIES = 1
MIN_INTERVAL = 3.0  # 同網域兩次請求之間的最短間隔（秒）

# Telegram bot token 的樣子：數字、冒號、一串英數。沒登記到的也要遮掉。
_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}")
_MASK = "***"
_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """登記一個不能出現在輸出裡的值（原樣和網址編碼後的樣子都登記）。"""
    if not value or len(value) < 5:
        return
    _secrets.add(value)
    _secrets.add(quote(value, safe=""))


def redact(text: object) -> str:
    text = str(text)
    for s in sorted(_secrets, key=len, reverse=True):
        text = text.replace(s, _MASK)
    return _TOKEN_RE.sub(_MASK, text)


class RedactFilter(logging.Filter):
    """把 log 訊息先遮蔽。requests 底下的 urllib3 在 DEBUG 時會把完整網址（含 token）寫進 log。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


# logger 的 filter 不會套到子 logger 傳上來的紀錄，所以每個會出現網址的 logger 都要掛。
for _name in ("urllib3", "urllib3.connectionpool", "urllib3.connection", "urllib3.util.retry",
              "urllib3.response", "requests"):
    logging.getLogger(_name).addFilter(RedactFilter())


def log(msg: str) -> None:
    """所有診斷訊息都走這裡，先遮蔽再印到 stderr。"""
    print(redact(msg), file=sys.stderr)


def domain_key(host: str) -> str:
    """同一個網域的判斷：取可註冊網域（www.twse.com.tw 和 openapi.twse.com.tw 算同一個）。"""
    labels = host.lower().split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"com", "org", "net", "gov", "edu"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


@dataclass
class FetchResult:
    url: str
    status: int | None
    elapsed_ms: int
    error: str | None
    response: requests.Response | None

    @property
    def ok(self) -> bool:
        return self.error is None


_BLOCK_MARKERS = ("FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED", "因為安全性考量，您所執行的頁面無法呈現")
_BLOCK_CODE_RE = re.compile(r"錯誤代碼：(\d+)")


def blocked_reason(body: bytes) -> str | None:
    """證交所的安全機制擋頁（狀態碼可能是 200 或 307）。是擋頁就回傳說明，否則 None。"""
    if len(body) > 20000:
        return None
    text = body.decode("utf-8", errors="replace")
    if not any(m in text for m in _BLOCK_MARKERS):
        return None
    m = _BLOCK_CODE_RE.search(text)
    return "被證交所安全機制擋下（擋頁" + (f"，錯誤代碼 {m.group(1)}" if m else "") + "）"


def _should_retry(status: int | None, blocked: bool) -> bool:
    # 例外（逾時、連線失敗）、擋頁、5xx、429 才重試；其他 4xx 重試也不會變。
    return blocked or status is None or status >= 500 or status == 429


class Fetcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: float = TIMEOUT,
        retries: int = RETRIES,
        interval: float = MIN_INTERVAL,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout
        self.retries = retries
        self.interval = interval
        self.sleep = sleep
        self.clock = clock
        self._last_done: dict[str, float] = {}

    def _wait_turn(self, url: str) -> str:
        key = domain_key(urlsplit(url).hostname or "")
        last = self._last_done.get(key)
        if last is not None:
            remaining = self.interval - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        return key

    def request(self, method: str, url: str, *, display_url: str | None = None, **kwargs) -> FetchResult:
        """送出請求。display_url 是給錯誤訊息用的網址（避免把帶 token 的網址寫進訊息）。"""
        shown = display_url or url
        elapsed = 0.0
        status: int | None = None
        error: str | None = None
        resp: requests.Response | None = None
        for attempt in range(1 + self.retries):
            key = self._wait_turn(url)
            start = self.clock()
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
                status = resp.status_code
                block = blocked_reason(resp.content)
                if block:
                    error = f"HTTP {status}，{block}"
                elif 200 <= status < 400:
                    error = None
                else:
                    error = f"HTTP {status}"
            except requests.RequestException as e:
                resp, status, block = None, None, None
                error = redact(f"{type(e).__name__}: {e}")
            finally:
                elapsed += self.clock() - start
                self._last_done[key] = self.clock()
            if error is None or not _should_retry(status, bool(block)):
                break
            if attempt < self.retries:
                log(f"重試 {redact(shown)}：{error}")
        return FetchResult(url=shown, status=status, elapsed_ms=round(elapsed * 1000), error=error, response=resp)

    def get(self, url: str, **kwargs) -> FetchResult:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> FetchResult:
        return self.request("POST", url, **kwargs)
