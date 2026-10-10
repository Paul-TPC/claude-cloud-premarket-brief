"""python -m brief check：逐一請求每個來源，只看連不連得到。"""

from __future__ import annotations

from datetime import date, datetime

from . import sources
from .dates import TAIPEI, previous_weekday
from .net import Fetcher, redact


def targets(d: date) -> list[tuple[str, str, bool]]:
    """(名稱, 網址, 是否跟隨轉址)。網址照 SPEC 第 5 節，T86 用 SPEC 寫的 ALL。"""
    return [
        ("twse_holiday", sources.TWSE_HOLIDAY, True),
        ("twse_index", sources.twse_index(d), True),
        ("twse_institutional", sources.twse_institutional(d), True),
        ("twse_margin", sources.twse_margin(d), True),
        ("twse_etf_institutional", sources.twse_etf_institutional(d, "ALL"), True),
        ("twse_ex_dividend", sources.TWSE_EX_DIVIDEND, True),
        ("news_yahoo", sources.NEWS_YAHOO, True),
        ("news_udn", sources.NEWS_UDN, True),
        ("news_cnyes", sources.NEWS_CNYES, True),
        # v2 articles 會抓的網域；經濟日報、tw.stock.yahoo.com 和上面的新聞來源同一個網域，鉅亨網讀 collect 的快取
        ("article_yahoo_news", sources.YAHOO_NEWS_ROOT, True),
        # 不帶 token。根目錄會轉址到 core.telegram.org，不跟過去，只看 api.telegram.org 本身有沒有回應。
        ("telegram", sources.TELEGRAM_ROOT, False),
    ]


def run(fetcher: Fetcher | None = None, *, today: date | None = None) -> int:
    fetcher = fetcher or Fetcher()
    today = today or datetime.now(TAIPEI).date()
    d = previous_weekday(today)
    print(f"check：{datetime.now(TAIPEI).isoformat(timespec='seconds')}，網址的日期參數用 {d.isoformat()}")
    print("| 來源 | 狀態碼 | 耗時（ms） | 錯誤訊息 | 網址 |")
    print("|---|---|---|---|---|")
    all_ok = True
    for name, url, follow in targets(d):
        r = fetcher.get(url, allow_redirects=follow)
        all_ok = all_ok and r.ok
        status = r.status if r.status is not None else "—"
        error = (r.error or "").replace("|", "\\|")
        print(f"| {name} | {status} | {r.elapsed_ms} | {redact(error)} | {url} |")
    print("結果：全部連得到" if all_ok else "結果：有來源連不到")
    return 0 if all_ok else 2
