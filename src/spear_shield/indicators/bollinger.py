"""布林带：中轨 / 上轨 / 下轨 / 带宽。

口径：
- 中轨 = SMA(close, period)
- 标准差 = 总体标准差 ddof=0（与通达信 / 同花顺 BOLL 一致）
- 上轨 = 中轨 + num_std * std；下轨 = 中轨 - num_std * std
- 带宽 = (上轨 - 下轨) / 中轨
"""
from __future__ import annotations

import pandas as pd

from .moving_average import sma


def bollinger(
    close: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
    ddof: int = 0,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """返回 (中轨, 上轨, 下轨, 带宽)。"""
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=ddof)
    upper = mid + num_std * std
    lower = mid - num_std * std
    bandwidth = (upper - lower) / mid
    return mid, upper, lower, bandwidth
