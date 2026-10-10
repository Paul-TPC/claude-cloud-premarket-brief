from datetime import date

import pytest

from brief import parse
from brief.dates import (
    HolidayCalendar,
    classify_holiday_row,
    parse_holiday_schedule,
    previous_weekday,
    roc_to_date,
)
from conftest import fixture_bytes


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1151009", date(2026, 10, 9)),
        ("1151005", date(2026, 10, 5)),
        ("115/10/06", date(2026, 10, 6)),
        ("115年10月06日", date(2026, 10, 6)),
        (" 115/1/2 ", date(2026, 1, 2)),
        ("991231", date(2010, 12, 31)),
    ],
)
def test_roc_to_date(text, expected):
    assert roc_to_date(text) == expected


@pytest.mark.parametrize("text", ["2026-10-06", "", "115-10-06", "1151332"])
def test_roc_to_date_rejects(text):
    with pytest.raises(ValueError):
        roc_to_date(text)


def test_previous_weekday():
    assert previous_weekday(date(2026, 10, 7)) == date(2026, 10, 6)
    assert previous_weekday(date(2026, 10, 5)) == date(2026, 10, 2)


@pytest.fixture
def cal():
    return parse.parse_holiday(parse.load_twse(fixture_bytes("twse_holiday.json")))


def test_calendar_from_real_list(cal):
    assert cal.source == "twse"
    assert cal.unknown == []
    assert date(2026, 10, 9) in cal.closed  # 國慶日補假
    assert date(2026, 2, 12) in cal.closed  # 市場無交易，僅辦理結算交割作業
    assert date(2026, 2, 11) not in cal.closed  # 農曆春節前最後交易日（說明列）
    assert date(2026, 1, 2) not in cal.closed  # 國曆新年開始交易日（說明列）
    assert date(2026, 10, 26) in cal.closed  # 光復節補假（週一）


def test_normal_weekday(cal):
    assert cal.is_trading_day(date(2026, 10, 7))
    assert cal.previous_trading_day(date(2026, 10, 7)) == date(2026, 10, 6)


def test_monday_uses_friday(cal):
    assert cal.previous_trading_day(date(2026, 10, 5)) == date(2026, 10, 2)


def test_national_day_makeup_holiday(cal):
    assert not cal.is_trading_day(date(2026, 10, 9))
    assert cal.previous_trading_day(date(2026, 10, 9)) == date(2026, 10, 8)


def test_monday_after_long_weekend(cal):
    assert cal.is_trading_day(date(2026, 10, 12))
    assert cal.previous_trading_day(date(2026, 10, 12)) == date(2026, 10, 8)


def test_weekend_only_when_list_missing():
    cal = HolidayCalendar()
    assert cal.source == "weekend_only"
    assert cal.is_trading_day(date(2026, 10, 9))  # 只看週末，不知道補假
    assert cal.previous_trading_day(date(2026, 10, 12)) == date(2026, 10, 9)
    assert not cal.is_trading_day(date(2026, 10, 10))


@pytest.mark.parametrize(
    "name, description, expected",
    [
        ("農曆春節前最後交易日", "農曆春節前最後交易。\r\n", False),
        ("國曆新年開始交易日", "國曆新年開始交易。", False),
        ("市場無交易，僅辦理結算交割作業", "", True),
        ("國慶日", "國慶日為10月10日適逢星期六，於10月9日（星期五）補假。", True),
        ("勞動節", "依規定放假1日。", True),
        ("某個新名目", "另行公告", None),
    ],
)
def test_classify_holiday_row(name, description, expected):
    assert classify_holiday_row(name, description) is expected


def test_unknown_row_is_closed_and_reported():
    cal = parse_holiday_schedule([(date(2026, 10, 21), "某個新名目", "另行公告")])
    assert date(2026, 10, 21) in cal.closed
    assert len(cal.unknown) == 1 and "2026-10-21" in cal.unknown[0]
