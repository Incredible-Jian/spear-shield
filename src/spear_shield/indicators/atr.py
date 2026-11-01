"""ATR（True Range + Wilder 平滑）。

口径：
- TR[0] = high - low
- TR[i] = max(high-low, |high - prev_close|, |low - prev_close|)
- ATR = Wilder 平滑(TR, period)，首值为前 period 期简单均值
- 前 period-1 根为 NaN（首根即有 TR，第 period 根起有效）

重要：本函数与周期无关——传入周线数据即得周线 ATR，传入日线即日线 ATR；
严禁将日线 ATR 数值当作周线 ATR 使用（原策略的「14 周 ATR」必须在周线上计算）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import validate_window, wilder_smooth


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """平均真实波幅。"""
    validate_window(period)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)  # 首根前收为 NaN，max(skipna) 退化为 high-low

    vals = wilder_smooth(tr.to_numpy(dtype=float), period)
    return pd.Series(vals, index=close.index, name=f"atr{period}")
