"""Phase6回放回归：全部为内存合成数据，不代表真实行情或策略验收。"""

from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from spear_shield.backtest.models import Target, TradingCalendar
from spear_shield.backtest.strategy_replay import StrategyReplay
from spear_shield.strategy.features import build_operational_snapshot
from spear_shield.strategy.operational import operational_policy
from spear_shield.strategy.rules import entry_rules
from spear_shield.strategy.types import (
    Action,
    Decision,
    Evidence,
    Policy,
    Position,
    RuleResult,
    Snapshot,
    Status,
)


SH = ZoneInfo("Asia/Shanghai")


def instant(day):
    return datetime.combine(pd.Timestamp(day).date(), time(15, 30), SH)


def snapshot(day, **overrides):
    values = dict(
        week_slopes2=(1.0, 1.0),
        month_slopes2=(1.0, 1.0),
        month_slope=1.0,
        week_close=100.0,
        week_ma60=90.0,
        week_ma10=90.0,
        eligible_lot_weight=0.0,
        post_entry_four_weeks=False,
        max_week_drop_price=0.0,
        week_atr14=1.0,
        zscore=0.0,
        long_upper_shadow=False,
        low_volume_stall=False,
        margin_pct=1.0,
        top_divergence=False,
        margin_turnover_pct=0.0,
        profit_pct=0.0,
        rise_from_bottom_100=False,
        six_of_eight_above_ma30=False,
        week_return_pct=0.0,
        volume_1_5=False,
        rsi=20.0,
        pe_percentile=10.0,
        peg=1.0,
        second_top=False,
        below_neckline=False,
        peak_profit_pct=0.0,
        drawdown_8=False,
        high_volume_stall=False,
        bullish_week=False,
        retest_ma60=False,
        deviation_ma60_pct=0.0,
        effective_above_ma60=False,
        volume_pct52=70.0,
        break_bear_rally_high=False,
        volume_breakout=False,
        missed_first_nonbullish=False,
        two_weeks_above_ma60=False,
        stop_distance_pct=1.0,
        execution_cost_buffer_pct=1.16,
        bear_entry_allowed=True,
        fast_entry_allowed=False,
        restore_allowed=False,
    )
    values.update(overrides)
    now = instant(day)
    return Snapshot(
        now,
        {
            key: Evidence(value, "synthetic-regression-only", now, now, now)
            for key, value in values.items()
        },
        weekly_final=True,
    )


@pytest.fixture
def replay():
    dates = pd.bdate_range("2024-01-01", periods=400)
    daily = pd.DataFrame(
        dict(
            date=dates,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1000.0,
            source="synthetic-regression-only",
            adjust="qfq",
        )
    )
    calendar = TradingCalendar(tuple(dates.date), "synthetic-regression-only", True)
    dataset = SimpleNamespace(
        growth=daily,
        dividend=daily.copy(),
        calendar=calendar,
        macros={},
        provenance={},
        limitations=["synthetic-regression-only"],
    )
    result = StrategyReplay(dataset, {"159915": daily})
    weeks = pd.date_range("2024-01-05", periods=12, freq="W-FRI")
    result.etf_weeks = pd.DataFrame(
        dict(
            date=weeks,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1000.0,
            atr14=1.0,
            ma60=90.0,
        )
    )
    return result


def row(quantity=80.0, price=100.0, equity=10000.0):
    return dict(
        weight_159915=quantity * price / equity, equity=equity, quantity_159915=quantity
    )


def decision(position, day, rule_id, action, priority=4):
    rule = RuleResult(rule_id, priority, Status.TRIGGERED, (), action, "synthetic")
    return Decision("actionable", rule, (rule,), "synthetic", position, instant(day))


def fill(side, quantity, price=100.0, reason="synthetic"):
    return dict(
        symbol="159915", side=side, quantity=quantity, price=price, reason=reason
    )


def receipt(
    day,
    *,
    target=None,
    trades=(),
    target_trades=None,
    quantity=0.0,
    cost=0.0,
    completed=True,
    status="completed_with_cash_and_lot_constraints"
):
    return dict(
        type="target",
        date=pd.Timestamp(day).date(),
        target=target,
        trades=list(trades),
        target_trades=list(trades if target_trades is None else target_trades),
        quantities={"159915": quantity},
        costs={"159915": cost},
        completed=completed,
        status=status,
    )


def test_risk_latches_after_fill_rearms_only_on_known_false(replay):
    replay.position = Position(0.8, stages=(1,), entry_mode="normal")
    values = dict(
        zscore=3.0, long_upper_shadow=True, retest_ma60=True, bullish_week=True
    )
    replay.snapshot_factory = lambda s, p: snapshot(s.as_of, **values)
    first = replay.close(instant("2024-01-05"), {}, row())
    assert first is not None and first.reason.endswith("P2_STYLE")
    assert "P2_STYLE" not in replay.risk_latched
    replay.execution(
        receipt(
            "2024-01-08",
            target=first,
            trades=[fill("sell", 40.0)],
            quantity=40.0,
            cost=4000.0,
        )
    )
    assert "P2_STYLE" in replay.risk_latched
    assert replay.close(instant("2024-01-12"), {}, row(40.0)) is None
    assert replay.audit[-1]["rule_status"]["P2_STYLE"] == Status.TRIGGERED.value
    assert replay.audit[-1]["rule_status"]["ENTRY_SECOND"] == Status.TRIGGERED.value
    assert replay.position.attack_weight == pytest.approx(0.4)
    values["zscore"] = None
    replay.close(instant("2024-01-19"), {}, row(40.0))
    assert "P2_STYLE" in replay.risk_latched
    values.update(zscore=0.0, retest_ma60=False)
    replay.close(instant("2024-01-26"), {}, row(40.0))
    assert "P2_STYLE" not in replay.risk_latched
    values["zscore"] = 3.0
    again = replay.close(instant("2024-02-02"), {}, row(40.0))
    assert again is not None and again.weights["159915"] == pytest.approx(0.2)
    # The attack leg can sell while another suspended leg keeps the whole
    # target pending. Superseding it must not forget the risk sale already made.
    sold = fill("sell", 10.0)
    replay.execution(
        receipt(
            "2024-02-05",
            target=again,
            trades=[sold],
            quantity=30.0,
            cost=3000.0,
            completed=False,
            status="pending",
        )
    )
    replay.execution(
        receipt(
            "2024-02-06",
            target=again,
            target_trades=[sold],
            quantity=30.0,
            cost=3000.0,
            status="superseded",
        )
    )
    duplicate = replay.close(instant("2024-02-09"), {}, row(30.0))
    assert (
        duplicate is None
    ), "A risk sale already filled must survive cancellation; do not halve the remaining 30% again"


def test_partial_fill_waits_for_completed_cumulative_receipt(replay):
    planned = decision(
        Position(), "2024-01-05", "ENTRY_FIRST", Action("entry", 0.5, stages=(1,))
    )
    target = Target(planned.as_of, {"159915": 0.5}, "partial-entry", planned.as_of)
    replay.pending[target.reason] = planned
    first = fill("buy", 1.0)
    replay.execution(
        receipt(
            "2024-01-08",
            target=target,
            trades=[first],
            quantity=1.0,
            cost=100.0,
            completed=False,
            status="pending",
        )
    )
    assert replay.position.stages == () and replay.entry_day is None
    assert target.reason not in replay.receipted
    rest = fill("buy", 49.0)
    replay.execution(
        receipt(
            "2024-01-09",
            target=target,
            trades=[rest],
            target_trades=[first, rest],
            quantity=50.0,
            cost=5000.0,
            completed=False,
            status="pending",
        )
    )
    assert replay.position.stages == ()
    # The final callback may contain no new attack fill (e.g. another leg resumes).
    final = receipt(
        "2024-01-10",
        target=target,
        target_trades=[first, rest],
        quantity=50.0,
        cost=5000.0,
    )
    replay.execution(final)
    assert replay.position.stages == (1,)
    assert replay.entry_day == pd.Timestamp("2024-01-10").date()
    assert sum(lot["quantity"] for lot in replay.lots) == 50.0
    before = replay.position
    replay.execution(final)
    assert replay.position == before


def test_restore_budget_tracks_actual_sold_units_at_current_price(replay):
    replay.position = Position(0.8, stages=(1,), entry_mode="normal")
    planned = decision(
        replay.position, "2024-01-05", "P3_MA10", Action("reduce", 0.25), priority=3
    )
    target = Target(
        planned.as_of, {"159915": 0.6}, "restore-actual-test", planned.as_of
    )
    replay.pending[target.reason] = planned
    replay.execution(
        receipt(
            "2024-01-08",
            target=target,
            trades=[fill("sell", 20.0)],
            quantity=60.0,
            cost=6000.0,
        )
    )
    assert replay.restore_quantity == 20.0
    replay._context(instant("2024-01-12"), row(60.0, 110.0, 10000.0))
    assert replay.position.pending_restore_weight == pytest.approx(0.22)


def test_peak_survives_buy_without_revaluing_old_peak_at_new_cost(replay):
    replay.cost = 100.0
    before = replay._context(instant("2024-01-05"), row(1.0, 210.0, 1000.0))
    assert before["peak_profit_pct"] == pytest.approx(110.0)
    replay.execution(
        receipt("2024-01-08", trades=[fill("buy", 0.01)], quantity=1.01, cost=101.0)
    )
    after = replay._context(instant("2024-01-12"), row(1.01, 188.0, 1000.0))
    assert after["peak_profit_pct"] == pytest.approx(110.0)
    assert after["drawdown_8"] is True
    # A different cycle never exceeded 50% profit. Averaging down must not arm
    # a >100% profit stop by dividing an old price peak by the new lower cost.
    replay.peak = None
    replay.peak_profit_seen = 0.0
    replay.cost = 100.0
    seen = replay._context(instant("2024-01-19"), row(1.0, 150.0, 1000.0))
    assert seen["peak_profit_pct"] == pytest.approx(50.0)
    replay.execution(
        receipt("2024-01-22", trades=[fill("buy", 2.0, 20.0)], quantity=3.0, cost=140.0)
    )
    diluted = replay._context(instant("2024-01-26"), row(3.0, 20.0, 1000.0))
    assert diluted["peak_profit_pct"] == pytest.approx(
        50.0
    ), "Historical peak profit must use the cost actually known at that observation"


def test_first_four_week_window_closes_and_later_entry_does_not_reset(replay):
    replay.position = Position(0.5, stages=(1,), entry_mode="normal")
    replay.entry_day = pd.Timestamp("2024-01-02").date()
    replay.etf_weeks.loc[1, "high"] = 110.0  # First window fails its amplitude test.
    fourth = instant("2024-02-02")
    context = replay._context(fourth, row(50.0))
    assert context["post_entry_four_weeks"] is True
    assert context["sideways_rows"][0][0] == 110.0
    replay.snapshot_factory = lambda s, p: snapshot(
        s.as_of, **replay._context(s.as_of, row(50.0))
    )
    replay.close(fourth, {}, row(50.0))
    assert replay.audit[-1]["rule_status"]["P1_TIME"] == Status.CLEAR.value
    assert replay.time_window_evaluated is True
    later = replay._context(instant("2024-02-16"), row(50.0))
    assert later["post_entry_four_weeks"] is False
    assert later["sideways_rows"] == context["sideways_rows"]
    original_day, original_high = replay.entry_day, replay.entry_high
    planned = decision(
        replay.position, "2024-02-16", "ENTRY_SECOND", Action("entry", 0.2, stages=(2,))
    )
    target = Target(planned.as_of, {"159915": 0.7}, "second-entry", planned.as_of)
    replay.pending[target.reason] = planned
    replay.execution(
        receipt(
            "2024-02-19",
            target=target,
            trades=[fill("buy", 20.0)],
            quantity=70.0,
            cost=7000.0,
        )
    )
    assert replay.entry_day == original_day and replay.entry_high == original_high
    assert replay.time_window_evaluated is True


def test_each_entry_and_restore_checks_its_fraction_and_all_cost_buffers(replay):
    base = operational_policy()
    policy = Policy(
        {
            **base.approvals,
            "equity_bond_definition": "synthetic-only",
            "equity_bond_extreme": "synthetic-only",
        },
        base.parameters,
    )
    common = dict(
        effective_above_ma60=True,
        bullish_week=True,
        missed_first_nonbullish=True,
        two_weeks_above_ma60=True,
        zscore=-3.0,
        equity_bond_ratio=1.0,
        equity_bond_extreme=True,
        iv_short_pct=99.0,
        iv_long_pct=90.0,
        margin_cleared=True,
        week_return_pct=8.0,
        fast_entry_allowed=True,
        retest_ma60=True,
        break_bear_rally_high=True,
        volume_breakout=True,
        restore_allowed=True,
        stop_distance_pct=4.0,
        execution_cost_buffer_pct=1.16,
    )
    now = "2024-02-02"
    rules = {
        r.rule_id: r for r in entry_rules(snapshot(now, **common), Position(), policy)
    }
    assert rules["ENTRY_FIRST"].action is not None  # .5 * 5.16 = 2.58
    assert rules["ENTRY_FAST"].action is not None
    assert rules["ENTRY_NUCLEAR"].status is Status.CLEAR  # 1 * 5.16 > 3
    assert rules["ENTRY_CATCHUP"].status is Status.CLEAR  # .7 * 5.16 > 3
    held = Position(
        0.5,
        stages=(1,),
        entry_mode="normal",
        pending_restore_weight=0.2,
        restore_due=now,
    )
    rules = {r.rule_id: r for r in entry_rules(snapshot(now, **common), held, policy)}
    for name in ("ENTRY_SECOND", "ENTRY_THIRD", "P3_RESTORE"):
        assert rules[name].action is not None
    # Isolate the fee/slippage/stress effect: distance alone would pass at 2.5%.
    rules = {
        r.rule_id: r
        for r in entry_rules(
            snapshot(now, **{**common, "stop_distance_pct": 5.0}), Position(), policy
        )
    }
    assert rules["ENTRY_FIRST"].status is Status.CLEAR  # .5 * 6.16 > 3
    missing = {**common, "execution_cost_buffer_pct": None}
    rules = {
        r.rule_id: r for r in entry_rules(snapshot(now, **missing), Position(), policy)
    }
    assert rules["ENTRY_FIRST"].status is Status.MISSING
    replay.fee_rate, replay.slippage = 0.001, 0.002
    context = replay._context(instant(now), row())
    assert context["execution_cost_buffer_pct"] == pytest.approx(1.6)


def test_divergence_uses_each_historical_week_publication_cutoff():
    dates = pd.date_range("2023-01-06", periods=70, freq="W-FRI")
    weekly = pd.DataFrame(
        dict(
            date=dates,
            open=100.0,
            high=102.0,
            low=99.0,
            close=100.0,
            volume=1000.0,
            ma60=90.0,
            ma10=95.0,
            slope_ma60=1.0,
            ret=0.0,
            vol_pct52=70.0,
            dev_ma60=1.0,
            rsi14=50.0,
        )
    )
    weekly.loc[weekly.index[-1], ["close", "high"]] = [110.0, 111.0]
    calendar = TradingCalendar(tuple(dates.date), "synthetic-regression-only", True)
    now = instant(dates[-1])
    margin = pd.DataFrame(
        dict(
            date=dates[-27:],
            value=[10.0] * 26 + [5.0],
            available_at=[instant(d) for d in dates[-27:]],
            source="synthetic-only",
        )
    )
    prepared = {
        "week": weekly,
        "month": weekly.iloc[:0],
        "defense_week": weekly.iloc[:0],
    }

    def build(frame):
        # Keep this regression about publication cutoffs, independent of the
        # timestamp resolution pandas infers when assigning a scalar datetime.
        frame = frame.copy()
        frame["available_at"] = pd.to_datetime(frame.available_at, utc=True).astype(
            "datetime64[ns, UTC]"
        )
        return build_operational_snapshot(
            weekly,
            weekly.iloc[:0],
            calendar,
            as_of=now,
            policy=operational_policy(),
            macros={"margin_pct": frame},
            prepared=prepared,
        )[0]

    assert build(margin).get("top_divergence") is True
    delayed = margin.copy()
    delayed["available_at"] = now
    assert build(delayed).get("top_divergence") is None
    delayed.loc[delayed.index[:-1], "value"] = 4.0
    assert build(delayed).get("top_divergence") is None
    future = margin.copy()
    future.loc[future.index[-1], "available_at"] = now + pd.Timedelta(seconds=1)
    assert build(future).get("margin_pct") == 10.0
    assert build(future).get("top_divergence") is False
