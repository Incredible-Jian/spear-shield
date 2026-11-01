"""周线/月线聚合测试。"""
from __future__ import annotations

import pandas as pd

from spear_shield.data.resample import resample_monthly, resample_weekly


def _daily() -> pd.DataFrame:
    # 2024-01-01 为周一，共 10 个自然日（跨两个周）
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.DataFrame({
        "date": dates,
        "open": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        "high": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0],
        "low": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5],
        "close": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5],
        "volume": [100.0] * 10,
        "amount": [1000.0] * 10,
    })


def test_weekly_aggregation() -> None:
    w = resample_weekly(_daily())
    assert len(w) == 2  # 01-01~01-07 与 01-08~01-10
    first, second = w.iloc[0], w.iloc[1]
    # 周内 open=首日、close=末日、high=max、low=min、volume/amount=累加
    assert first["open"] == 1.0
    assert first["close"] == 7.5
    assert first["high"] == 8.0
    assert first["low"] == 0.5
    assert first["volume"] == 700.0
    assert first["amount"] == 7000.0
    assert second["open"] == 8.0
    assert second["close"] == 10.5
    assert second["volume"] == 300.0


def test_monthly_aggregation() -> None:
    m = resample_monthly(_daily())
    assert len(m) == 1  # 全部落在 2024-01
    row = m.iloc[0]
    assert row["open"] == 1.0
    assert row["close"] == 10.5
    assert row["high"] == 11.0
    assert row["low"] == 0.5
    assert row["volume"] == 1000.0


def test_empty_returns_empty() -> None:
    empty = _daily().iloc[0:0]
    assert resample_weekly(empty).empty
    assert resample_monthly(empty).empty
