"""SMA / EMA 手工计算验证。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from spear_shield.indicators.moving_average import ema, sma


def test_sma_hand_calc() -> None:
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = sma(s, 3)
    assert out.iloc[0] != out.iloc[0] or np.isnan(out.iloc[0])
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0
    assert out.iloc[3] == 3.0
    assert out.iloc[4] == 4.0


def test_sma_insufficient_length_is_nan() -> None:
    out = sma(pd.Series([1.0, 2.0]), 3)
    assert out.isna().all()


def test_ema_hand_calc() -> None:
    # window=2, alpha=2/3；seed = mean(10,20)=15
    s = pd.Series([10.0, 20.0, 30.0])
    out = ema(s, 2)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx(15.0)
    assert out.iloc[2] == pytest.approx(25.0)  # 15 + (2/3)*(30-15)


def test_ema_hand_calc_nonlinear() -> None:
    # window=3, alpha=0.5；seed = mean(1,2,4)=7/3
    s = pd.Series([1.0, 2.0, 4.0, 8.0, 16.0])
    out = ema(s, 3)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(7.0 / 3.0)
    # 7/3 + 0.5*(8 - 7/3) = 31/6
    assert out.iloc[3] == pytest.approx(31.0 / 6.0)
    # 31/6 + 0.5*(16 - 31/6) = 127/12
    assert out.iloc[4] == pytest.approx(127.0 / 12.0)


def test_ema_insufficient_length_is_nan() -> None:
    assert ema(pd.Series([1.0]), 3).isna().all()


def test_nan_input_does_not_crash() -> None:
    s = pd.Series([1.0, 2.0, np.nan, 4.0])
    out = sma(s, 2)
    assert np.isnan(out.iloc[2])  # 含 NaN 的窗口结果为 NaN
    assert not np.isnan(out.iloc[1])


def test_invalid_window_raises() -> None:
    with pytest.raises(ValueError):
        sma(pd.Series([1.0]), 0)
    with pytest.raises(ValueError):
        ema(pd.Series([1.0]), -1)
