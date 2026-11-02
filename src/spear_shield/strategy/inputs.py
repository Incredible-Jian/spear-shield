"""已结算周/月行情 -> 策略证据；要求发布时点，不猜测交易日历。"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from ..indicators.engine import IndicatorEngine
from .types import Evidence, Policy, Snapshot, utc_time


def _bars(frame: pd.DataFrame, as_of: datetime, period: str) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume",
                "available_at", "is_final", "adjust", "source"}
    if missing := required - set(frame):
        raise ValueError(f"缺少带发布时间的策略输入字段:{sorted(missing)}")
    df = frame.copy(deep=True)
    dates = pd.to_datetime(df["date"], errors="raise")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("日期须唯一、有效且升序")
    # 日期字段表示交易日标签，不接受带时间/时区的混合标签。
    if dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all():
        raise ValueError("date须为无时区的交易日日期标签")
    df["date"] = dates
    released = []
    for value in df["available_at"]:
        released.append(utc_time(pd.Timestamp(value).to_pydatetime()))
    df["available_at"] = pd.to_datetime(released, utc=True)
    if not df["is_final"].map(lambda v: isinstance(v, (bool, np.bool_))).all():
        raise ValueError("is_final须为布尔值")
    # 先按可知时点截断，再计算；未来的价格/复权值不得影响过去。
    df = df.loc[(df["available_at"] <= utc_time(as_of)) & df["is_final"] &
                (df["date"].dt.date <= as_of.astimezone(ZoneInfo('Asia/Shanghai')).date())].copy().reset_index(drop=True)
    if df.empty:
        return df
    if not df["adjust"].eq("qfq").all() or df["source"].isna().any() or df["source"].eq("").any():
        raise ValueError("须提供前复权价格和来源")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="raise")
        if not np.isfinite(df[col]).all():
            raise ValueError("行情存在非有限数")
    if ((df[["open", "high", "low", "close"]] <= 0).any().any() or
            (df["volume"] < 0).any() or
            (df["high"] < df[["open", "low", "close"]].max(axis=1)).any() or
            (df["low"] > df[["open", "close"]].min(axis=1)).any()):
        raise ValueError("非法OHLC或成交量")
    slots = df["date"].dt.to_period("W-SUN" if period == "week" else "M")
    if slots.duplicated().any():
        raise ValueError("同一周期存在多个bar，不能当作周/月序列")
    # 缺一个整周/月则重置预热，不把不连续bar当作连续周期。
    gaps = slots.astype('int64').diff().fillna(1).ne(1)
    if gaps.any():
        df = df.loc[gaps[gaps].index[-1]:].copy()
    return df.reset_index(drop=True)


def build_snapshot(weekly: pd.DataFrame, monthly: pd.DataFrame, *,
                   as_of: datetime, valid_until: datetime, signal_symbol: str,
                   expected_week_close: date, expected_month_close: date,
                   policy: Policy) -> Snapshot:
    """signal_symbol由负责人确认，不能暗中切换指数/ETF。

    expected_* 为交易日历确定的最近一个应已结算周期，防止把旧周线当本周。
    qfq历史须由调用者提供当时可知的复权版本，接口不能证明供应商历史版本。
    """
    if signal_symbol not in ("399006", "159915") or not policy.approved("signal_series_definition"):
        raise ValueError("策略信号使用指数还是ETF须有负责人确认记录")
    facts = {}
    weekly_ok = False
    for frame, period, expected in ((weekly, "week", expected_week_close),
                                     (monthly, "month", expected_month_close)):
        data = _bars(frame, as_of, period)
        if data.empty or data.iloc[-1]["date"].date() != expected:
            continue
        indicators = IndicatorEngine(period).compute(data).data
        if period == "week":
            sop_time = pd.Timestamp(expected).tz_localize("Asia/Shanghai") + pd.Timedelta(hours=15, minutes=30)
            weekly_ok = pd.Timestamp(as_of) >= sop_time
        latest = indicators.iloc[-1]
        observed = latest["date"].tz_localize("Asia/Shanghai") + pd.Timedelta(hours=15)
        released = max(data["available_at"])
        source = f"{signal_symbol}:" + ",".join(sorted(set(data["source"])))

        def put(key, value):
            if isinstance(value, float) and not np.isfinite(value):
                value = None
            elif isinstance(value, tuple):
                value = tuple(None if isinstance(v, float) and not np.isfinite(v) else v for v in value)
            facts[key] = Evidence(value, source, observed.to_pydatetime(),
                                  released.to_pydatetime(), valid_until)

        put(f"{period}_slope", float(latest["slope_ma60"]))
        put(f"{period}_slopes2", tuple(float(v) for v in indicators["slope_ma60"].tail(2)))
        put(f"{period}_input_history", tuple({
            "date": row["date"].date().isoformat(),
            "available_at": row["available_at"].isoformat(),
            "source": row["source"], "adjust": row["adjust"],
            **{k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}
        } for _, row in data.iterrows()))
        if period == "week":
            for key, col in (("week_close", "close"), ("week_ma60", "ma60"),
                             ("week_ma10", "ma10"), ("week_return_pct", "ret"),
                             ("volume_pct52", "vol_pct52"),
                             ("deviation_ma60_pct", "dev_ma60"), ("week_atr14", "atr14")):
                put(key, float(latest[col]))
    return Snapshot(as_of, facts, weekly_final=weekly_ok)
