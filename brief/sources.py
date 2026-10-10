"""SPEC 第 5 節的資料來源網址。"""

from __future__ import annotations

from datetime import date

TWSE_HOLIDAY = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json"
TWSE_EX_DIVIDEND = "https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json"
NEWS_YAHOO = "https://tw.stock.yahoo.com/rss?category=tw-market"
NEWS_UDN = "https://money.udn.com/rssfeed/news/1001/5590?ch=money"
NEWS_CNYES = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=100"
TELEGRAM_ROOT = "https://api.telegram.org"
# v2 articles：Yahoo 新聞的另一種網址（tw.stock.yahoo.com 已經在 NEWS_YAHOO 測到）
YAHOO_NEWS_ROOT = "https://tw.news.yahoo.com/"

# T86 的 selectType：照 SPEC 用 ALL（約 2 萬列）。縮小範圍的 0099P 在雲端被擋，沒辦法確認，見 docs/PITFALLS.md。
T86_SELECT_TYPE = "ALL"


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def twse_index(d: date) -> str:
    """加權指數、類股指數、成交金額、漲跌家數、觀察清單 ETF 的價格都在這一個回應裡。"""
    return f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={_ymd(d)}&type=ALLBUT0999&response=json"


def twse_institutional(d: date) -> str:
    return f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate={_ymd(d)}&response=json"


def twse_margin(d: date) -> str:
    return f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={_ymd(d)}&selectType=MS&response=json"


def twse_etf_institutional(d: date, select_type: str = T86_SELECT_TYPE) -> str:
    return f"https://www.twse.com.tw/rwd/zh/fund/T86?date={_ymd(d)}&selectType={select_type}&response=json"
