"""RSI（Wilder 平滑法）。

口径：
- delta = close.diff()
- 涨幅 gain = max(delta, 0)，跌幅 loss = max(-delta, 0)
- avg_gain / avg_loss 采用 Wilder 平滑（首值为前 period 期简单均值）
- RS = avg_gain / avg_loss；RSI = 100 - 100/(1+RS)
- 零波动（gain=loss=0）记 50；仅涨（loss=0）记 100；仅跌（gain=0）记 0
- 前 period 根为 NaN（需 period 个涨跌幅，第 period+1 根起有效）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import validate_window, wilder_smooth


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """相对强弱指标。"""
    validate_window(period)
    delta = close.diff().iloc[1:]
    gain = delta.clip(lower=0.0).to_numpy(dtype=float)
    loss = (-delta.clip(upper=0.0)).to_numpy(dtype=float)

    out = pd.Series(np.nan, index=close.index, dtype=float, name=f"rsi{period}")
    if len(gain) < period:
        return out

    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)

    rsi_vals = np.full(len(avg_gain), np.nan, dtype=float)
    for i in range(len(avg_gain)):
        g, l = avg_gain[i], avg_loss[i]
        if np.isnan(g) or np.isnan(l):
            continue
        if l == 0.0:
            rsi_vals[i] = 100.0 if g > 0.0 else 50.0
        else:
            rsi_vals[i] = 100.0 - 100.0 / (1.0 + g / l)

    # avg_gain[i] 对应 close 下标 i+1（delta 前导一行）
    out.iloc[1:] = rsi_vals
    return out
