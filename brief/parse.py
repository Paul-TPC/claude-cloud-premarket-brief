"""證交所回應的解析。只做數字，不做文字判斷。"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from . import fmt
from .dates import HolidayCalendar, parse_holiday_schedule, roc_to_date

# SPEC 5.1：只取這 32 個產業類別。
SECTORS = (
    "水泥", "食品", "塑膠", "紡織纖維", "電機機械", "電器電纜", "化學", "生技醫療", "玻璃陶瓷", "造紙",
    "鋼鐵", "橡膠", "汽車", "半導體", "電腦及週邊設備", "光電", "通信網路", "電子零組件", "電子通路",
    "資訊服務", "其他電子", "建材營造", "航運", "觀光餐旅", "金融保險", "貿易百貨", "油電燃氣",
    "綠能環保", "數位雲端", "運動休閒", "居家生活", "其他",
)
# 合計類，名稱也以「類指數」結尾，但不取。
SECTOR_AGGREGATES = ("水泥窯製", "塑膠化工", "機電", "化學生技醫療", "電子工業")


class SourceError(Exception):
    """回應拿到了，但內容不能用（stat 不是 OK、找不到資料、格式變了）。"""


_TAG_RE = re.compile(r"<[^>]*>")


def clean_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", str(text))).strip()


def parse_decimal(text: str) -> Decimal:
    """`49,822.55`、`-1,890,751,296`、`+0.55`、`<p>+</p>` 這類 → Decimal。"""
    s = clean_html(text).replace(",", "").replace(" ", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise SourceError(f"看不懂的數字：{text!r}") from None


def parse_int(text: str) -> int:
    v = parse_decimal(text)
    if v != v.to_integral_value():
        raise SourceError(f"應該是整數：{text!r}")
    return int(v)


def load_twse(body: bytes, d: date | None = None) -> dict:
    """讀證交所 rwd 的 JSON，檢查 stat 和日期。"""
    try:
        data = json.loads(body)
    except ValueError:
        raise SourceError("回應不是 JSON") from None
    if not isinstance(data, dict):
        raise SourceError("回應格式不是預期的物件")
    stat = data.get("stat")
    # 開休市日期的 stat 是小寫 ok，其他是大寫 OK
    if str(stat).upper() != "OK":
        raise SourceError(f"stat 不是 OK：{stat}")
    if d is not None and data.get("date") and data["date"] != d.strftime("%Y%m%d"):
        raise SourceError(f"回應日期 {data['date']} 和請求的 {d:%Y%m%d} 不一樣")
    return data


def _col(fields: list[str], name: str) -> int:
    try:
        return fields.index(name)
    except ValueError:
        raise SourceError(f"找不到欄位「{name}」，欄位是 {fields}") from None


def _table(data: dict, title: str) -> dict:
    """MI_INDEX 這類有多個表的回應：用標題找表（標題前面可能有日期）。"""
    table = next((t for t in data.get("tables", []) if title in (t.get("title") or "")), None)
    if table is None:
        raise SourceError(f"找不到「{title}」表")
    return table


def parse_holiday(data: dict) -> HolidayCalendar:
    """holidaySchedule（rwd）→ 開休市日曆。日期是西元（`2026-10-09`）。"""
    f = data["fields"]
    i_date, i_name, i_desc = _col(f, "日期"), _col(f, "名稱"), _col(f, "說明")
    rows = []
    for r in data.get("data") or []:
        try:
            d = date.fromisoformat(clean_html(r[i_date]))
        except ValueError:
            raise SourceError(f"看不懂的日期：{r[i_date]!r}") from None
        rows.append((d, clean_html(r[i_name]), clean_html(r[i_desc])))
    if not rows:
        raise SourceError("開休市清單是空的")
    return parse_holiday_schedule(rows)


def _signed_change(sign_cell: str, points: str, pct: str) -> tuple[Decimal, Decimal]:
    """漲跌符號只看「漲跌(+/-)」欄；點數和百分比取絕對值（下跌時百分比本身也帶負號，不能相乘）。"""
    sign = clean_html(sign_cell)
    p = abs(parse_decimal(points))
    c = abs(parse_decimal(pct))
    if sign == "+":
        return p, c
    if sign == "-":
        return -p, -c
    if sign == "" and p == 0:
        return Decimal(0), Decimal(0)
    raise SourceError(f"看不懂的漲跌符號：{sign_cell!r}")


def parse_index(data: dict) -> tuple[dict, list[dict], list[str]]:
    """MI_INDEX 表 0「價格指數(臺灣證券交易所)」→ (加權指數, 類股清單, 警告)。"""
    table = _table(data, "價格指數(臺灣證券交易所)")
    f = table["fields"]
    i_name, i_close, i_sign, i_pts, i_pct = (
        _col(f, "指數"), _col(f, "收盤指數"), _col(f, "漲跌(+/-)"), _col(f, "漲跌點數"), _col(f, "漲跌百分比(%)")
    )
    taiex = None
    sectors: list[dict] = []
    warnings: list[str] = []
    for row in table["data"]:
        name = clean_html(row[i_name])
        if name == "發行量加權股價指數":
            close = parse_decimal(row[i_close])
            chg, pct = _signed_change(row[i_sign], row[i_pts], row[i_pct])
            taiex = {
                "close": float(close), "change": float(chg), "change_pct": float(pct),
                "display": {"close": fmt.index(close), "change": fmt.change(chg), "change_pct": fmt.pct(pct)},
            }
        elif name.endswith("類指數"):
            short = name[: -len("類指數")]
            if short in SECTOR_AGGREGATES:
                continue
            if short not in SECTORS:
                warnings.append(f"MI_INDEX 出現清單外的類指數：{name}")
                continue
            close = parse_decimal(row[i_close])
            _, pct = _signed_change(row[i_sign], row[i_pts], row[i_pct])
            sectors.append({
                "name": short, "close": float(close), "change_pct": float(pct),
                "display": {"close": fmt.index(close), "change_pct": fmt.pct(pct)},
            })
    if taiex is None:
        raise SourceError("找不到「發行量加權股價指數」")
    missing = [s for s in SECTORS if s not in {x["name"] for x in sectors}]
    if missing:
        warnings.append(f"MI_INDEX 缺少類股：{'、'.join(missing)}")
    sectors.sort(key=lambda x: x["change_pct"], reverse=True)
    return taiex, sectors, warnings


def parse_turnover(data: dict) -> dict:
    """MI_INDEX 表 6「大盤統計資訊」→ 「總計(1~15)」的成交金額（和 FMTQIK 的成交金額相同）。"""
    table = _table(data, "大盤統計資訊")
    f = table["fields"]
    i_item, i_value = _col(f, "成交統計"), _col(f, "成交金額(元)")
    row = next((r for r in table["data"] if clean_html(r[i_item]).startswith("總計")), None)
    if row is None:
        raise SourceError("大盤統計資訊找不到「總計」列")
    value = parse_int(row[i_value])
    return {"value_twd": value, "display": {"value": fmt.yi(value, signed=False)}}


_COUNT_RE = re.compile(r"^([\d,]+)(?:\([\d,]+\))?$")


def _count(text: str) -> int:
    """`462(10)` → 462（括號裡是漲停、跌停家數，不取）；`1,356` → 1356。"""
    m = _COUNT_RE.match(clean_html(text).replace(" ", ""))
    if not m:
        raise SourceError(f"看不懂的家數：{text!r}")
    return int(m.group(1).replace(",", ""))


def parse_breadth(data: dict) -> dict:
    """MI_INDEX 表 7「漲跌證券數合計」→ 「股票」欄的上漲、下跌家數。"""
    table = _table(data, "漲跌證券數合計")
    f = table["fields"]
    i_type, i_stock = _col(f, "類型"), _col(f, "股票")
    counts: dict[str, int] = {}
    for row in table["data"]:
        kind = clean_html(row[i_type])
        for key, prefix in (("up", "上漲"), ("down", "下跌")):
            if kind.startswith(prefix):
                counts[key] = _count(row[i_stock])
    for key, prefix in (("up", "上漲"), ("down", "下跌")):
        if key not in counts:
            raise SourceError(f"漲跌證券數合計找不到「{prefix}」列")
    return {
        "up": counts["up"], "down": counts["down"],
        "display": {"up": fmt.count(counts["up"], "家"), "down": fmt.count(counts["down"], "家")},
    }


def parse_institutional(data: dict) -> dict:
    """BFI82U → 三大法人買賣差額（元）。"""
    f = data["fields"]
    i_name, i_net = _col(f, "單位名稱"), _col(f, "買賣差額")
    net = {clean_html(r[i_name]): parse_int(r[i_net]) for r in data.get("data", [])}
    needed = ("自營商(自行買賣)", "自營商(避險)", "投信", "外資及陸資(不含外資自營商)", "合計")
    for n in needed:
        if n not in net:
            raise SourceError(f"找不到「{n}」")
    # 外資自營商已經算在自營商（自行買賣 + 避險）裡，外資不再加，三項加起來才會等於「合計」。
    groups = {
        "foreign": net["外資及陸資(不含外資自營商)"],
        "investment_trust": net["投信"],
        "dealer": net["自營商(自行買賣)"] + net["自營商(避險)"],
        "total": net["合計"],
    }
    return {k: {"net_twd": v, "display": fmt.yi(v, signed=True)} for k, v in groups.items()}


def parse_margin(data: dict) -> dict:
    """MI_MARGN（selectType=MS）→ 融資金額（仟元）、融券（張）的餘額和增減。"""
    table = next((t for t in data.get("tables", []) if "信用交易統計" in (t.get("title") or "")), None)
    if table is None:
        raise SourceError("找不到「信用交易統計」表")
    f = table["fields"]
    i_item, i_prev, i_today = _col(f, "項目"), _col(f, "前日餘額"), _col(f, "今日餘額")
    rows = {clean_html(r[i_item]): r for r in table["data"]}
    for n in ("融資金額(仟元)", "融券(交易單位)"):
        if n not in rows:
            raise SourceError(f"找不到「{n}」")
    fin, short = rows["融資金額(仟元)"], rows["融券(交易單位)"]
    fin_bal, fin_prev = parse_int(fin[i_today]), parse_int(fin[i_prev])
    short_bal, short_prev = parse_int(short[i_today]), parse_int(short[i_prev])
    fin_chg, short_chg = fin_bal - fin_prev, short_bal - short_prev
    return {
        "financing_balance_k_twd": fin_bal, "financing_change_k_twd": fin_chg,
        "short_balance_lots": short_bal, "short_change_lots": short_chg,
        "display": {
            "financing_balance": fmt.yi(fin_bal, signed=False, unit=fmt.YI_IN_K),
            "financing_change": fmt.yi(fin_chg, signed=True, unit=fmt.YI_IN_K),
            "short_balance": fmt.lots(short_bal, signed=False, already_lots=True),
            "short_change": fmt.lots(short_chg, signed=True, already_lots=True),
        },
    }


# 外資自營商已經算在「自營商買賣超股數」裡，外資只取不含外資自營商的這一欄。
T86_FOREIGN = "外陸資買賣超股數(不含外資自營商)"
T86_TRUST = "投信買賣超股數"
T86_DEALER = "自營商買賣超股數"


def parse_t86(data: dict, codes: list[str]) -> dict[str, dict]:
    """T86 → {代號: {foreign, trust, dealer}}（單位：股）。清單裡沒出現的代號不放進結果。"""
    f = data["fields"]
    i_code = _col(f, "證券代號")
    i_foreign = _col(f, T86_FOREIGN)
    i_trust, i_dealer = _col(f, T86_TRUST), _col(f, T86_DEALER)
    want = set(codes)
    out: dict[str, dict] = {}
    for row in data.get("data", []):
        code = clean_html(row[i_code])
        if code in want:
            out[code] = {
                "foreign": parse_int(row[i_foreign]),
                "trust": parse_int(row[i_trust]),
                "dealer": parse_int(row[i_dealer]),
            }
    return out


def parse_daily_quotes(data: dict, codes: list[str]) -> dict[str, dict]:
    """MI_INDEX 表 8「每日收盤行情」→ {代號: 收盤價、漲跌符號、漲跌價差（原始字串）、成交股數}。清單裡沒出現的代號不放進結果。"""
    table = _table(data, "每日收盤行情")
    f = table["fields"]
    i_code, i_close, i_sign, i_diff, i_vol = (
        _col(f, "證券代號"), _col(f, "收盤價"), _col(f, "漲跌(+/-)"), _col(f, "漲跌價差"), _col(f, "成交股數")
    )
    want = set(codes)
    out: dict[str, dict] = {}
    for row in table["data"]:
        code = clean_html(row[i_code])
        if code in want:
            out[code] = {
                "close": clean_html(row[i_close]),
                "sign": clean_html(row[i_sign]),
                "diff": clean_html(row[i_diff]),
                "volume": clean_html(row[i_vol]),
            }
    return out


_UNSIGNED_RE = re.compile(r"\d+(\.\d+)?")


def etf_price_fields(raw: dict) -> tuple[dict, str | None]:
    """把每日收盤行情的原始字串變成 JSON 欄位。

    漲跌價差不帶正負號，正負號只看「漲跌(+/-)」欄（+、-、空白 = 平盤、X = 不比價）。
    不是 +、- 或平盤的 0 時，不算漲跌幅，回傳警告。收盤價、成交股數看不懂時丟 SourceError。
    """
    close = parse_decimal(raw["close"])
    shares = parse_int(raw["volume"])
    out = {
        "close": float(close),
        "change": None,
        "change_pct": None,
        "volume_lots": fmt.to_lots(shares),
    }
    display = {"close": raw["close"], "change_pct": None, "volume": fmt.lots(shares, signed=False)}
    warning = None
    sign, text = raw["sign"], raw["diff"]
    diff = None
    if _UNSIGNED_RE.fullmatch(text):
        value = Decimal(text)
        if sign == "+":
            diff = value
        elif sign == "-":
            diff = -value
        elif sign == "" and value == 0:
            diff = Decimal(0)
    if diff is None:
        warning = f"漲跌不是一般格式：漲跌(+/-) {sign!r}、漲跌價差 {text!r}"
    else:
        if diff == 0:
            diff = Decimal(0)  # 避免 -0.0
        pct = fmt.etf_change_pct(close, diff)
        out["change"], out["change_pct"] = float(diff), float(pct)
        display["change_pct"] = fmt.pct(pct)
    out["display"] = display
    return out, warning


_PENDING_CASH = "待公告"


def parse_ex_dividend(data: dict, names: dict[str, str], start: date, end: date) -> tuple[list[dict], list[str]]:
    """TWT48U（rwd）→ 觀察清單（{代號: 名稱}）、start～end（含）之間的除權息預告，以及警告。

    現金股利還沒公告時是 HTML（`<p ...>待公告實際收益分配金額</p>`）或空字串，存 null。
    """
    f = data["fields"]
    i_date, i_code, i_type, i_cash = (
        _col(f, "除權除息日期"), _col(f, "股票代號"), _col(f, "除權息"), _col(f, "現金股利")
    )
    out, warnings = [], []
    for r in data.get("data", []):
        code = clean_html(r[i_code])
        if code not in names:
            continue
        d = roc_to_date(clean_html(r[i_date]))
        if not (start <= d <= end):
            continue
        cash_raw = clean_html(r[i_cash])
        cash = None
        if cash_raw and _PENDING_CASH not in cash_raw:
            try:
                cash = parse_decimal(cash_raw)
            except SourceError:
                warnings.append(f"{code} 的現金股利看不懂，當作尚未公告：{cash_raw!r}")
        out.append({
            "code": code,
            "name": names[code],
            "date": d.isoformat(),
            "type": clean_html(r[i_type]),
            "cash_dividend": float(cash) if cash is not None else None,
            "display": {"cash_dividend": f"{fmt.plain_decimal(cash)} 元" if cash is not None else "尚未公告"},
        })
    out.sort(key=lambda x: (x["date"], x["code"]))
    return out, warnings
