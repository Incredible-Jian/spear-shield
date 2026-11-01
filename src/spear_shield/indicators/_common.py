"""指标模块内部共享工具（非公共 API）。"""
from __future__ import annotations

import numpy as np


def validate_window(window: int) -> None:
    """窗口/周期参数必须为正整数。"""
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        raise ValueError(f"窗口必须为正整数，得到: {window!r}")


def wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder 平滑：首值 = 前 period 期简单均值，其后递归加权。

    返回与输入等长数组，前 period-1 位为 NaN（预热期）。
    递归式：smooth[i] = smooth[i-1] + (values[i] - smooth[i-1]) / period。
    """
    n = len(values)
    out = np.full(n, np.nan, dtype=float)
    if n < period:
        return out
    out[period - 1] = float(np.mean(values[:period]))
    for i in range(period, n):
        out[i] = out[i - 1] + (values[i] - out[i - 1]) / period
    return out
