"""python -m brief collect：抓資料、整理成 data/<報告日>.json。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import articles, fmt, news, parse, sources
from .config import WatchItem, load_watchlist
from .dates import TAIPEI, HolidayCalendar
from .net import Fetcher, log, redact

EXIT_OK, EXIT_ERROR, EXIT_PARTIAL, EXIT_CLOSED = 0, 1, 2, 3
EX_DIVIDEND_DAYS = 14  # 報告日起 14 天內（含頭尾）


class Collector:
    """逐一請求、解析，把每個來源的結果記在 sources；失敗不中止。"""

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self.sources: list[dict] = []
        self.warnings: list[str] = []

    def fetch(self, name: str, url: str, parser: Callable[[bytes], Any]) -> Any:
        r = self.fetcher.get(url)
        value, error = None, r.error
        if r.ok:
            try:
                value = parser(r.response.content)
            except Exception as e:  # 解析失敗也只記錄，不中止
                error = f"{type(e).__name__}: {e}"
        error = redact(error) if error else None
        if error:
            log(f"{name} 失敗：{error}（{url}）")
        self.sources.append({"name": name, "url": url, "ok": error is None, "error": error, "elapsed_ms": r.elapsed_ms})
        return value

    def part(self, label: str, fn: Callable[[], Any]) -> Any:
        """同一個回應裡的一部分（例如 MI_INDEX 的一個表）。解析失敗時只有這部分是 null，最近一個來源記成失敗。"""
        try:
            return fn()
        except Exception as e:
            source = self.sources[-1]
            error = redact(f"{label}：{type(e).__name__}: {e}")
            log(f"{source['name']} 失敗：{error}（{source['url']}）")
            source["ok"] = False
            source["error"] = error if source["error"] is None else f"{source['error']}；{error}"
            return None

    @property
    def all_ok(self) -> bool:
        return all(s["ok"] for s in self.sources)


def _empty_etf(item: WatchItem) -> dict:
    return {
        "code": item.code, "name": item.name,
        "close": None, "change": None, "change_pct": None, "volume_lots": None,
        "foreign_net_lots": None, "trust_net_lots": None, "dealer_net_lots": None,
        "display": {"close": None, "change_pct": None, "volume": None,
                    "foreign_net": None, "trust_net": None, "dealer_net": None},
    }


def collect(
    report_date: date,
    fetcher: Fetcher,
    watchlist: list[WatchItem],
    now: Callable[[], datetime] = lambda: datetime.now(TAIPEI),
    cnyes_cache: Path | None = None,
) -> tuple[int, dict]:
    """cnyes_cache：鉅亨網內文的快取目錄（v2 articles 讀）；None 就不存。"""
    c = Collector(fetcher)

    cal = c.fetch("twse_holiday", sources.TWSE_HOLIDAY, lambda b: parse.parse_holiday(parse.load_twse(b)))
    if cal is None:
        cal = HolidayCalendar(source="weekend_only")
    for row in cal.unknown:
        c.warnings.append(f"開休市清單有判斷不了的列（當作休市）：{row}")
    if cal.source == "twse" and not any(d.year == report_date.year for d in cal.closed):
        c.warnings.append(f"開休市清單裡沒有 {report_date.year} 年的日期，可能還沒更新")

    open_today = cal.is_trading_day(report_date)
    data_date = cal.previous_trading_day(report_date)
    result: dict[str, Any] = {
        "report_date": report_date.isoformat(),
        "data_date": data_date.isoformat(),
        "market_open_today": open_today,
        "holiday_source": cal.source,
    }
    if not open_today:
        result["generated_at"] = now().isoformat(timespec="seconds")
        return EXIT_CLOSED, result

    dd = data_date
    codes = [w.code for w in watchlist]
    # 加權指數、類股、成交金額、漲跌家數、ETF 價格都在 MI_INDEX 這一個回應裡，每個表分開解析。
    taiex = sectors = turnover = breadth = quotes = None
    mi = c.fetch("twse_index", sources.twse_index(dd), lambda b: parse.load_twse(b, dd))
    if mi is not None:
        idx = c.part("價格指數", lambda: parse.parse_index(mi))
        if idx:
            taiex, sectors = idx[0], idx[1]
            c.warnings.extend(idx[2])
        turnover = c.part("大盤統計資訊", lambda: parse.parse_turnover(mi))
        breadth = c.part("漲跌證券數合計", lambda: parse.parse_breadth(mi))
        quotes = c.part("每日收盤行情", lambda: parse.parse_daily_quotes(mi, codes))

    institutional = c.fetch("twse_institutional", sources.twse_institutional(dd),
                            lambda b: parse.parse_institutional(parse.load_twse(b, dd)))
    margin = c.fetch("twse_margin", sources.twse_margin(dd), lambda b: parse.parse_margin(parse.load_twse(b, dd)))
    t86 = c.fetch("twse_etf_institutional", sources.twse_etf_institutional(dd),
                  lambda b: parse.parse_t86(parse.load_twse(b, dd), codes))

    etfs = []
    for item in watchlist:
        etf = _empty_etf(item)
        raw = quotes.get(item.code) if quotes is not None else None
        if quotes is not None and raw is None:
            c.warnings.append(f"每日收盤行情裡沒有 {item.code}，價格留空")
        if raw is not None:
            try:
                fields, warning = parse.etf_price_fields(raw)
            except parse.SourceError as e:  # 例如沒成交、收盤價是 --：只有這一檔留空
                c.warnings.append(f"{item.code} 價格留空：{e}")
            else:
                if warning:
                    c.warnings.append(f"{item.code} {warning}")
                display = fields.pop("display")
                etf.update(fields)
                etf["display"].update(display)
        if t86 is not None:
            inst = t86.get(item.code)
            if inst is None:
                c.warnings.append(f"T86 裡沒有 {item.code}，法人買賣超留空")
            else:
                for key in ("foreign", "trust", "dealer"):
                    etf[f"{key}_net_lots"] = fmt.to_lots(inst[key])
                    etf["display"][f"{key}_net"] = fmt.lots(inst[key], signed=True)
        etfs.append(etf)

    names = {w.code: w.name for w in watchlist}
    end = report_date + timedelta(days=EX_DIVIDEND_DAYS)
    ex = c.fetch("twse_ex_dividend", sources.TWSE_EX_DIVIDEND,
                 lambda b: parse.parse_ex_dividend(parse.load_twse(b), names, report_date, end))
    ex_dividend = None
    if ex is not None:
        ex_dividend, ex_warnings = ex
        c.warnings.extend(ex_warnings)

    def parse_cnyes(body: bytes, source: str) -> list[news.NewsItem]:
        items = news.parse_cnyes(body, source)
        if cnyes_cache is not None:
            _save_cnyes_cache(c, body, cnyes_cache)
        return items

    items: list[news.NewsItem] = []
    for name, url, parser in (
        ("news_yahoo", sources.NEWS_YAHOO, news.parse_rss),
        ("news_udn", sources.NEWS_UDN, news.parse_rss),
        ("news_cnyes", sources.NEWS_CNYES, parse_cnyes),
    ):
        got = c.fetch(name, url, lambda b, p=parser, n=name: p(b, news.SOURCE_NAMES[n]))
        items.extend(got or [])
    start = datetime(dd.year, dd.month, dd.day, 13, 30, tzinfo=TAIPEI)
    news_items = news.finalize(items, start, now())

    result.update({
        "generated_at": now().isoformat(timespec="seconds"),
        "sources": c.sources,
        "warnings": c.warnings,
        "index": {"taiex": taiex, "turnover": turnover, "breadth": breadth},
        "sectors": sectors,
        "institutional": institutional,
        "margin": margin,
        "etfs": etfs,
        "ex_dividend": ex_dividend,
        "news": [n.to_json() for n in news_items],
    })
    return (EXIT_OK if c.all_ok else EXIT_PARTIAL), result


def _save_cnyes_cache(c: Collector, body: bytes, cache_dir: Path) -> None:
    """鉅亨網列表 API 每則都附 content（全文），存起來給 articles 用。存不了只記 warning，不影響新聞標題。"""
    try:
        _, missing = articles.save_cnyes_cache(body, cache_dir)
    except Exception as e:
        c.warnings.append(redact(f"鉅亨網內文存不進快取：{type(e).__name__}: {e}"))
        return
    if missing:
        c.warnings.append(f"鉅亨網有 {len(missing)} 則沒有 content，articles 讀不到內文：{'、'.join(missing)}")


def write_json(result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result['report_date']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run(report_date: date | None = None, out_dir: Path = Path("data"), *, fetcher: Fetcher | None = None) -> int:
    try:
        report_date = report_date or datetime.now(TAIPEI).date()
        code, result = collect(report_date, fetcher or Fetcher(), load_watchlist(), cnyes_cache=articles.CNYES_CACHE)
        path = write_json(result, out_dir)
    except Exception as e:
        log(f"collect 失敗：{type(e).__name__}: {e}")
        return EXIT_ERROR
    failed = [s["name"] for s in result.get("sources", []) if not s["ok"]]
    print(f"已寫入 {path}，結束碼 {code}" + (f"，失敗的來源：{'、'.join(failed)}" if failed else ""))
    return code
