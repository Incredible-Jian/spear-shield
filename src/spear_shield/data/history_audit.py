"""公司行动、时点复权重建和跨源核对；核对一致不等于历史发布证明。"""

from datetime import date
import re
import numpy as np
import pandas as pd

from ..backtest.models import CorporateAction


def cash_dividends(symbol, frame, *, source):
    required = {"除息日", "分红发放日", "每10份分红"}
    if not required <= set(frame):
        raise ValueError("分红表字段不完整")
    output = []
    for _, row in frame.iterrows():
        text = str(row["每10份分红"])
        match = re.fullmatch(r"每10份派现金([0-9]+(?:\.[0-9]+)?)元", text)
        if not match:
            raise ValueError(f"不支持的分红单位:{text}")
        output.append(
            CorporateAction(
                symbol,
                pd.Timestamp(row["除息日"]).date(),
                pd.Timestamp(row["分红发放日"]).date(),
                float(match[1]) / 10,
                1.0,
                source,
            )
        )
    if len({x.ex_date for x in output}) != len(output):
        raise ValueError("重复分红日期")
    return tuple(sorted(output, key=lambda a: a.ex_date))


def qfq_asof(raw, actions, *, as_of: date, method="cash_additive"):
    """按截止日已生效的公司行动，将原始OHLC归一到截止日价格单位。

    只支持现金分红和份额拆分，无配股/特殊收益再投资。未来公司行动不参与。
    原始数据历史修订、事件完整性、公告时点由调用方另行审计。
    """
    if method not in ("cash_additive", "ratio"):
        raise ValueError("复权方法须明确为cash_additive或ratio")
    df = raw.copy(deep=True)
    if "adjust" not in df or not df.adjust.eq("none").all():
        raise ValueError("时点复权重建必须输入原始行情")
    df["date"] = pd.to_datetime(df.date)
    if df.date.duplicated().any():
        raise ValueError("重复原始行情日期")
    df = df.loc[df.date.dt.date <= as_of].sort_values("date").reset_index(drop=True)
    factors = np.ones(len(df))
    offsets = np.zeros(len(df))
    seen = set()
    for event in sorted(actions, key=lambda a: a.ex_date):
        if event.ex_date > as_of:
            continue
        if event.ex_date in seen:
            raise ValueError("重复公司行动")
        seen.add(event.ex_date)
        before = df.date.dt.date < event.ex_date
        if not before.any():
            continue
        previous = float(df.loc[before, "close"].iloc[-1])
        multiplier = (previous - event.cash_per_unit) / (previous * event.split_ratio)
        if not np.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("非法公司行动复权因子")
        if method == "ratio":
            factors[before.to_numpy()] *= multiplier
        else:
            factors[before.to_numpy()] /= event.split_ratio
            offsets[before.to_numpy()] = (
                offsets[before.to_numpy()] - event.cash_per_unit
            ) / event.split_ratio
    for column in ("open", "high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="raise") * factors + offsets
        if (df[column] <= 0).any():
            raise ValueError("复权后价格非正，拒绝隐藏长历史现金调整异常")
    df["adjustment_split_factor_asof"] = factors
    df["adjustment_cash_offset_asof"] = offsets
    df["adjustment_method"] = method
    df["adjust"] = "qfq"
    df["adjustment_as_of"] = as_of.isoformat()
    return df


def compare_prices(left, right, *, tolerance_abs=0.001, end=None):
    a, b = left[["date", "close"]].copy(), right[["date", "close"]].copy()
    for frame in (a, b):
        frame["date"] = pd.to_datetime(frame.date)
        if frame.date.duplicated().any():
            raise ValueError("比较序列存在重复日期")
    if end is not None:
        a, b = (frame.loc[frame.date.dt.date <= end] for frame in (a, b))
    merged = a.merge(
        b, on="date", how="outer", suffixes=("_left", "_right"), indicator=True
    )
    both = merged.loc[merged._merge.eq("both")]
    error = (both.close_left - both.close_right).abs()
    return {
        "common_dates": len(both),
        "left_only": int(merged._merge.eq("left_only").sum()),
        "right_only": int(merged._merge.eq("right_only").sum()),
        "tolerance_abs": tolerance_abs,
        "mismatch_count": int((error > tolerance_abs).sum()),
        "max_absolute_error": float(error.max()) if len(error) else None,
        "max_error_basis_points": (
            float((error / both.close_right.abs() * 10000).max())
            if len(error)
            else None
        ),
        "meaning": "仅核对重合日期价格一致性，不证明两源独立、无修订或历史实际可知",
    }
