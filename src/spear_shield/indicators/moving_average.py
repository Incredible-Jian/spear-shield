"""移动平均线：SMA / EMA。

统一口径（全文见 docs/indicators/indicator_specification.md）：
- SMA：滚动简单平均，min_periods=window，前 window-1 根为 NaN。
- EMA：alpha = 2/(window+1)；初始值 = 前 window 根简单平均（SMA 种子）；
  之后递归 EMA[i] = EMA[i-1] + alpha * (x[i] - EMA[i-1])；前 window-1 根为 NaN。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import validate_window


def sma(values: pd.Series, window: int) -> pd.Series:
    """简单移动平均。"""
    validate_window(window)
    return values.rolling(window=window, min_periods=window).mean()


def ema(values: pd.Series, window: int) -> pd.Series:
    """指数移动平均（SMA 种子 + 递归）。输入须为无缺失数值序列。"""
    validate_window(window)
    alpha = 2.0 / (window + 1.0)
    vals = np.asarray(values, dtype=float)
    out = np.full(len(vals), np.nan, dtype=float)
    if len(vals) < window:
        return pd.Series(out, index=values.index, name=values.name)
    out[window - 1] = float(np.mean(vals[:window]))
    for i in range(window, len(vals)):
        out[i] = out[i - 1] + alpha * (vals[i] - out[i - 1])
    return pd.Series(out, index=values.index, name=values.name)
