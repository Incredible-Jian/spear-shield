"""只读行情展示模型：缓存、价格口径和完成性显式区分，不产生策略信号。"""

from datetime import datetime, time
from zoneinfo import ZoneInfo
import math

import pandas as pd

from ..data.quality import validate_daily

SH = ZoneInfo("Asia/Shanghai")


def quote_view(symbol, raw, adjusted, *, now=None):
    now = now or datetime.now(SH)
    now = now.astimezone(SH)
    # 优先同日期原始价；只有前复权更新时，明确展示其研究单位口径。
    choices = [(raw, "原始行情"), (adjusted, "前复权研究价")]
    choices = [(df, label) for df, label in choices if not df.empty]
    base = {
        "code": symbol.code,
        "name": symbol.name,
        "price": None,
        "change_pct": None,
        "date": "—",
        "updated": "—",
        "source": "未接入",
        "basis": "—",
        "completion": "UNKNOWN / 数据缺失",
        "quality": "UNKNOWN",
        "issues": [],
    }
    if not choices:
        return base
    df, basis = max(
        choices,
        key=lambda item: (pd.Timestamp(item[0].iloc[-1].date), item[1] == "原始行情"),
    )
    row = df.iloc[-1]
    basis = "指数点位" if symbol.asset_type == "index" else basis
    day = pd.Timestamp(row.date).date()
    updated = pd.to_datetime(row.get("updated_at"), utc=True, errors="coerce")
    issues = validate_daily(df)
    if not df.date.is_monotonic_increasing:
        issues.append("日期乱序")
    if (
        not df[["open", "high", "low", "close", "volume"]]
        .apply(
            lambda col: col.map(
                lambda v: isinstance(v, (int, float)) and math.isfinite(v)
            )
        )
        .all()
        .all()
    ):
        issues.append("非有限数值")
    if (df.volume < 0).any():
        issues.append("负成交量")
    if not str(row.get("source", "")).strip():
        issues.append("来源缺失")
    if pd.isna(updated):
        issues.append("写入时间缺失")
    if day > now.date():
        issues.append("行情日期在未来")
    if not pd.isna(updated) and updated.to_pydatetime() > now:
        issues.append("写入时间在未来")
    settled_after = datetime.combine(day, time(15, 30), SH)
    completed = (
        not pd.isna(updated)
        and updated.to_pydatetime() >= settled_after
        and now >= settled_after
    )
    completion = "收盘后缓存 / 非实时" if completed else "未完成日线 / 待收盘后更新"
    if day < now.date():
        completion += " / 历史数据"
    price = float(row.close) if not issues else None
    change = None
    if price is not None and len(df) >= 2 and float(df.iloc[-2].close) > 0:
        change = (price / float(df.iloc[-2].close) - 1) * 100
    return {
        **base,
        "price": price,
        "change_pct": change,
        "date": day.isoformat(),
        "updated": (
            updated.tz_convert(SH).strftime("%Y-%m-%d %H:%M:%S %Z")
            if not pd.isna(updated)
            else "—"
        ),
        "source": str(row.get("source", "")),
        "basis": basis,
        "completion": completion,
        "quality": "FALSE / 数据异常" if issues else "TRUE / 样本校验通过",
        "issues": issues,
        "complete": bool(completed and not issues),
    }


def chart_period_note(bars, period, *, now=None):
    if bars.empty:
        return "UNKNOWN / 无行情"
    now = (now or datetime.now(SH)).astimezone(SH)
    if period == "day":
        return "日线末根收盘完成性见行情时间；盘中值仅供观察"
    freq = "W-SUN" if period == "week" else "M"
    end = pd.Timestamp(bars.iloc[-1].date).to_period(freq).end_time.date()
    if end >= now.date():
        return "UNKNOWN / 末根周月线尚未确认，观察聚合不可用于交易裁决"
    return "历史周月聚合，仅供观察；交易日缺失/正式结算完整性需策略日历另行核验"
