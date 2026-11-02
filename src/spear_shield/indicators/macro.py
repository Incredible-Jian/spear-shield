"""纯数值宏观工具。未确认的窗口、ddof、数据口径均不设策略默认值。"""
from __future__ import annotations

from abc import ABC, abstractmethod
import numpy as np
import pandas as pd

from ._common import validate_window


def _validate(values: pd.Series) -> pd.Series:
    if values.index.has_duplicates or not values.index.is_monotonic_increasing:
        raise ValueError("宏观序列索引必须唯一且升序")
    out = pd.to_numeric(values, errors="raise").astype(float)
    return out.where(np.isfinite(out))


def ratio(numerator: pd.Series, denominator: pd.Series, *, percent: bool = False) -> pd.Series:
    """同时间索引精确对齐，分母非正返回 NaN，不填补缺口。"""
    a, b = _validate(numerator), _validate(denominator)
    if not a.index.equals(b.index):
        raise ValueError("比率输入须有完全相同的日期索引与已统一的单位")
    return a / b.where(b > 0) * (100.0 if percent else 1.0)


def style_zscore(growth: pd.Series, dividend: pd.Series, *,
                 ddof: int, include_current: bool) -> pd.Series:
    """156 周比值的 Z；ddof 和窗口是否含本周须显式指定。"""
    if ddof not in (0, 1) or not isinstance(include_current, bool):
        raise ValueError("须明确 ddof=0/1 及 include_current")
    if isinstance(growth.index, pd.DatetimeIndex):
        weeks = growth.index.tz_localize(None).to_period("W-SUN")
        if weeks.has_duplicates or (len(weeks) > 1 and not np.all(np.diff(weeks.asi8) == 1)):
            raise ValueError("Z须为连续周序列，缺失整周请显式补为NaN，不能压缩周期")
    r = ratio(growth, dividend)
    history = r if include_current else r.shift(1)
    mean = history.rolling(156, min_periods=156).mean()
    std = history.rolling(156, min_periods=156).std(ddof=ddof)
    return (r - mean) / std.where(std > 0)


def historical_percentile(values: pd.Series, *, window: int,
                          include_current: bool) -> pd.Series:
    """经验分布 count(x<=当前)/N*100，窗口不满或含缺失则 NaN。"""
    validate_window(window)
    if not isinstance(include_current, bool):
        raise ValueError("须明确是否包含当前值")
    s = _validate(values)
    if include_current:
        return s.rolling(window, min_periods=window).apply(
            lambda x: np.count_nonzero(x <= x[-1]) / window * 100, raw=True)
    # N+1 窗口：前 N 个为历史，最后一个仅作查询，不参与分母。
    return s.rolling(window + 1, min_periods=window + 1).apply(
        lambda x: np.count_nonzero(x[:-1] <= x[-1]) / window * 100, raw=True)


class IVProvider(ABC):
    """独立 IV 提供接口；本阶段无付费实现，不估算官方 IV。"""

    @abstractmethod
    def history(self, underlying: str, start: str, end: str) -> pd.Series:
        """返回带日期索引的 IV 序列，来源/发布时点由接入层记录。"""
