"""价格指标：涨跌幅、偏离率、振幅、斜率。

本模块所有「率 / 幅 / 偏离 / 斜率」均返回百分比数值（1.0 = 1%），
与策略文档阈值（0.1%、3%、8% 等）直接对应。
"""
from __future__ import annotations

import pandas as pd

from .moving_average import sma


def pct_change(close: pd.Series, periods: int = 1) -> pd.Series:
    """周期涨跌幅 = (收盘 - 前 periods 收盘) / 前收盘 × 100。"""
    return close.pct_change(periods=periods, fill_method=None) * 100.0


def deviation_pct(close: pd.Series, window: int) -> pd.Series:
    """价格相对均线偏离率 = (收盘 - MA(window)) / MA(window) × 100。"""
    ma = sma(close, window)
    return (close - ma) / ma * 100.0


def amplitude_pct(
    high: pd.Series, low: pd.Series, close: pd.Series, periods: int = 1
) -> pd.Series:
    """周期振幅 = (最高 - 最低) / 前 periods 周期收盘 × 100。

    用于周线/月线振幅（periods=1 即「上周/上月收盘」为基准，
    与原策略 P1 横盘口径「(最高-最低)/上周收盘」一致）。
    """
    prev = close.shift(periods)
    return (high - low) / prev * 100.0


def slope(series: pd.Series, periods: int = 1) -> pd.Series:
    """序列斜率 = (当前 - 前 periods 值) / 前值 × 100（百分比）。

    用于 60 月/周线斜率、连续均线斜率等。
    """
    return series.pct_change(periods=periods, fill_method=None) * 100.0
