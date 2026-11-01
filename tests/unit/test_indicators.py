"""MACD / RSI / 布林带 / ATR / 成交量 / 价格指标的手工数值验证。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from spear_shield.indicators.atr import atr
from spear_shield.indicators.bollinger import bollinger
from spear_shield.indicators.macd import macd
from spear_shield.indicators.price import (
    amplitude_pct,
    deviation_pct,
    pct_change,
    slope,
)
from spear_shield.indicators.rsi import rsi
from spear_shield.indicators.volume import volume_ma, volume_percentile, volume_ratio


# ---- MACD ----

def test_macd_hand_calc() -> None:
    # fast=2, slow=3, signal=2，close 线性 [1..6]
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    dif, dea, hist = macd(close, fast=2, slow=3, signal=2)
    # DIF 有效起点为 slow 预热期 idx2，线性序列下恒为 0.5
    assert np.isnan(dif.iloc[0]) and np.isnan(dif.iloc[1])
    assert dif.iloc[2] == pytest.approx(0.5)
    assert dif.iloc[5] == pytest.approx(0.5)
    # DEA = EMA(dif,2)，有效起点 idx3
    assert np.isnan(dea.iloc[0:3]).all()
    assert dea.iloc[3] == pytest.approx(0.5)
    # MACD 柱 = 2*(dif-dea)，有效起点 idx3 后为 0
    assert np.isnan(hist.iloc[0:3]).all()
    assert hist.iloc[3] == pytest.approx(0.0)


def test_macd_default_warmup_lengths() -> None:
    close = pd.Series(np.linspace(100, 120, 40))
    dif, dea, hist = macd(close)  # 12/26/9
    assert dif.first_valid_index() == 25  # slow=26 预热期 25 根
    assert dea.first_valid_index() == 33  # 25 + (signal-1)
    assert hist.first_valid_index() == 33


# ---- RSI ----

def test_rsi_rising() -> None:
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    out = rsi(close, period=3)
    assert np.isnan(out.iloc[0:3]).all()  # 预热期 3 根
    assert out.iloc[3] == pytest.approx(100.0)
    assert out.iloc[6] == pytest.approx(100.0)


def test_rsi_falling() -> None:
    close = pd.Series([7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    out = rsi(close, period=3)
    assert out.iloc[3] == pytest.approx(0.0)
    assert out.iloc[6] == pytest.approx(0.0)


def test_rsi_flat() -> None:
    close = pd.Series([5.0, 5.0, 5.0, 5.0, 5.0])
    out = rsi(close, period=3)
    assert np.isnan(out.iloc[0:3]).all()
    assert out.iloc[3] == pytest.approx(50.0)
    assert out.iloc[4] == pytest.approx(50.0)


def test_rsi_insufficient_length_is_nan() -> None:
    assert rsi(pd.Series([1.0, 2.0]), period=14).isna().all()


# ---- 布林带 ----

def test_bollinger_hand_calc() -> None:
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    mid, up, low, width = bollinger(close, period=3, num_std=2.0, ddof=0)
    std = np.sqrt(2.0 / 3.0)  # 总体标准差 [1,2,3]
    assert np.isnan(mid.iloc[0:2]).all()
    assert mid.iloc[2] == pytest.approx(2.0)
    assert up.iloc[2] == pytest.approx(2.0 + 2.0 * std)
    assert low.iloc[2] == pytest.approx(2.0 - 2.0 * std)
    assert width.iloc[2] == pytest.approx(4.0 * std / 2.0)


# ---- ATR ----

def test_atr_hand_calc() -> None:
    high = pd.Series([5.0, 6.0, 7.0, 8.0])
    low = pd.Series([4.0, 5.0, 6.0, 7.0])
    close = pd.Series([4.5, 5.5, 6.5, 7.5])
    out = atr(high, low, close, period=3)
    # TR = [1, 1.5, 1.5, 1.5]
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx((1.0 + 1.5 + 1.5) / 3.0)  # 种子
    # 1.3333 + (1.5 - 1.3333)/3
    assert out.iloc[3] == pytest.approx((1.0 + 1.5 + 1.5) / 3.0 + (1.5 - 4.0 / 3.0) / 3.0)


def test_atr_first_tr_is_high_minus_low() -> None:
    out = atr(pd.Series([10.0]), pd.Series([8.0]), pd.Series([9.0]), period=1)
    assert out.iloc[0] == pytest.approx(2.0)


# ---- 成交量 ----

def test_volume_ma() -> None:
    v = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    out = volume_ma(v, 3)
    assert np.isnan(out.iloc[0:2]).all()
    assert out.iloc[2] == pytest.approx(20.0)
    assert out.iloc[4] == pytest.approx(40.0)


def test_volume_ratio() -> None:
    v = pd.Series([10.0, 20.0, 30.0])
    out = volume_ratio(v, 3)
    assert out.iloc[2] == pytest.approx(30.0 / 20.0)


def test_volume_percentile_boundaries() -> None:
    v = pd.Series([10.0, 30.0, 20.0, 40.0, 10.0])
    out = volume_percentile(v, 3)
    assert np.isnan(out.iloc[0:2]).all()
    # [10,30,20] 当前 20，≤20 的有 2 根 → 66.67
    assert out.iloc[2] == pytest.approx(2 / 3 * 100)
    # [30,20,40] 当前 40 → 100
    assert out.iloc[3] == pytest.approx(100.0)
    # [20,40,10] 当前 10 → 33.33
    assert out.iloc[4] == pytest.approx(1 / 3 * 100)


# ---- 价格指标 ----

def test_pct_change() -> None:
    out = pct_change(pd.Series([100.0, 110.0, 121.0]), 1)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx(10.0)
    assert out.iloc[2] == pytest.approx(10.0)


def test_deviation_pct() -> None:
    close = pd.Series([10.0, 20.0, 30.0, 40.0])
    out = deviation_pct(close, 3)
    assert out.iloc[2] == pytest.approx(50.0)  # (30-20)/20
    assert out.iloc[3] == pytest.approx((40.0 - 30.0) / 30.0 * 100.0)


def test_amplitude_pct() -> None:
    high = pd.Series([12.0, 13.0, 14.0])
    low = pd.Series([10.0, 11.0, 12.0])
    close = pd.Series([11.0, 12.0, 13.0])
    out = amplitude_pct(high, low, close, 1)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx((13.0 - 11.0) / 11.0 * 100.0)
    assert out.iloc[2] == pytest.approx((14.0 - 12.0) / 12.0 * 100.0)


def test_slope() -> None:
    out = slope(pd.Series([2.0, 4.0, 6.0]), 1)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx(100.0)
    assert out.iloc[2] == pytest.approx(50.0)
