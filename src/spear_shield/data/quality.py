"""数据质量检查。

返回问题列表，绝不静默填充或丢弃。发现致命问题时上层应标记「数据不可用」。
"""
from __future__ import annotations

import pandas as pd

_REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}


def validate_daily(df: pd.DataFrame) -> list[str]:
    """校验标准化日线数据，返回问题描述列表（空列表表示通过）。"""
    problems: list[str] = []

    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        problems.append(f"缺少必需列: {sorted(missing)}")
        return problems

    if df.empty:
        problems.append("数据为空")
        return problems

    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        problems.append("date 列不是日期时间类型")

    if df["date"].duplicated().any():
        problems.append("存在重复日期")

    if df[["open", "high", "low", "close"]].isna().any().any():
        problems.append("OHLC 存在空值")

    if (df["close"] <= 0).any():
        problems.append("存在非正收盘价")

    if (df["high"] < df["low"]).any():
        problems.append("存在最高价 < 最低价")

    if (df["high"] < df[["open", "close"]].max(axis=1)).any():
        problems.append("存在最高价低于开盘/收盘")

    if (df["low"] > df[["open", "close"]].min(axis=1)).any():
        problems.append("存在最低价高于开盘/收盘")

    return problems


def validate_margin(df: pd.DataFrame) -> list[str]:
    """校验两融日频数据。"""
    problems: list[str] = []
    if df.empty:
        problems.append("两融数据为空")
        return problems
    if "date" not in df.columns:
        problems.append("两融数据缺少 date 列")
    if df["date"].duplicated().any():
        problems.append("两融数据存在重复日期")
    return problems
