"""技术指标计算模块。

仅提供指标计算，不包含任何策略规则、买卖信号或交易判断。
所有「率 / 幅 / 偏离 / 斜率」指标返回百分比数值（1.0 = 1%）。
"""
from __future__ import annotations

from .atr import atr
from .bollinger import bollinger
from .engine import IndicatorEngine, IndicatorResult
from .macd import macd
from .moving_average import ema, sma
from .price import amplitude_pct, deviation_pct, pct_change, slope
from .rsi import rsi
from .volume import volume_ma, volume_percentile, volume_ratio

__all__ = [
    "IndicatorEngine",
    "IndicatorResult",
    "sma",
    "ema",
    "macd",
    "rsi",
    "bollinger",
    "atr",
    "volume_ma",
    "volume_ratio",
    "volume_percentile",
    "pct_change",
    "deviation_pct",
    "amplitude_pct",
    "slope",
]
