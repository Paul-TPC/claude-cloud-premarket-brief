"""民國日期轉換、交易日判斷。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone

# 台灣沒有日光節約時間，用固定 +08:00，不依賴系統時區資料。
TAIPEI = timezone(timedelta(hours=8), "Asia/Taipei")

_ROC_COMPACT = re.compile(r"^(\d{2,3})(\d{2})(\d{2})$")
_ROC_SLASH = re.compile(r"^(\d{2,3})/(\d{1,2})/(\d{1,2})$")
_ROC_CJK = re.compile(r"^(\d{2,3})年(\d{1,2})月(\d{1,2})日$")


def roc_to_date(text: str) -> date:
    """`1151005`、`115/10/06`、`115年10月06日` → 西元日期。"""
    s = text.strip()
    for pattern in (_ROC_COMPACT, _ROC_SLASH, _ROC_CJK):
        m = pattern.match(s)
        if m:
            y, mo, d = (int(g) for g in m.groups())
            return date(y + 1911, mo, d)
    raise ValueError(f"看不懂的民國日期：{text!r}")


def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# 開休市清單裡，哪些說明代表「這天有交易」、哪些代表「這天沒有交易」。
# 先看有交易的關鍵字（例如「最後交易日」「開始交易」），再看休市的。
_OPEN_WORDS = ("最後交易日", "開始交易", "開始買賣", "照常交易")
_CLOSED_WORDS = ("無交易", "放假", "休市", "停止交易", "補假", "調整放假")


@dataclass
class HolidayCalendar:
    closed: set[date] = field(default_factory=set)
    source: str = "weekend_only"  # "twse" 或 "weekend_only"
    unknown: list[str] = field(default_factory=list)  # 判斷不了的列（原文）

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.closed

    def previous_trading_day(self, d: date) -> date:
        d -= timedelta(days=1)
        for _ in range(60):
            if self.is_trading_day(d):
                return d
            d -= timedelta(days=1)
        raise ValueError("往前 60 天都找不到交易日")


def classify_holiday_row(name: str, description: str) -> bool | None:
    """True = 休市，False = 有交易（說明列），None = 判斷不了。"""
    text = f"{name} {description}"
    if any(w in text for w in _OPEN_WORDS):
        return False
    if any(w in text for w in _CLOSED_WORDS):
        return True
    return None


def parse_holiday_schedule(rows: list[tuple[date, str, str]]) -> HolidayCalendar:
    """(日期, 名稱, 說明) 的清單 → 開休市日曆。"""
    cal = HolidayCalendar(source="twse")
    for d, name, description in rows:
        verdict = classify_holiday_row(name, description)
        if verdict is True:
            cal.closed.add(d)
        elif verdict is None:
            # 判斷不了：當作休市（清單本來就是休市日清單），並回報出去。
            cal.closed.add(d)
            cal.unknown.append(f"{d.isoformat()} {name}：{description}")
    return cal
