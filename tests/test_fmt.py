from decimal import Decimal

import pytest

from brief import fmt


def test_index():
    assert fmt.index(Decimal("49822.55")) == "49,822.55"
    assert fmt.index(Decimal("90.8")) == "90.80"


@pytest.mark.parametrize(
    "value, expected",
    [("110.51", "+110.51"), ("-25.76", "-25.76"), ("1236.3", "+1,236.30"), ("0", "0.00"), ("-0.004", "0.00")],
)
def test_change(value, expected):
    assert fmt.change(Decimal(value)) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("0.22", "+0.22%"), ("-0.83", "-0.83%"), ("0", "0.00%"), ("0.125", "+0.13%"), ("-0.125", "-0.13%")],
)
def test_pct_half_up(value, expected):
    # 0.125 用銀行家捨入會變 0.12，這裡要 0.13
    assert fmt.pct(Decimal(value)) == expected


def test_yi_real_values_20261006():
    assert fmt.yi(1026204771139, signed=False) == "10,262.0 億"
    assert fmt.yi(-6657341610, signed=True) == "-66.6 億"
    assert fmt.yi(-14264918768, signed=True) == "-142.6 億"
    assert fmt.yi(1721212199, signed=True) == "+17.2 億"
    assert fmt.yi(-19201048179, signed=True) == "-192.0 億"


def test_yi_from_thousands():
    assert fmt.yi(637657044, signed=False, unit=fmt.YI_IN_K) == "6,376.6 億"
    assert fmt.yi(4305323, signed=True, unit=fmt.YI_IN_K) == "+43.1 億"


def test_yi_half_up_and_zero():
    assert fmt.yi(5_000_000, signed=True) == "+0.1 億"  # 0.05 → 0.1
    assert fmt.yi(25_000_000, signed=True) == "+0.3 億"  # 0.25 → 0.3（銀行家捨入會是 0.2）
    assert fmt.yi(-4_000_000, signed=True) == "0.0 億"  # 四捨五入後是 0，不寫「-0.0」
    assert fmt.yi(0, signed=True) == "0.0 億"


def test_lots():
    assert fmt.lots(-15986082, signed=True) == "-15,986 張"
    assert fmt.lots(70945715, signed=False) == "70,946 張"
    assert fmt.lots(214529, signed=False, already_lots=True) == "214,529 張"
    assert fmt.lots(-3929, signed=True, already_lots=True) == "-3,929 張"
    assert fmt.lots(0, signed=True) == "0 張"


def test_lots_half_up():
    assert fmt.lots(70944500, signed=False) == "70,945 張"  # 銀行家捨入會是 70,944
    assert fmt.to_lots(70944500) == 70945
    assert fmt.to_lots(-40000) == -40


def test_count():
    assert fmt.count(462, "家") == "462 家"
    assert fmt.count(1083, "家") == "1,083 家"
    assert fmt.count(0, "家") == "0 家"


def test_etf_change_pct():
    # 0050 在 2026-10-06：收盤 116.50、漲跌價差 +0.55 → 0.55 / 115.95 × 100 = 0.474…
    assert fmt.etf_change_pct(Decimal("116.50"), Decimal("0.55")) == Decimal("0.47")
    assert fmt.pct(fmt.etf_change_pct(Decimal("116.50"), Decimal("0.55"))) == "+0.47%"
    assert fmt.etf_change_pct(Decimal("112.80"), Decimal("-0.10")) == Decimal("-0.09")


def test_plain_decimal():
    assert fmt.plain_decimal(Decimal("0.120000")) == "0.12"
    assert fmt.plain_decimal(Decimal("1.000000")) == "1.00"
    assert fmt.plain_decimal(Decimal("0.0451")) == "0.0451"
