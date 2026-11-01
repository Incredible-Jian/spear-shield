"""指标引擎集成测试：不改动入参、无未来数据、周期隔离、预热期等。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from spear_shield.data.resample import resample_weekly
from spear_shield.indicators.engine import IndicatorEngine


def _bars(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2020-01-01", periods=n)
    close = 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))
    high = close + np.abs(rng.normal(1.0, 0.3, n))
    low = close - np.abs(rng.normal(1.0, 0.3, n))
    open_ = close - rng.normal(0.0, 0.3, n)
    volume = rng.integers(1000, 10000, n).astype(float)
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def test_compute_returns_original_plus_indicators() -> None:
    res = IndicatorEngine("day").compute(_bars())
    assert set(["open", "high", "low", "close", "volume"]).issubset(res.data.columns)
    assert "ma60" in res.data.columns and "rsi14" in res.data.columns
    assert res.meta["period"] == "day"
    assert res.meta["indicators"]["ma60"]["window"] == 60


def test_does_not_mutate_input() -> None:
    df = _bars(30)
    original = df.copy(deep=True)
    IndicatorEngine("day").compute(df)
    pd.testing.assert_frame_equal(df, original)


def test_no_lookahead() -> None:
    full = IndicatorEngine("day").compute(_bars()).data
    k = 60
    part = IndicatorEngine("day").compute(_bars().iloc[:k]).data
    for col in [c for c in full.columns if c != "date"]:
        pd.testing.assert_series_equal(
            full[col].iloc[:k].reset_index(drop=True),
            part[col].reset_index(drop=True),
            check_dtype=False, check_exact=False, rtol=1e-10, atol=1e-10,
        )


def test_period_isolation_day_vs_week() -> None:
    daily = _bars(200)
    weekly = resample_weekly(daily)
    d_res = IndicatorEngine("day").compute(daily).data
    w_res = IndicatorEngine("week").compute(weekly).data
    # 周期不同 → bar 数量与 MA 值均不同，引擎不会跨周期重采样
    assert len(d_res) != len(w_res)
    assert d_res["ma10"].iloc[-1] != w_res["ma10"].iloc[-1]
    # 相同 bar 上，周期元信息不同不改变计算口径
    w_res2 = IndicatorEngine("day").compute(weekly).data
    pd.testing.assert_frame_equal(w_res, w_res2)


def test_warmup_is_nan_not_fabricated() -> None:
    res = IndicatorEngine("day").compute(_bars(70)).data
    assert np.isnan(res["ma60"].iloc[58]) and not np.isnan(res["ma60"].iloc[59])
    assert np.isnan(res["rsi14"].iloc[13]) and not np.isnan(res["rsi14"].iloc[14])
    # ATR 首根即有 TR，预热期 = period-1（首个有效下标 13）
    assert np.isnan(res["atr14"].iloc[12]) and not np.isnan(res["atr14"].iloc[13])


def test_duplicate_dates_raises() -> None:
    df = _bars(10)
    dup = pd.concat([df, df.iloc[[0]]]).sort_values("date").reset_index(drop=True)
    with pytest.raises(ValueError):
        IndicatorEngine("day").compute(dup)


def test_missing_column_raises() -> None:
    df = _bars(10).drop(columns=["volume"])
    with pytest.raises(ValueError):
        IndicatorEngine("day").compute(df)


def test_invalid_period_raises() -> None:
    with pytest.raises(ValueError):
        IndicatorEngine("hour")
