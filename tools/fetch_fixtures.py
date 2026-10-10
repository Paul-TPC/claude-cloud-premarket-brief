"""把各來源的真實回應存成 tests/fixtures/（開發用，不是每天跑的）。

用法：python tools/fetch_fixtures.py 2026-10-06 [輸出目錄] [只抓的檔名 ...]
請求規矩和 collect 一樣（逾時、重試、同網域間隔）。大的回應（MI_INDEX、T86）存好之後自己用 gzip 壓縮。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brief import sources  # noqa: E402
from brief.net import Fetcher, log  # noqa: E402


def main() -> int:
    d = date.fromisoformat(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("tests/fixtures")
    only = set(sys.argv[3:])
    out.mkdir(parents=True, exist_ok=True)
    ymd = d.strftime("%Y%m%d")
    targets = [
        ("twse_holiday.json", sources.TWSE_HOLIDAY),
        (f"twse_index_{ymd}.json", sources.twse_index(d)),
        (f"twse_institutional_{ymd}.json", sources.twse_institutional(d)),
        (f"twse_margin_{ymd}.json", sources.twse_margin(d)),
        (f"twse_t86_{sources.T86_SELECT_TYPE}_{ymd}.json", sources.twse_etf_institutional(d)),
        ("twse_ex_dividend.json", sources.TWSE_EX_DIVIDEND),
        ("news_yahoo.xml", sources.NEWS_YAHOO),
        ("news_udn.xml", sources.NEWS_UDN),
        ("news_cnyes.json", sources.NEWS_CNYES),
    ]
    failed = 0
    f = Fetcher()
    for name, url in targets:
        if only and name not in only:
            continue
        r = f.get(url)
        if not r.ok:
            headers = dict(r.response.headers) if r.response is not None else {}
            log(f"{name}：{r.error}；回應標頭：{headers}")
            failed += 1
            continue
        (out / name).write_bytes(r.response.content)
        print(f"{name}\t{r.status}\t{len(r.response.content)} bytes\t{r.elapsed_ms} ms")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
