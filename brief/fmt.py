"""`display` 字串的格式（SPEC 第 6 節）。四捨五入一律用 ROUND_HALF_UP。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

YI = Decimal(100_000_000)  # 1 億元
YI_IN_K = Decimal(100_000)  # 1 億元 = 100,000 仟元
LOT = Decimal(1000)  # 1 張 = 1,000 股


def _q(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _signed(text: str, value: Decimal) -> str:
    # 正負號看四捨五入後的值：0 不加號，避免「-0.0」。
    if value > 0:
        return "+" + text
    if value < 0:
        return "-" + text
    return text


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    return _q(Decimal(value), places)


def index(value: Decimal) -> str:
    """指數：千分位、兩位小數。`49,822.55`"""
    return f"{_q(Decimal(value), 2):,.2f}"


def change(value: Decimal, places: int = 2) -> str:
    """漲跌點數：帶正負號、兩位小數。`+110.51`"""
    v = _q(Decimal(value), places)
    return _signed(f"{abs(v):,.{places}f}", v)


def pct(value: Decimal) -> str:
    """百分比：帶正負號、兩位小數加 %。`+0.22%`"""
    v = _q(Decimal(value), 2)
    return _signed(f"{abs(v):.2f}%", v)


def yi(twd: int | Decimal, *, signed: bool, unit: Decimal = YI) -> str:
    """金額換成億元、一位小數。`-66.6 億`、`10,262.0 億`。unit 用 YI_IN_K 表示輸入是仟元。"""
    v = _q(Decimal(twd) / unit, 1)
    text = f"{abs(v):,.1f} 億"
    if not signed:
        return f"{v:,.1f} 億"
    return _signed(text, v)


def lots(shares: int | Decimal, *, signed: bool, already_lots: bool = False) -> str:
    """張數：股數除以 1,000（already_lots 表示本來就是張）、千分位。`-15,986 張`"""
    v = Decimal(shares) if already_lots else Decimal(shares) / LOT
    v = _q(v, 0)
    if not signed:
        return f"{v:,.0f} 張"
    return _signed(f"{abs(v):,.0f} 張", v)


def count(n: int, unit: str) -> str:
    """家數這類整數：千分位加單位。`1,234 家`"""
    return f"{n:,} {unit}"


def to_lots(shares: int | Decimal) -> int:
    return int(_q(Decimal(shares) / LOT, 0))


def etf_change_pct(close: Decimal, diff: Decimal) -> Decimal:
    """ETF 漲跌幅：漲跌價差 ÷ 前一日收盤（收盤 − 漲跌價差）× 100，四捨五入到兩位。"""
    prev = close - diff
    return _q(diff / prev * 100, 2)


def plain_decimal(value: Decimal, min_places: int = 2) -> str:
    """去掉多餘的尾數 0，但至少留 min_places 位小數。`0.120000` → `0.12`"""
    v = Decimal(value).normalize()
    places = max(-v.as_tuple().exponent, min_places) if v != 0 else min_places
    return f"{Decimal(value):,.{places}f}"
