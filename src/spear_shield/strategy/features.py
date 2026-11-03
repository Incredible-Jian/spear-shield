"""带日历的因果特征构造；回溯缓存研究不伪装为历史实际发布时间。"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from ..indicators.engine import IndicatorEngine
from ..indicators.macro import historical_percentile
from .types import Evidence, Snapshot, Policy

SH = ZoneInfo("Asia/Shanghai")


def settled_bars(daily, calendar, as_of, period):
    """只聚合日历已结束的周/月；长假无交易周不伪造K线。"""
    if period not in ("week", "month"):
        raise ValueError("仅周/月")
    now = pd.Timestamp(as_of).tz_convert("Asia/Shanghai")
    frequency = "W-SUN" if period == "week" else "M"
    sessions = pd.DatetimeIndex(calendar.sessions)
    slots = sessions.to_period(frequency)
    last_days = pd.Series(sessions, index=slots).groupby(level=0).max()
    settled = last_days.loc[
        (last_days + pd.Timedelta(hours=15, minutes=30)) <= now.tz_localize(None)
    ]
    df = daily.copy(deep=True)
    df["date"] = pd.to_datetime(df.date)
    df = df.loc[
        (df.date.dt.date <= now.date()) & (df.date >= sessions.min())
    ].sort_values("date")
    if df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    # 每个实际有交易的周期均须全覆盖；不足的周期留NaN以重置warm-up。
    rows = []
    groups = dict(tuple(df.groupby(df.date.dt.to_period(frequency), sort=True)))
    for slot, last_day in settled.items():
        if last_day < df.date.min():
            continue
        group = groups.get(slot, df.iloc[:0])
        expected = set(sessions[slots == slot].date)
        if expected != set(group.date.dt.date):
            rows.append(
                {
                    "date": settled.loc[slot],
                    **{k: np.nan for k in ("open", "high", "low", "close", "volume")},
                }
            )
            continue
        rows.append(
            {
                "date": settled.loc[slot],
                "open": float(group.iloc[0].open),
                "high": float(group.high.max()),
                "low": float(group.low.min()),
                "close": float(group.iloc[-1].close),
                "volume": float(group.volume.sum()),
            }
        )
    return pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "volume"]
    )


def complete_segment_indicators(bars, period):
    """缺失周期保留NaN；递推指标在下一完整段重新预热，不永久污染后续。"""
    if bars.empty:
        return IndicatorEngine(period).compute(bars).data
    valid = bars[["open", "high", "low", "close", "volume"]].notna().all(axis=1)
    segments = valid.ne(valid.shift(fill_value=False)).cumsum()
    output = []
    for _, block in bars.groupby(segments, sort=False):
        computed = IndicatorEngine(period).compute(block).data
        if not valid.loc[block.index].all():
            computed.loc[:, computed.columns.difference(["date"])] = np.nan
        output.append(computed)
    return pd.concat(output).sort_index()


def _finite(value):
    return (
        value is not None
        and isinstance(value, (int, float, np.number))
        and np.isfinite(value)
    )


def _last(values):
    return float(values.iloc[-1]) if len(values) and _finite(values.iloc[-1]) else None


def _known_series(frame, as_of, *, name):
    """额外宏观须显式提供可用时间；缺发布时间不替其推测。"""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "value", "available_at", "source"])
    if not {"date", "value", "available_at", "source"} <= set(frame):
        raise ValueError(f"{name}宏观输入缺少date/value/available_at/source")
    df = frame.copy(deep=True)
    if any(pd.Timestamp(t).tzinfo is None for t in df.available_at):
        raise ValueError("宏观发布时间须带时区")
    df["available_at"] = pd.to_datetime(df.available_at, utc=True)
    df["date"] = pd.to_datetime(df.date)
    if df.date.duplicated().any() or df.date.isna().any():
        raise ValueError("宏观日期重复或无效")
    df = df.loc[
        (df.available_at <= pd.Timestamp(as_of))
        & (df.date.dt.date <= as_of.astimezone(SH).date())
    ]
    return df.sort_values("date").reset_index(drop=True)


def candle_features(weekly, policy):
    if weekly.empty:
        return {}
    x = weekly.iloc[-1]
    if not all(_finite(x[k]) for k in ("open", "high", "low", "close", "ma60")):
        return {}
    c, o, h, l, ma = (float(x[k]) for k in ("close", "open", "high", "low", "ma60"))
    values = {
        "effective_above_ma60": c > ma,
        "bullish_week": c > o,
        "retest_ma60": l <= ma * 1.03 and c >= ma,
        "two_weeks_above_ma60": bool(
            len(weekly) >= 2
            and weekly.tail(2).ma60.notna().all()
            and (weekly.tail(2).close > weekly.tail(2).ma60).all()
        ),
        "long_upper_shadow": h > l
        and (h - max(o, c)) / (h - l) > policy.parameters["upper_shadow_fraction"],
    }
    baseline = (
        weekly.volume.shift(1)
        .rolling(
            policy.parameters["volume_baseline_weeks"],
            min_periods=policy.parameters["volume_baseline_weeks"],
        )
        .mean()
        .iloc[-1]
    )
    if _finite(baseline) and baseline > 0 and _finite(x.ret):
        vr = float(x.volume / baseline)
        stalled = abs(float(x.ret)) < policy.parameters["stall_return_abs_pct"]
        values.update(
            volume_1_5=vr >= 1.5,
            low_volume_stall=vr < policy.parameters["low_volume_ratio"] and stalled,
            high_volume_stall=vr >= policy.parameters["high_volume_ratio"] and stalled,
        )
    if len(weekly) >= 2 and weekly.tail(2).ma60.notna().all():
        # 前周满足突破/量/趋势但未收阳，当前为连续站稳的第二周。
        prev = weekly.iloc[-2]
        values["missed_first_nonbullish"] = bool(
            prev.close > prev.ma60
            and prev.close <= prev.open
            and _finite(prev.vol_pct52)
            and prev.vol_pct52 >= 60
        )
    return values


def double_top_features(weekly):
    """首顶需右侧2根确认；第二顶为当前候选，无未来确认。颈线保存已形成候选。"""
    if len(weekly) < 9 or not weekly.tail(9).close.notna().all():
        return {}
    data = weekly.tail(52).reset_index(drop=True)
    pivots = [
        i
        for i in range(2, len(data) - 2)
        if data.high.iloc[i] == data.high.iloc[i - 2 : i + 3].max()
        and data.high.iloc[i] > data.high.iloc[i - 1]
        and data.high.iloc[i] > data.high.iloc[i + 1]
    ]
    second = False
    neckline = None
    for first in pivots:
        h1 = data.high.iloc[first]
        for j in range(first + 3, len(data)):
            valley = data.low.iloc[first + 1 : j].min()
            near = abs(data.high.iloc[j] / h1 - 1) <= 0.03
            recovery = data.high.iloc[j] > data.high.iloc[j - 1]
            if near and recovery and valley <= h1 * 0.95:
                neckline = float(valley)
                if j == len(data) - 1:
                    second = True
    return {
        "second_top": second,
        "below_neckline": bool(neckline is not None and data.close.iloc[-1] < neckline),
    }


def build_operational_snapshot(
    growth_daily,
    dividend_daily,
    calendar,
    *,
    as_of: datetime,
    policy: Policy,
    context=None,
    macros=None,
    historical_time_assumption=False,
    prepared=None,
):
    """context由成交账本提供，宏观未提供则缺失；不将未知风险设为False。"""
    context, macros = context or {}, macros or {}
    if as_of.tzinfo is None:
        raise ValueError("as_of须带时区")
    if prepared is None:
        weekly = settled_bars(growth_daily, calendar, as_of, "week")
        monthly = settled_bars(growth_daily, calendar, as_of, "month")
    else:
        weekly = (
            prepared["week"]
            .loc[prepared["week"].date.dt.date <= as_of.astimezone(SH).date()]
            .copy()
        )
        monthly = (
            prepared["month"]
            .loc[prepared["month"].date.dt.date <= as_of.astimezone(SH).date()]
            .copy()
        )
    facts = {}

    def put(
        key,
        value,
        source="原文跟踪指数399006/公开历史缓存",
        observed=None,
        available=None,
    ):
        if isinstance(value, (float, np.floating)) and not np.isfinite(value):
            return
        if isinstance(value, np.bool_):
            value = bool(value)
        if value is not None:
            facts[key] = Evidence(
                value, source, observed or as_of, available or as_of, as_of
            )

    put(
        "history_time_assumption",
        historical_time_assumption,
        "抓取时点与历史经济时点严格区分",
    )
    weekly_final = False
    for bars, prefix, expected_period in (
        (weekly, "week", "W-SUN"),
        (monthly, "month", "M"),
    ):
        if bars.empty:
            continue
        computed = (
            complete_segment_indicators(bars, prefix) if "ma60" not in bars else bars
        )
        if prefix == "week":
            weekly = computed
            weekly_final = (
                pd.Timestamp(as_of.astimezone(SH).date()) == computed.iloc[-1].date
            )
        else:
            monthly = computed
        x = computed.iloc[-1]
        put(f"{prefix}_slope", float(x.slope_ma60))
        slopes = tuple(
            float(v) if _finite(v) else None for v in computed.slope_ma60.tail(2)
        )
        put(f"{prefix}_slopes2", slopes)
        put(
            f"{prefix}_input_history",
            tuple(
                {
                    "date": r.date.isoformat(),
                    **{
                        k: float(r[k]) if _finite(r[k]) else None
                        for k in ("open", "high", "low", "close", "volume")
                    },
                }
                for _, r in bars.iterrows()
            ),
        )
    if len(weekly):
        x = weekly.iloc[-1]
        for key, col in (
            ("week_close", "close"),
            ("week_ma60", "ma60"),
            ("week_ma10", "ma10"),
            ("week_return_pct", "ret"),
            ("volume_pct52", "vol_pct52"),
            ("deviation_ma60_pct", "dev_ma60"),
            ("rsi", "rsi14"),
        ):
            put(key, float(x[col]))
        if _finite(x.slope_ma60):
            put("week_direction_up", bool(x.slope_ma60 > 0))
        for key, value in {
            **candle_features(weekly, policy),
            **double_top_features(weekly),
        }.items():
            put(key, value, "授权操作定义/仅使用已结算周线")
        if not monthly.empty:
            month_direction = pd.merge_asof(
                weekly[["date", "high"]],
                monthly[["date", "slope_ma60"]],
                on="date",
                direction="backward",
            )
            previous = month_direction.iloc[:-1]
            # 最近连续熊市段；只使用其已发生的高点，不预判最终反弹顶。
            indices = np.flatnonzero(previous.slope_ma60.le(0).to_numpy())
            if len(indices):
                last = indices[-1]
                start = last
                while start > 0 and previous.slope_ma60.iloc[start - 1] <= 0:
                    start -= 1
                rally = previous.high.iloc[start : last + 1].max()
                put("break_bear_rally_high", bool(x.close > rally))
            put(
                "volume_breakout",
                bool(x.vol_pct52 >= 60) if _finite(x.vol_pct52) else None,
            )
        put("bear_entry_allowed", True, "授权熊市20%例外")
        put("fast_entry_allowed", True, "授权快速通道负月线封顶20%")
        put(
            "restore_allowed",
            bool(_finite(x.ma10) and x.close >= x.ma10),
            "授权次周收回>=MA10，仍受风险滤网约束",
        )
    if len(dividend_daily):
        defense = (
            settled_bars(dividend_daily, calendar, as_of, "week")
            if prepared is None
            else prepared["defense_week"].loc[
                prepared["defense_week"].date.dt.date <= as_of.astimezone(SH).date()
            ]
        )
        pairs = weekly[["date", "close"]].merge(
            defense[["date", "close"]],
            on="date",
            how="left",
            suffixes=("_growth", "_dividend"),
        )
        r = pairs.close_growth / pairs.close_dividend
        history = r.shift(1)
        z = (r - history.rolling(156, min_periods=156).mean()) / history.rolling(
            156, min_periods=156
        ).std(ddof=0).replace(0, np.nan)
        put("zscore", _last(z), "399006/H30269；156个已完成交易周，不含当前，ddof0")
        if len(pairs) >= 3 and pairs.tail(3).notna().all().all():
            dr = pairs.close_dividend.pct_change(fill_method=None)
            gr = pairs.close_growth.pct_change(fill_method=None)
            put(
                "defense_fuse",
                bool(((dr < gr) & (dr < 0) & (gr < 0)).tail(2).all()),
                "两指数连续两周均跌且红利跌得更多",
            )
    # 精确的宏观发布时间由接入方保留；本函数不生成假发布时间。
    known = {
        key: _known_series(frame, as_of, name=key) for key, frame in macros.items()
    }
    for key, frame in known.items():
        if frame.empty:
            continue
        latest = frame.iloc[-1]
        # 指标最近观测须不早于7天；周末仍可以使用周五/周四已发布值。
        if (as_of.astimezone(SH).date() - latest.date.date()).days > 7:
            continue
        value = float(latest.value)
        put(
            key,
            value,
            str(latest.source),
            observed=datetime.combine(latest.date.date(), time(0), SH),
            available=latest.available_at.to_pydatetime(),
        )
        if key in ("iv_short", "iv_long", "pe"):
            window = policy.parameters[
                {
                    "iv_short": "iv_short_window",
                    "iv_long": "iv_long_window",
                    "pe": "pe_window",
                }[key]
            ]
            percentiles = historical_percentile(
                frame.value, window=window, include_current=False
            )
            put(
                {
                    "iv_short": "iv_short_pct",
                    "iv_long": "iv_long_pct",
                    "pe": "pe_percentile",
                }[key],
                _last(percentiles),
                str(latest.source),
            )
        if key == "margin_pct":
            put(
                "margin_cleared",
                (
                    value <= policy.parameters["margin_clear_pct"]
                    if _finite(value)
                    else None
                ),
                str(latest.source),
            )
        if key == "margin_turnover_pct":
            put(
                "margin_turnover_valid",
                True if _finite(value) else None,
                str(latest.source),
            )
    if len(weekly) and "margin_pct" in known and len(known["margin_pct"]):
        margin = known["margin_pct"]
        left = weekly[["date", "close"]].copy()
        left["known_by"] = (
            left.date.dt.tz_localize("Asia/Shanghai")
            + pd.Timedelta(hours=15, minutes=30)
        ).dt.tz_convert("UTC")
        aligned = pd.merge_asof(
            left.sort_values("known_by"),
            margin[["available_at", "value"]].sort_values("available_at"),
            left_on="known_by",
            right_on="available_at",
            direction="backward",
            tolerance=pd.Timedelta(days=7),
        )
        n = policy.parameters["divergence_window"]
        if len(aligned) >= n + 1 and aligned.tail(n + 1).notna().all().all():
            put(
                "top_divergence",
                bool(
                    aligned.close.iloc[-1] >= aligned.close.iloc[-n - 1 : -1].max()
                    and aligned.value.iloc[-1] < aligned.value.iloc[-n - 1 : -1].max()
                ),
            )
    for key, value in context.items():
        put(key, value, "实际模拟成交账本/因果持仓状态")
    return Snapshot(as_of, facts, weekly_final=weekly_final), weekly, monthly
