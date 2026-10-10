import json
from datetime import date
from decimal import Decimal

import pytest

from brief import parse
from brief.net import blocked_reason
from conftest import fixture_bytes

D = date(2026, 10, 6)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("<p style ='color:red'>+</p>", "+"),
        ("<p style ='color:green'>-</p>", "-"),
        ("  富邦台50        ", "富邦台50"),
        ("A&amp;B", "A&B"),
    ],
)
def test_clean_html(text, expected):
    assert parse.clean_html(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("49,822.55", Decimal("49822.55")),
        ("-1,890,751,296", Decimal("-1890751296")),
        ("+0.55", Decimal("0.55")),
        (" 0.00", Decimal("0")),
        ("-0.83", Decimal("-0.83")),
        ("1,026,204,771,139", Decimal("1026204771139")),
    ],
)
def test_parse_decimal(text, expected):
    assert parse.parse_decimal(text) == expected


@pytest.mark.parametrize("text", ["", "--", "X0.55", "N/A"])
def test_parse_decimal_rejects(text):
    with pytest.raises(parse.SourceError):
        parse.parse_decimal(text)


def test_load_twse_checks_stat_and_date():
    ok = json.dumps({"stat": "OK", "date": "20261006"}).encode()
    assert parse.load_twse(ok, D)["stat"] == "OK"
    # 開休市日期的 stat 是小寫 ok
    assert parse.load_twse(json.dumps({"stat": "ok"}).encode())["stat"] == "ok"
    no_data = json.dumps({"stat": "很抱歉，沒有符合條件的資料!"}).encode()
    with pytest.raises(parse.SourceError, match="stat"):
        parse.load_twse(no_data, D)
    with pytest.raises(parse.SourceError, match="日期"):
        parse.load_twse(ok, date(2026, 10, 5))
    with pytest.raises(parse.SourceError, match="JSON"):
        parse.load_twse(fixture_bytes("twse_blocked_200.html"), D)


def test_blocked_pages():
    assert "7641438221885014413" in blocked_reason(fixture_bytes("twse_blocked_200.html"))
    assert "擋" in blocked_reason(fixture_bytes("twse_blocked_307.html"))
    assert blocked_reason(fixture_bytes("twse_institutional_20261006.json")) is None


def _mi_index():
    """MI_INDEX type=ALLBUT0999（2026-10-06）。"""
    return parse.load_twse(fixture_bytes("twse_index_20261006.json"), D)


def test_mi_index_tables():
    titles = [t.get("title") for t in _mi_index()["tables"]]
    assert "價格指數(臺灣證券交易所)" in titles[0]
    assert "大盤統計資訊" in titles[6]
    assert titles[7] == "漲跌證券數合計"
    assert "每日收盤行情" in titles[8]


def test_index_20261006():
    taiex, sectors, warnings = parse.parse_index(_mi_index())
    assert taiex["close"] == 49822.55
    assert taiex["change"] == 110.51
    assert taiex["change_pct"] == 0.22
    assert taiex["display"] == {"close": "49,822.55", "change": "+110.51", "change_pct": "+0.22%"}
    assert warnings == []

    names = [s["name"] for s in sectors]
    assert len(sectors) == 32 and set(names) == set(parse.SECTORS)
    assert not any(n.endswith("類指數") for n in names)
    for excluded in ("電子工業", "化學生技醫療", "水泥窯製", "塑膠化工", "機電"):
        assert excluded not in names
    pcts = [s["change_pct"] for s in sectors]
    assert pcts == sorted(pcts, reverse=True)

    by_name = {s["name"]: s for s in sectors}
    # 下跌時百分比本身就帶負號，不能和「漲跌」欄的 - 相乘變成正的
    assert by_name["生技醫療"]["change_pct"] == -0.83
    assert by_name["生技醫療"]["display"] == {"close": "90.80", "change_pct": "-0.83%"}
    assert by_name["半導體"]["display"] == {"close": "1,681.90", "change_pct": "-0.26%"}
    assert sectors[0]["name"] == "油電燃氣" and sectors[0]["display"]["change_pct"] == "+2.69%"


def test_index_warns_on_unknown_sector():
    data = _mi_index()
    table = data["tables"][0]
    table["data"].append(["新興產業類指數", "100.00", "<p style ='color:red'>+</p>", "1.00", "1.01", ""])
    table["data"] = [r for r in table["data"] if r[0] != "航運類指數"]
    _, sectors, warnings = parse.parse_index(data)
    assert len(sectors) == 31
    assert any("新興產業類指數" in w for w in warnings)
    assert any("航運" in w for w in warnings)


def test_turnover_20261006():
    # 表 6「總計(1~15)」的成交金額，和之前 FMTQIK 的成交金額一樣
    assert parse.parse_turnover(_mi_index()) == {"value_twd": 1026204771139, "display": {"value": "10,262.0 億"}}


def test_turnover_missing_total():
    data = _mi_index()
    data["tables"][6]["data"] = [r for r in data["tables"][6]["data"] if not r[0].startswith("總計")]
    with pytest.raises(parse.SourceError, match="總計"):
        parse.parse_turnover(data)


def test_missing_table():
    data = _mi_index()
    del data["tables"][6]
    with pytest.raises(parse.SourceError, match="大盤統計資訊"):
        parse.parse_turnover(data)


def test_breadth_20261006():
    # 表 7 的「股票」欄：上漲 462(10)、下跌 519(2)，括號裡的漲停、跌停不取
    assert parse.parse_breadth(_mi_index()) == {
        "up": 462, "down": 519, "display": {"up": "462 家", "down": "519 家"},
    }


@pytest.mark.parametrize("text, expected", [("7,356(70)", 7356), ("462(10)", 462), ("1,356", 1356), ("0", 0)])
def test_count(text, expected):
    assert parse._count(text) == expected


@pytest.mark.parametrize("text", ["", "--", "(10)", "462(10"])
def test_count_rejects(text):
    with pytest.raises(parse.SourceError):
        parse._count(text)


def test_institutional_20261006():
    inst = parse.parse_institutional(parse.load_twse(fixture_bytes("twse_institutional_20261006.json"), D))
    assert inst == {
        "foreign": {"net_twd": -6657341610, "display": "-66.6 億"},
        "investment_trust": {"net_twd": -14264918768, "display": "-142.6 億"},
        "dealer": {"net_twd": 1721212199, "display": "+17.2 億"},
        "total": {"net_twd": -19201048179, "display": "-192.0 億"},
    }
    assert sum(inst[k]["net_twd"] for k in ("foreign", "investment_trust", "dealer")) == inst["total"]["net_twd"]


def test_institutional_foreign_dealer_not_counted_twice():
    """外資自營商已經算在自營商（自行買賣 + 避險）裡，外資不能再加。10/6 外資自營商是 0，這裡改成 5 億來測。"""
    data = parse.load_twse(fixture_bytes("twse_institutional_20261006.json"), D)
    rows = {r[0]: r for r in data["data"]}
    rows["外資自營商"][3] = "500,000,000"
    rows["自營商(自行買賣)"][3] = "4,111,963,495"  # 3,611,963,495 + 5 億
    rows["合計"][3] = "-18,701,048,179"  # -19,201,048,179 + 5 億
    inst = parse.parse_institutional(data)
    assert inst["foreign"]["net_twd"] == -6657341610
    assert inst["dealer"]["net_twd"] == 2221212199
    assert sum(inst[k]["net_twd"] for k in ("foreign", "investment_trust", "dealer")) == inst["total"]["net_twd"]


def test_margin_20261006():
    m = parse.parse_margin(parse.load_twse(fixture_bytes("twse_margin_20261006.json"), D))
    assert m == {
        "financing_balance_k_twd": 637657044,
        "financing_change_k_twd": 4305323,
        "short_balance_lots": 214529,
        "short_change_lots": -3929,
        "display": {
            "financing_balance": "6,376.6 億",
            "financing_change": "+43.1 億",
            "short_balance": "214,529 張",
            "short_change": "-3,929 張",
        },
    }


def test_t86_20261006():
    data = parse.load_twse(fixture_bytes("twse_t86_ALL_20261006.json"), D)
    got = parse.parse_t86(data, ["0050", "006208", "0056", "00878", "00919", "9999"])
    assert set(got) == {"0050", "006208", "0056", "00878", "00919"}
    assert got["0050"] == {"foreign": -15986082, "trust": -40000, "dealer": -568186}
    assert got["00919"]["foreign"] == 4287787


def test_t86_foreign_excludes_foreign_dealer():
    data = parse.load_twse(fixture_bytes("twse_t86_ALL_20261006.json"), D)
    f = data["fields"]
    row = next(r for r in data["data"] if r[0].strip() == "0050")
    row[f.index("外資自營商買賣超股數")] = "1,000,000"
    assert parse.parse_t86(data, ["0050"])["0050"]["foreign"] == -15986082


def test_daily_quotes_20261006():
    got = parse.parse_daily_quotes(_mi_index(), ["0050", "006208", "0056", "00878", "00919", "9999"])
    assert set(got) == {"0050", "006208", "0056", "00878", "00919"}
    # 表 8 的漲跌符號 HTML 和表 0 不同（`<p style= color:red>+</p>`），漲跌價差不帶正負號
    assert got["0050"] == {"close": "116.50", "sign": "+", "diff": "0.55", "volume": "70,945,715"}
    fields, warning = parse.etf_price_fields(got["0050"])
    assert warning is None
    assert fields == {
        "close": 116.5, "change": 0.55, "change_pct": 0.47, "volume_lots": 70946,
        "display": {"close": "116.50", "change_pct": "+0.47%", "volume": "70,946 張"},
    }
    fields, _ = parse.etf_price_fields(got["006208"])
    assert fields["display"] == {"close": "265.90", "change_pct": "+0.21%", "volume": "2,959 張"}


def test_daily_quotes_down_and_unchanged():
    got = parse.parse_daily_quotes(_mi_index(), ["00403A", "00407A"])
    assert got["00403A"]["sign"] == "-" and got["00403A"]["diff"] == "0.02"
    down, warning = parse.etf_price_fields(got["00403A"])
    # 收盤 11.42、跌 0.02 → -0.02 / 11.44 × 100 = -0.1748…
    assert warning is None and down["change"] == -0.02 and down["display"]["change_pct"] == "-0.17%"
    assert got["00407A"]["sign"] == ""  # `<p> </p>`
    flat, warning = parse.etf_price_fields(got["00407A"])
    assert warning is None and flat["change"] == 0.0 and flat["display"]["change_pct"] == "0.00%"


def test_daily_quotes_no_comparison_mark():
    # 2614 東森在 10/6 是 `<p>X</p>`（不比價，例如除權息當天），漲跌價差 0.00
    raw = parse.parse_daily_quotes(_mi_index(), ["2614"])["2614"]
    assert raw["sign"] == "X"
    fields, warning = parse.etf_price_fields(raw)
    assert fields["change"] is None and fields["change_pct"] is None
    assert fields["display"]["change_pct"] is None and fields["display"]["close"] == "15.95"
    assert "'X'" in warning


def test_daily_quotes_no_trade():
    # 00625K 在 10/6 沒成交，收盤價是 --
    raw = parse.parse_daily_quotes(_mi_index(), ["00625K"])["00625K"]
    with pytest.raises(parse.SourceError, match="--"):
        parse.etf_price_fields(raw)


def _ex_dividend():
    return parse.load_twse(fixture_bytes("twse_ex_dividend.json"))


def test_ex_dividend_window():
    names = {"0050": "元大台灣50", "0056": "元大高股息"}
    # 報告日 10/08：10/08～10/22 含頭尾，0056 的 10/22 在範圍內；現金股利是「待公告實際收益分配金額」的 HTML
    got, warnings = parse.parse_ex_dividend(_ex_dividend(), names, date(2026, 10, 8), date(2026, 10, 22))
    assert got == [{
        "code": "0056", "name": "元大高股息", "date": "2026-10-22", "type": "息",
        "cash_dividend": None, "display": {"cash_dividend": "尚未公告"},
    }]
    assert warnings == []
    # 報告日 10/07：範圍到 10/21，0056 不在範圍內
    assert parse.parse_ex_dividend(_ex_dividend(), names, date(2026, 10, 7), date(2026, 10, 21)) == ([], [])


def test_ex_dividend_cash():
    got, _ = parse.parse_ex_dividend(_ex_dividend(), {"00400A": "主動國泰動能高息"}, date(2026, 10, 7), date(2026, 10, 21))
    assert got[0]["date"] == "2026-10-08"
    assert got[0]["cash_dividend"] == 0.12
    assert got[0]["display"]["cash_dividend"] == "0.12 元"


def test_ex_dividend_unknown_cash_text():
    data = _ex_dividend()
    row = next(r for r in data["data"] if r[1] == "00400A")
    row[data["fields"].index("現金股利")] = "另行公告"
    got, warnings = parse.parse_ex_dividend(data, {"00400A": "主動國泰動能高息"}, date(2026, 10, 7), date(2026, 10, 21))
    assert got[0]["cash_dividend"] is None and got[0]["display"]["cash_dividend"] == "尚未公告"
    assert len(warnings) == 1 and "另行公告" in warnings[0]


def test_holiday_20261006():
    cal = parse.parse_holiday(parse.load_twse(fixture_bytes("twse_holiday.json")))
    assert cal.source == "twse" and cal.unknown == []
    assert date(2026, 10, 9) in cal.closed


def test_holiday_bad_date():
    data = parse.load_twse(fixture_bytes("twse_holiday.json"))
    data["data"][0][0] = "115/01/01"
    with pytest.raises(parse.SourceError, match="日期"):
        parse.parse_holiday(data)


def test_holiday_empty():
    data = parse.load_twse(fixture_bytes("twse_holiday.json"))
    data["data"] = []
    with pytest.raises(parse.SourceError, match="空"):
        parse.parse_holiday(data)
