"""日线 → 周线 / 月线聚合。

口径：以交易日历实际最后交易日结算（节假日顺延），
open=首日开盘，high=周期最高，low=周期最低，close=末日收盘，volume/amount=累加。
"""
from __future__ import annotations

import pandas as pd


def _aggregate(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """按 period 聚合标准化日线 DataFrame。period: 'W' 或 'M'。"""
    if df.empty:
        return df.copy()
    d = df.sort_values("date").copy()
    if "date" not in d.columns:
        raise ValueError("日线数据缺少 date 列")

    key = d["date"].dt.to_period(period)
    agg: dict[str, tuple] = {
        "date": ("date", "last"),
        "open": ("open", "first"),
        "high": ("high", "max"),
        "low": ("low", "min"),
        "close": ("close", "last"),
        "volume": ("volume", "sum"),
    }
    if "amount" in d.columns:
        agg["amount"] = ("amount", "sum")

    out = d.groupby(key, as_index=False).agg(**agg)
    out = out.sort_values("date").reset_index(drop=True)
    return out


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """日线 → 周线。"""
    return _aggregate(df, "W")


def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """日线 → 月线。"""
    return _aggregate(df, "M")
