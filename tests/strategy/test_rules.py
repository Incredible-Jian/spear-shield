from dataclasses import replace
from datetime import date
import pytest

from spear_shield.strategy import Policy, Position, Status, StrategyEngine
from spear_shield.strategy.rules import entry_rules, exit_rules
from spear_shield.portfolio.state import confirm_execution, observe_month


def find(results, key):
    return next(r for r in results if r.rule_id == key)


@pytest.mark.parametrize("week,month,trigger", [((-.1,-.2),(1,1),True),
    ((1,1),(-.1,-.2),True), ((0,-.2),(1,1),False), ((-.1,0),(0,0),False),
    ((None,-.1),(1,1),None), ((1,1),(-.1,-.1),True)])
def test_p0_strict_two_periods(snapshot, week,month,trigger):
    rule = find(exit_rules(snapshot(week_slopes2=week,month_slopes2=month),
                           Position(.5), Policy()),"P0_TREND")
    assert rule.status == ({True:Status.TRIGGERED,False:Status.CLEAR,None:Status.MISSING}[trigger])


def test_priority_p0_excludes_repeated_reductions(snapshot):
    s = snapshot(week_slopes2=(-1,-1),week_close=1,week_ma60=2,
                 eligible_lot_weight=.4,profit_pct=40,week_ma10=3)
    d = StrategyEngine().evaluate(s,Position(.4))
    assert d.status == "actionable"
    assert d.selected.rule_id == "P0_TREND"
    assert d.selected.action.fraction == 1
    assert find(d.results,"P1_FALSE_BREAK").status is Status.TRIGGERED
    assert find(d.results,"P3_MA10").status is Status.TRIGGERED


def test_missing_higher_priority_blocks_lower(snapshot):
    s = snapshot(week_close=1,week_ma60=2,eligible_lot_weight=.5)
    d = StrategyEngine().evaluate(s,Position(.5))
    assert d.status == "blocked" and d.selected is None


def test_partial_week_has_no_final_decision(snapshot):
    s = replace(snapshot(week_slopes2=(-1,-1)),weekly_final=False)
    assert StrategyEngine().evaluate(s,Position(.5)).selected is None


def test_false_break_only_eligible_lot(snapshot):
    s = snapshot(week_slopes2=(1,1),month_slopes2=(1,1),week_close=90,
                 week_ma60=100,eligible_lot_weight=.2)
    d = StrategyEngine().evaluate(s,Position(.6))
    assert d.selected.rule_id == "P1_FALSE_BREAK"
    after = confirm_execution(Position(.6),d,"lot-stop")
    assert after.attack_weight == pytest.approx(.4)


def test_same_priority_conflict_not_stacked(snapshot, approved):
    s = snapshot(week_slopes2=(1,1),month_slopes2=(1,1),week_close=90,week_ma60=100,
                 eligible_lot_weight=.5,max_week_drop_price=21,week_atr14=10)
    d = StrategyEngine(approved("atr_drawdown_definition")).evaluate(s,Position(.5))
    assert d.status == "conflict" and d.selected is None


def test_time_stop_manual_values_and_amplitude_boundary(snapshot,approved):
    policy = approved("entry_completion_definition")
    rows = [(101,99,100,100)]*4
    s = snapshot(post_entry_four_weeks=True,sideways_rows=rows,entry_week_high=102)
    assert find(exit_rules(s,Position(.5),policy),"P1_TIME").status is Status.TRIGGERED
    rows[2] = (102,98,100,100)  # 恰好4%不触发
    s = snapshot(post_entry_four_weeks=True,sideways_rows=rows,entry_week_high=102)
    assert find(exit_rules(s,Position(.5),policy),"P1_TIME").status is Status.CLEAR


def test_seven_of_five_does_not_count_unknown_as_true(snapshot,approved):
    s = snapshot(profit_pct=80,week_return_pct=10,rise_from_bottom_100=True,
                 six_of_eight_above_ma30=True,volume_1_5=True)
    p = approved("bottom_definition","above_ma30_definition","volume_baseline_definition")
    rule = find(exit_rules(s,Position(.5),p),"P2_TOP")
    assert rule.status is Status.TRIGGERED  # 5个已知真，另2个未知
    assert len(rule.conditions) == 9
    s = snapshot(profit_pct=80,week_return_pct=10)
    assert find(exit_rules(s,Position(.5),Policy()),"P2_TOP").status is Status.PENDING


@pytest.mark.parametrize("profit,close,trigger", [(30,9,False),(30.01,9,True),(31,10,False)])
def test_p3_profit_and_ma_boundaries(snapshot,profit,close,trigger):
    rule=find(exit_rules(snapshot(profit_pct=profit,week_close=close,week_ma10=10),
                         Position(.8),Policy()),"P3_MA10")
    assert (rule.status is Status.TRIGGERED) is trigger


def entry_snapshot(snapshot,**extra):
    values=dict(week_slopes2=(.1,.1),month_slope=.1,effective_above_ma60=True,
                bullish_week=True,volume_pct52=60,margin_pct=2.0,risk_budget_pass=True)
    values.update(extra)
    return snapshot(**values)


def entry_policy(approved,*extra):
    return replace(approved("effective_break_definition","bullish_definition","margin_redline",
                    "margin_definition","single_trade_risk_definition",*extra),
                   parameters={"margin_redline_pct":2.3})


def test_default_entries_not_invented(snapshot):
    results=entry_rules(entry_snapshot(snapshot),Position(),Policy())
    assert find(results,"ENTRY_FIRST").status is Status.PENDING
    assert find(results,"ENTRY_NUCLEAR").action is None
    assert find(results,"ENTRY_FOURTH").status is Status.UNDEFINED


@pytest.mark.parametrize("slopes,volume,expected", [((.1,.1),60,True),((.099,.1),60,False),
                                                 ((.1,.1),59.99,False)])
def test_entry_boundaries_with_explicit_test_approvals(snapshot,approved,slopes,volume,expected):
    s=entry_snapshot(snapshot,week_slopes2=slopes,volume_pct52=volume)
    r=find(entry_rules(s,Position(),entry_policy(approved)),"ENTRY_FIRST")
    assert (r.status is Status.TRIGGERED) is expected


def test_nuclear_missing_iv_or_ratio_never_triggers(snapshot,approved):
    p=entry_policy(approved,"zscore_definition","margin_clear_definition")
    s=entry_snapshot(snapshot,z_below_minus2=True,margin_cleared=True)
    assert find(entry_rules(s,Position(),p),"ENTRY_NUCLEAR").action is None


def test_nuclear_lock_and_duplicate_stage(snapshot,approved):
    s=entry_snapshot(snapshot,retest_ma60=True,deviation_ma60_pct=3)
    p=entry_policy(approved,"retest_definition")
    assert find(entry_rules(s,Position(1,(1,),nuclear=True),p),"ENTRY_SECOND").action is None
    assert find(entry_rules(s,Position(.7,(1,2)),p),"ENTRY_SECOND").action is None


def test_second_and_third_additions_and_third_permanent_disable(snapshot,approved):
    s=entry_snapshot(snapshot,retest_ma60=True,deviation_ma60_pct=3,
        break_bear_rally_high=True,volume_breakout=True,pe_percentile=59.9)
    p=entry_policy(approved,"retest_definition","bear_rally_high_definition",
                   "breakout_volume_definition","pe_definition")
    rules=entry_rules(s,Position(.5,(1,),entry_mode="normal"),p)
    assert find(rules,"ENTRY_SECOND").action.fraction == .2
    assert find(rules,"ENTRY_THIRD").action.fraction == .3
    state=observe_month(Position(.5,(1,),entry_mode="normal"),-.1)
    state=observe_month(state,.2)
    assert find(entry_rules(s,state,p),"ENTRY_THIRD").action is None


def test_fast_bear_and_catchup_paths(snapshot,approved):
    p=entry_policy(approved,"fast_bear_precedence","pe_definition","bear_precondition_conflict",
                   "catchup_definition")
    s=entry_snapshot(snapshot,month_slope=-1,week_return_pct=8,pe_percentile=49.9,
                      fast_entry_allowed=True,bear_entry_allowed=True)
    rules=entry_rules(s,Position(),p)
    assert find(rules,"ENTRY_FAST").action.fraction == .5
    assert find(rules,"ENTRY_BEAR").action.fraction == .2
    s=entry_snapshot(snapshot,missed_first_nonbullish=True,two_weeks_above_ma60=True)
    assert find(entry_rules(s,Position(),p),"ENTRY_CATCHUP").action.fraction == .7


def test_intraday_atr_separate_and_definition_required(snapshot,approved):
    s=replace(snapshot(max_week_drop_price=21,week_atr14=10),weekly_final=False)
    assert StrategyEngine().evaluate_intraday(s,Position(.5)).selected is None
    d=StrategyEngine(approved("atr_drawdown_definition")).evaluate_intraday(s,Position(.5))
    assert d.selected.action.timing == "intraday"


def test_execution_only_updates_on_receipt_and_replay_idempotent(snapshot):
    state=Position(.8,(1,2))
    s=snapshot(week_slopes2=(-1,-1))
    d=StrategyEngine().evaluate(s,state)
    assert state.attack_weight == .8
    after=confirm_execution(state,d,"clear-1")
    assert after.attack_weight == 0
    assert confirm_execution(after,d,"clear-1") == after
    with pytest.raises(ValueError):
        confirm_execution(state,StrategyEngine().evaluate(replace(s,weekly_final=False),state),"bad")


def test_ma10_receipt_tracks_exact_reduction_and_restore_limit(snapshot,approved):
    # 专门验证执行状态，不要求无关P1/2缺失条件通过。
    from spear_shield.strategy.types import Decision
    rule=find(exit_rules(snapshot(profit_pct=31,week_close=9,week_ma10=10),
                          Position(.8),Policy()),"P3_MA10")
    d=Decision("actionable",rule,(rule,),"test",Position(.8),snapshot().as_of)
    after=confirm_execution(Position(.8),d,"cut",next_week_close=date(2026,11,6))
    assert after.attack_weight == pytest.approx(.6)
    assert after.pending_restore_weight == pytest.approx(.2)
    assert after.restore_due == "2026-11-06"
    with pytest.raises(ValueError):
        confirm_execution(Position(.8),d,"cut-no-calendar")
