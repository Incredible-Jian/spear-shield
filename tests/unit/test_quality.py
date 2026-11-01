"""数据质量检查测试。"""
from __future__ import annotations

import pandas as pd

from spear_shield.data.quality import validate_daily, validate_margin


def _good_daily() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "open": [10.0, 11.0],
        "high": [12.0, 13.0],
        "low": [9.0, 10.0],
        "close": [11.0, 12.0],
        "volume": [100.0, 200.0],
        "amount": [1000.0, 2000.0],
    })


def test_good_daily_passes() -> None:
    assert validate_daily(_good_daily()) == []


def test_missing_column() -> None:
    df = _good_daily().drop(columns=["close"])
    assert any("close" in p for p in validate_daily(df))


def test_empty_data() -> None:
    assert validate_daily(_good_daily().iloc[0:0]) == ["数据为空"]


def test_duplicate_dates() -> None:
    df = pd.concat([_good_daily(), _good_daily()])
    assert any("重复日期" in p for p in validate_daily(df))


def test_high_below_low() -> None:
    df = _good_daily()
    df.loc[0, "high"] = 5.0  # < low(9.0)
    assert any("最高价 < 最低价" in p for p in validate_daily(df))


def test_nonpositive_close() -> None:
    df = _good_daily()
    df.loc[1, "close"] = 0.0
    assert any("非正收盘价" in p for p in validate_daily(df))


def test_margin_validation() -> None:
    good = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02"]),
        "margin_balance": [1.0],
        "securities_balance": [2.0],
        "margin_buy": [3.0],
        "securities_sell": [4.0],
    })
    assert validate_margin(good) == []
    assert validate_margin(good.iloc[0:0]) == ["两融数据为空"]
    dup = pd.concat([good, good])
    assert any("重复日期" in p for p in validate_margin(dup))
