import json
from datetime import date, datetime

import requests

from brief import collect, sources
from brief.config import load_watchlist
from brief.dates import TAIPEI
from brief.net import Fetcher
from conftest import fake_session, fixture_bytes

D = date(2026, 10, 6)
WATCH = load_watchlist()
NOW = datetime(2026, 10, 7, 3, 4, 0, tzinfo=TAIPEI)


def routes(**override):
    """網址 → 在雲端抓到的真實回應（行情、法人、融資融券是 2026-10-06 的）。"""
    r = {
        sources.TWSE_HOLIDAY: (200, fixture_bytes("twse_holiday.json")),
        sources.twse_index(D): (200, fixture_bytes("twse_index_20261006.json")),
        sources.twse_institutional(D): (200, fixture_bytes("twse_institutional_20261006.json")),
        sources.twse_margin(D): (200, fixture_bytes("twse_margin_20261006.json")),
        sources.twse_etf_institutional(D): (200, fixture_bytes("twse_t86_ALL_20261006.json")),
        sources.TWSE_EX_DIVIDEND: (200, fixture_bytes("twse_ex_dividend.json")),
        sources.NEWS_YAHOO: (200, fixture_bytes("news_yahoo.xml")),
        sources.NEWS_UDN: (200, fixture_bytes("news_udn.xml")),
        sources.NEWS_CNYES: (200, fixture_bytes("news_cnyes.json")),
    }
    r.update(override)
    return r


def run_collect(report_date, table, cnyes_cache=None):
    def handler(req):
        if req.url not in table:
            return requests.ConnectionError(f"沒準備這個網址：{req.url}")
        return table[req.url]

    session, adapter = fake_session(handler)
    code, result = collect.collect(report_date, Fetcher(session, sleep=lambda s: None), WATCH, now=lambda: NOW,
                                   cnyes_cache=cnyes_cache)
    return code, result, adapter


BLOCKED_307 = (307, fixture_bytes("twse_blocked_307.html"))


def _mi_index_with(change):
    data = json.loads(fixture_bytes("twse_index_20261006.json"))
    change(data)
    return (200, json.dumps(data, ensure_ascii=False).encode())


def test_collect_all_ok_exit_0():
    code, result, adapter = run_collect(date(2026, 10, 7), routes())
    assert code == collect.EXIT_OK
    assert result["report_date"] == "2026-10-07"
    assert result["data_date"] == "2026-10-06"
    assert result["market_open_today"] is True
    assert result["holiday_source"] == "twse"
    assert result["generated_at"] == "2026-10-07T03:04:00+08:00"
    assert all(s["ok"] for s in result["sources"])
    assert result["warnings"] == []

    # 證交所只有 6 個請求：開休市、MI_INDEX、BFI82U、MI_MARGN、T86、TWT48U
    assert [s["name"] for s in result["sources"]] == [
        "twse_holiday", "twse_index", "twse_institutional", "twse_margin", "twse_etf_institutional",
        "twse_ex_dividend", "news_yahoo", "news_udn", "news_cnyes",
    ]
    hosts = [requests.utils.urlparse(r.url).hostname for r in adapter.requests]
    assert hosts.count("www.twse.com.tw") == 6
    assert "openapi.twse.com.tw" not in hosts

    assert result["index"]["taiex"]["display"] == {"close": "49,822.55", "change": "+110.51", "change_pct": "+0.22%"}
    assert result["index"]["turnover"] == {"value_twd": 1026204771139, "display": {"value": "10,262.0 億"}}
    assert result["index"]["breadth"] == {"up": 462, "down": 519, "display": {"up": "462 家", "down": "519 家"}}
    assert result["institutional"]["foreign"] == {"net_twd": -6657341610, "display": "-66.6 億"}
    assert result["margin"]["display"]["financing_change"] == "+43.1 億"
    assert len(result["sectors"]) == 32

    etfs = {e["code"]: e for e in result["etfs"]}
    assert list(etfs) == ["0050", "006208", "0056", "00878", "00919"]
    e0050 = etfs["0050"]
    assert e0050["name"] == "元大台灣50"
    assert e0050["close"] == 116.5 and e0050["change"] == 0.55 and e0050["change_pct"] == 0.47
    assert e0050["volume_lots"] == 70946 and e0050["foreign_net_lots"] == -15986
    assert e0050["display"] == {
        "close": "116.50", "change_pct": "+0.47%", "volume": "70,946 張",
        "foreign_net": "-15,986 張", "trust_net": "-40 張", "dealer_net": "-568 張",
    }
    assert etfs["006208"]["display"] == {
        "close": "265.90", "change_pct": "+0.21%", "volume": "2,959 張",
        "foreign_net": "+170 張", "trust_net": "-132 張", "dealer_net": "+199 張",
    }
    assert etfs["0056"]["display"]["close"] == "58.10" and etfs["0056"]["display"]["change_pct"] == "+0.43%"

    assert result["ex_dividend"] == []  # 0056 的 10/22 超過 10/07 起 14 天
    assert 0 < len(result["news"]) <= 150
    assert result["news"][0]["published_at"] <= "2026-10-07T03:04:00+08:00"
    json.dumps(result, ensure_ascii=False)  # 可以序列化


def test_collect_ex_dividend_in_window():
    # 報告日 10/08：0056 的 10/22 除息在範圍內，現金股利待公告
    # 資料日 10/07 的行情、法人沒有準備（連線失敗），不影響除息預告
    _, result, _ = run_collect(date(2026, 10, 8), routes())
    assert result["data_date"] == "2026-10-07"
    assert result["ex_dividend"] == [{
        "code": "0056", "name": "元大高股息", "date": "2026-10-22", "type": "息",
        "cash_dividend": None, "display": {"cash_dividend": "尚未公告"},
    }]


def test_collect_mi_index_blocked():
    # MI_INDEX 被擋：大盤、類股、成交金額、漲跌家數、ETF 價格都留空，法人買賣超還是有
    code, result, _ = run_collect(date(2026, 10, 7), routes(**{sources.twse_index(D): BLOCKED_307}))
    assert code == collect.EXIT_PARTIAL
    failed = [s for s in result["sources"] if not s["ok"]]
    assert [s["name"] for s in failed] == ["twse_index"]
    assert "擋" in failed[0]["error"]
    assert result["index"] == {"taiex": None, "turnover": None, "breadth": None}
    assert result["sectors"] is None
    e0056 = result["etfs"][2]
    assert e0056["close"] is None and e0056["display"]["close"] is None
    assert e0056["display"]["foreign_net"] == "-1,722 張"
    assert result["warnings"] == []  # 整個來源失敗記在 sources，不重複記 warnings


def test_collect_one_mi_index_table_broken():
    # 表 6 不見了：只有成交金額留空，其他表照常；來源記成失敗
    code, result, _ = run_collect(date(2026, 10, 7), routes(**{
        sources.twse_index(D): _mi_index_with(lambda d: d["tables"].pop(6)),
    }))
    assert code == collect.EXIT_PARTIAL
    idx = next(s for s in result["sources"] if s["name"] == "twse_index")
    assert not idx["ok"] and idx["error"].startswith("大盤統計資訊：") and "找不到「大盤統計資訊」表" in idx["error"]
    assert result["index"]["turnover"] is None
    assert result["index"]["taiex"]["display"]["close"] == "49,822.55"
    assert result["index"]["breadth"]["up"] == 462
    assert result["etfs"][0]["display"]["close"] == "116.50"


def test_collect_holiday_exit_3():
    code, result, adapter = run_collect(date(2026, 10, 9), routes())
    assert code == collect.EXIT_CLOSED
    assert result == {
        "report_date": "2026-10-09",
        "data_date": "2026-10-08",
        "market_open_today": False,
        "holiday_source": "twse",
        "generated_at": "2026-10-07T03:04:00+08:00",
    }
    assert len(adapter.requests) == 1  # 只抓了開休市清單


def test_collect_weekend_exit_3_without_holiday_list():
    code, result, _ = run_collect(date(2026, 10, 10), routes(**{sources.TWSE_HOLIDAY: BLOCKED_307}))
    assert code == collect.EXIT_CLOSED
    assert result["holiday_source"] == "weekend_only"


def test_collect_holiday_list_blocked_falls_back_to_weekend():
    code, result, _ = run_collect(date(2026, 10, 7), routes(**{sources.TWSE_HOLIDAY: BLOCKED_307}))
    assert code == collect.EXIT_PARTIAL
    assert result["holiday_source"] == "weekend_only"
    assert result["data_date"] == "2026-10-06"
    holiday = next(s for s in result["sources"] if s["name"] == "twse_holiday")
    assert not holiday["ok"] and "擋" in holiday["error"]


def test_collect_stat_not_ok_is_failure():
    no_data = (200, json.dumps({"stat": "很抱歉，沒有符合條件的資料!"}).encode())
    code, result, _ = run_collect(date(2026, 10, 7), routes(**{sources.twse_index(D): no_data}))
    assert code == collect.EXIT_PARTIAL
    idx = next(s for s in result["sources"] if s["name"] == "twse_index")
    assert not idx["ok"] and "stat" in idx["error"]
    assert result["index"]["taiex"] is None and result["sectors"] is None


def test_run_writes_file(tmp_path):
    session, _ = fake_session(lambda req: routes().get(req.url, requests.ConnectionError("x")))
    code = collect.run(date(2026, 10, 9), tmp_path, fetcher=Fetcher(session, sleep=lambda s: None))
    assert code == collect.EXIT_CLOSED
    data = json.loads((tmp_path / "2026-10-09.json").read_text(encoding="utf-8"))
    assert data["market_open_today"] is False


def _set_quote(code, column, value):
    def change(data):
        table = data["tables"][8]
        row = next(r for r in table["data"] if r[0] == code)
        row[table["fields"].index(column)] = value
    return change


def test_bad_etf_price_only_that_etf_is_empty():
    # 0050 收盤價變成 --（沒成交）：只有 0050 的價格留空，記 warning，來源還是成功
    code, result, _ = run_collect(date(2026, 10, 7), routes(**{
        sources.twse_index(D): _mi_index_with(_set_quote("0050", "收盤價", "--")),
    }))
    assert code == collect.EXIT_OK
    e0050 = result["etfs"][0]
    assert e0050["close"] is None and e0050["display"]["close"] is None
    assert e0050["foreign_net_lots"] == -15986
    assert result["etfs"][1]["display"]["close"] == "265.90"
    assert len(result["warnings"]) == 1 and result["warnings"][0].startswith("0050 價格留空") and "--" in result["warnings"][0]


def test_etf_no_comparison_mark_warns():
    # 除息當天漲跌是 X（不比價）：收盤價、成交量照常，漲跌幅留空，記 warning
    code, result, _ = run_collect(date(2026, 10, 7), routes(**{
        sources.twse_index(D): _mi_index_with(_set_quote("0056", "漲跌(+/-)", "<p>X</p>")),
    }))
    assert code == collect.EXIT_OK
    e0056 = result["etfs"][2]
    assert e0056["display"]["close"] == "58.10" and e0056["display"]["change_pct"] is None
    assert e0056["change"] is None and e0056["change_pct"] is None
    assert result["warnings"] == ["0056 漲跌不是一般格式：漲跌(+/-) 'X'、漲跌價差 '0.25'"]


def test_etf_missing_from_daily_quotes_warns():
    def drop(data):
        data["tables"][8]["data"] = [r for r in data["tables"][8]["data"] if r[0] != "00919"]
    code, result, _ = run_collect(date(2026, 10, 7), routes(**{sources.twse_index(D): _mi_index_with(drop)}))
    assert code == collect.EXIT_OK
    assert result["etfs"][4]["close"] is None and result["etfs"][4]["display"]["foreign_net"] == "+4,288 張"
    assert result["warnings"] == ["每日收盤行情裡沒有 00919，價格留空"]


def test_collect_saves_cnyes_cache(tmp_path):
    # v2：鉅亨網列表 API 的 content 存成 .cache/cnyes/<newsId>.txt，給 articles 讀
    cache = tmp_path / "cnyes"
    code, result, adapter = run_collect(date(2026, 10, 7), routes(**{
        sources.NEWS_CNYES: (200, fixture_bytes("news_cnyes_content.json")),
    }), cnyes_cache=cache)
    assert code == collect.EXIT_OK
    assert result["warnings"] == []
    assert sorted(x.name for x in cache.iterdir()) == ["6624009.txt", "6624323.txt"]
    assert "news.cnyes.com" not in [requests.utils.urlparse(r.url).hostname for r in adapter.requests]


def test_collect_cnyes_without_content_warns(tmp_path):
    # 列表 API 不再附 content：新聞標題照常，記一筆 warning，不影響結束碼
    code, result, _ = run_collect(date(2026, 10, 7), routes(), cnyes_cache=tmp_path / "cnyes")
    assert code == collect.EXIT_OK
    assert len(result["warnings"]) == 1 and result["warnings"][0].startswith("鉅亨網有 30 則沒有 content")
    assert any(n["source"] == "鉅亨網" for n in result["news"])


def test_collect_cnyes_cache_write_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")  # 快取目錄的位置是一個檔案，建不了目錄
    code, result, _ = run_collect(date(2026, 10, 7), routes(), cnyes_cache=blocker / "cnyes")
    assert code == collect.EXIT_OK
    assert result["warnings"][0].startswith("鉅亨網內文存不進快取")
    assert any(n["source"] == "鉅亨網" for n in result["news"])
