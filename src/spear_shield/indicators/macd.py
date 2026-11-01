"""MACD：DIF / DEA / MACD 柱。

口径（中国软件通用）：
- DIF = EMA(close, fast) - EMA(close, slow)
- DEA = EMA(DIF, signal)（对 DIF 的有效段计算）
- MACD 柱 = 2 * (DIF - DEA)
- EMA 采用本模块统一口径（SMA 种子 + alpha=2/(N+1)，见 moving_average.ema）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .moving_average import ema


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (DIF, DEA, MACD 柱)。"""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    dif = ema_fast - ema_slow

    # DEA 只在 DIF 有效段上计算，避免前导 NaN 破坏 EMA 种子
    dea = pd.Series(np.nan, index=close.index, dtype=float)
    valid = dif.dropna()
    if len(valid) >= signal:
        dea_valid = ema(valid, signal)
        dea.loc[dea_valid.index] = dea_valid

    hist = 2.0 * (dif - dea)
    return dif, dea, hist
