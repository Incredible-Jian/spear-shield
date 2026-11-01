"""成交量指标：均量、量比、滚动分位数。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import validate_window
from .moving_average import sma


def volume_ma(volume: pd.Series, window: int = 5) -> pd.Series:
    """成交量简单移动平均。"""
    return sma(volume, window)


def volume_ratio(volume: pd.Series, window: int = 5) -> pd.Series:
    """量比 = 成交量 / N 期均量。"""
    validate_window(window)
    return volume / sma(volume, window)


def volume_percentile(volume: pd.Series, window: int = 52) -> pd.Series:
    """滚动分位数（0~100）。

    口径：
    - 统计窗口 = 过去 window 根（含当前根，当前值参与统计）
    - 算法 = 经验累积分布：窗口内「成交量 ≤ 当前值」的根数 / window × 100
    - 100 表示当前为窗口内最大；「位列过去 52 周前 40%」等价于分位 ≥ 60
    - 预热期 window 根，此前为 NaN
    """
    validate_window(window)

    def _rank(w: np.ndarray) -> float:
        return float((w <= w[-1]).sum()) / len(w) * 100.0

    return volume.rolling(window=window, min_periods=window).apply(_rank, raw=True)
