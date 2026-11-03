"""授权操作口径测试：合成数据仅供测试，不用于真实验收。"""

from dataclasses import replace
from datetime import datetime, date, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from spear_shield.backtest.models import TradingCalendar
from spear_shield.strategy.features import settled_bars, build_operational_snapshot
from spear_shield.strategy.operational import operational_policy
from spear_shield.strategy.defense import defense_plan
from spear_shield.strategy.rules import entry_rules
from spear_shield.strategy import Position, StrategyEngine

SH = ZoneInfo("Asia/Shanghai")


def data(start="2010-01-04", periods=4500):
    dates = pd.bdate_range(start, periods=periods)
    c = np.linspace(100.0, 200.0, len(dates)) + np.sin(np.arange(len(dates)) / 30)
    return pd.DataFrame(
        {
            "date": dates,
            "open": c - 0.1,
            "high": c + 1,
            "low": c - 1,
            "close": c,
            "volume": 1000.0,
            "source": "synthetic-test-only",
        }
    )


def calendar(frame):
    return TradingCalendar(tuple(frame.date.dt.date), "test-calendar", True)


def instant(day):
    return datetime.combine(day, time(15, 30), SH)


def test_unfinished_week_and_month_not_final():
    frame = data(periods=90)
    cal = calendar(frame)
    wednesday = frame.loc[frame.date.dt.weekday.eq(2)].iloc[4].date.date()
    result = settled_bars(frame, cal, instant(wednesday), "week")
    assert result.iloc[-1].date.date() < wednesday
    month = settled_bars(frame, cal, instant(wednesday), "month")
    assert month.empty or month.iloc[-1].date.month < wednesday.month


def test_holiday_thursday_is_final_only_when_calendar_says_so():
    frame = data(periods=20)
    frame = frame.loc[frame.date.ne(pd.Timestamp("2010-01-08"))]
    cal = calendar(frame)
    result = settled_bars(frame, cal, instant(date(2010, 1, 7)), "week")
    assert result.iloc[-1].date.date() == date(2010, 1, 7)


def test_missing_daily_bar_does_not_disappear_into_valid_week():
    frame = data(periods=30)
    cal = calendar(frame)
    missing = frame.loc[frame.date.ne(pd.Timestamp("2010-01-05"))]
    result = settled_bars(missing, cal, instant(date(2010, 1, 15)), "week")
    assert pd.isna(result.iloc[0].close)


def test_entire_missing_trading_week_is_preserved_and_indicator_rewarms():
    from spear_shield.strategy.features import complete_segment_indicators

    frame = data(periods=200)
    cal = calendar(frame)
    removed = frame.loc[~frame.date.between("2010-01-11", "2010-01-15")]
    bars = settled_bars(removed, cal, instant(frame.iloc[-1].date.date()), "week")
    assert len(bars) == 40 and bars.close.isna().sum() == 1
    computed = complete_segment_indicators(bars, "week")
    assert pd.isna(computed.atr14.iloc[2])
    assert np.isfinite(computed.atr14.iloc[-1])


def test_future_prices_do_not_change_current_snapshot():
    frame = data()
    cal = calendar(frame)
    day = frame.loc[frame.date.dt.weekday.eq(4)].iloc[400].date.date()
    modified = frame.copy()
    modified.loc[modified.date.dt.date > day, ["open", "high", "low", "close"]] *= 10
    a, _, _ = build_operational_snapshot(
        frame, frame, cal, as_of=instant(day), policy=operational_policy()
    )
    b, _, _ = build_operational_snapshot(
        modified, frame, cal, as_of=instant(day), policy=operational_policy()
    )
    for key in (
        "week_slope",
        "month_slope",
        "week_close",
        "volume_pct52",
        "rsi",
        "zscore",
    ):
        assert a.get(key) == b.get(key)


def test_macro_future_publication_not_seen_and_iv_is_not_return_volatility():
    frame = data(periods=500)
    cal = calendar(frame)
    day = frame.loc[frame.date.dt.weekday.eq(4)].iloc[-2].date.date()
    macro = pd.DataFrame(
        {
            "date": [str(day)],
            "value": [2.1],
            "source": ["test-margin"],
            "available_at": [instant(day) + pd.Timedelta(days=1)],
        }
    )
    s, _, _ = build_operational_snapshot(
        frame,
        frame,
        cal,
        as_of=instant(day),
        policy=operational_policy(),
        macros={"margin_pct": macro},
    )
    assert s.get("margin_pct") is None
    assert s.get("iv_short_pct") is None and s.get("iv_long_pct") is None


def test_delegated_policy_does_not_approve_equity_bond_scale():
    p = operational_policy()
    assert p.approved("effective_break_definition")
    assert p.approved("same_priority_definition")
    assert not p.approved("equity_bond_definition")
    assert not p.approved("equity_bond_extreme")


def test_defense_fuse_allocates_to_short_bond_only_under_delegated_policy(snapshot):
    s = snapshot(zscore=0, defense_fuse=True)
    plan = defense_plan(s, operational_policy(), active=True)
    assert plan["weights"] == pytest.approx(
        {"563020": 0.3, "511360": 0.6, "511990": 0.1}
    )
    assert plan["unallocated"] == 0 and plan["executable"]


def test_bear_fast_cap_is_20_not_50(snapshot):
    s = snapshot(
        month_slope=-1,
        week_slopes2=(0.1, 0.1),
        week_return_pct=8,
        volume_pct52=70,
        pe_percentile=40,
        fast_entry_allowed=True,
        margin_pct=2,
        risk_budget_pass=True,
        stop_distance_pct=1.0,
        execution_cost_buffer_pct=1.16,
    )
    rule = next(
        r
        for r in entry_rules(s, Position(), operational_policy())
        if r.rule_id == "ENTRY_FAST"
    )
    assert rule.action.fraction == 0.2


def test_delegated_same_priority_is_single_largest_action(snapshot):
    s = snapshot(
        week_slopes2=(-1, -1),
        month_slopes2=(1, 1),
        week_close=1,
        week_ma60=2,
        eligible_lot_weight=0.5,
        profit_pct=40,
        week_ma10=3,
    )
    d = StrategyEngine(operational_policy()).evaluate(s, Position(0.5))
    assert d.selected.rule_id == "P0_TREND"
