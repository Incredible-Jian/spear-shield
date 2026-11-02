from dataclasses import replace
from datetime import timedelta
import pytest

from spear_shield.strategy import Policy, Position, Status, StrategyEngine
from spear_shield.strategy.rules import entry_rules, exit_rules
from spear_shield.portfolio.state import confirm_execution


def find(rules,name):
    return next(r for r in rules if r.rule_id==name)


@pytest.mark.parametrize("drop,expected",[(20,False),(20.001,True),(-1,False)])
def test_atr_strict_price_boundary(snapshot,approved,drop,expected):
    s=snapshot(max_week_drop_price=drop,week_atr14=10)
    r=find(exit_rules(s,Position(.8),approved("atr_drawdown_definition")),"P1_ATR")
    assert (r.status is Status.TRIGGERED) is expected


def test_atr_flag_without_actual_price_data_never_fires(snapshot,approved):
    r=find(exit_rules(snapshot(intraday_atr_breach=True),Position(.5),
                      approved("atr_drawdown_definition")),"P1_ATR")
    assert r.status is Status.MISSING


def test_intraday_does_not_override_known_final_p0(snapshot,approved):
    s=snapshot(week_slopes2=(-1,-1),max_week_drop_price=21,week_atr14=10)
    d=StrategyEngine(approved("atr_drawdown_definition")).evaluate_intraday(s,Position(.8))
    assert d.selected.rule_id=="P0_TREND"


@pytest.mark.parametrize("end",[97.,103.])
def test_sideways_inclusive_three_percent(snapshot,approved,end):
    rows=[(101,99,100,100)]*3+[(end+.1,end-.1,end,100)]
    s=snapshot(post_entry_four_weeks=True,sideways_rows=rows,entry_week_high=110)
    assert find(exit_rules(s,Position(.5),approved("entry_completion_definition")),"P1_TIME").status is Status.TRIGGERED


@pytest.mark.parametrize("mode",["bear","fast",None])
def test_nonstandard_base_cannot_add_as_normal(snapshot,approved,mode):
    policy=replace(approved("effective_break_definition","bullish_definition","retest_definition",
        "margin_redline","margin_definition","single_trade_risk_definition"),parameters={"margin_redline_pct":2.3})
    s=snapshot(week_slopes2=(.1,.1),month_slope=1,margin_pct=2,risk_budget_pass=True,
               retest_ma60=True,deviation_ma60_pct=1,bullish_week=True)
    assert find(entry_rules(s,Position(.2,(1,),entry_mode=mode),policy),"ENTRY_SECOND").action is None


def holding_case(snapshot,approved,**extra):
    pol=replace(approved("entry_completion_definition","atr_drawdown_definition",
        "bottom_definition","above_ma30_definition","volume_baseline_definition",
        "rsi_definition","pe_definition","margin_definition","margin_redline",
        "zscore_definition","candle_definition","stall_definition"),parameters={"margin_redline_pct":2.3})
    facts=dict(week_slopes2=(1,1),month_slopes2=(1,1),week_close=9,week_ma60=8,
        post_entry_four_weeks=False,max_week_drop_price=0,week_atr14=1,zscore=0,
        profit_pct=31,rise_from_bottom_100=False,six_of_eight_above_ma30=False,
        week_return_pct=0,volume_1_5=False,rsi=50,pe_percentile=30,peg=1,
        margin_pct=2,margin_turnover_pct=0,week_ma10=10)
    facts.update(extra)
    return snapshot(**facts),pol


def test_p3_selected_after_higher_levels_are_explicitly_clear(snapshot,approved):
    s,pol=holding_case(snapshot,approved)
    d=StrategyEngine(pol).evaluate(s,Position(.8,entry_mode="normal"))
    assert d.selected.rule_id=="P3_MA10"
    state=confirm_execution(d.position,d,"ma10",next_week_close=(s.as_of+timedelta(days=7)).date())
    assert state.attack_weight==pytest.approx(.6)


def test_p2_dominates_p3_without_reduction_stacking(snapshot,approved):
    s,pol=holding_case(snapshot,approved,zscore=2.1,long_upper_shadow=True,low_volume_stall=False)
    d=StrategyEngine(pol).evaluate(s,Position(.8))
    assert d.selected.rule_id=="P2_STYLE"
    state=confirm_execution(d.position,d,"p2")
    assert state.attack_weight==pytest.approx(.4)


def test_p1_dominates_p2_and_p3(snapshot,approved):
    s,pol=holding_case(snapshot,approved,zscore=2.1,long_upper_shadow=True,
                       low_volume_stall=False,max_week_drop_price=3)
    assert StrategyEngine(pol).evaluate(s,Position(.8)).selected.rule_id=="P1_ATR"


def test_negative_z_does_not_make_missing_higher_risk_pass(snapshot,approved):
    s=snapshot(profit_pct=31,week_close=9,week_ma10=10,zscore=-3)
    assert StrategyEngine(approved("zscore_definition")).evaluate(s,Position(.8)).status=="blocked"
