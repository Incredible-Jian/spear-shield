from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import pytest

from spear_shield.database.engine import Database
from spear_shield.database.strategy_audit import load_history
from spear_shield.strategy import Evidence, Policy, Position, Status, StrategyEngine
from spear_shield.strategy.rules import entry_rules
from spear_shield.strategy.service import run_research
from spear_shield.portfolio.state import confirm_execution


def base(snapshot,**kwargs):
    data=dict(week_slopes2=(.1,.1),month_slopes2=(1,1),month_slope=1,
        effective_above_ma60=True,bullish_week=True,volume_pct52=60,margin_pct=2,
        risk_budget_pass=True)
    data.update(kwargs)
    return snapshot(**data)


def policy(approved,*keys):
    return replace(approved("effective_break_definition","bullish_definition","margin_redline",
        "margin_definition","single_trade_risk_definition",*keys),parameters={"margin_redline_pct":2.3})


def test_first_entry_end_to_end_and_state_binding(snapshot,approved):
    s=base(snapshot)
    p=Position()
    d=StrategyEngine(policy(approved)).evaluate(s,p)
    assert d.selected.rule_id == "ENTRY_FIRST"
    after=confirm_execution(p,d,"entry")
    assert after.attack_weight == .5 and after.stages == (1,)
    # 重放同一回执幂等；新的回执不能复用针对旧状态的同一裁决。
    assert confirm_execution(after,d,"entry") == after
    with pytest.raises(ValueError): confirm_execution(after,d,"different-entry")


def test_flat_p0_blocks_even_fast_path(snapshot,approved):
    s=base(snapshot,month_slopes2=(-1,-1),month_slope=-1,week_return_pct=8,
           pe_percentile=10,fast_entry_allowed=True)
    d=StrategyEngine(policy(approved,"pe_definition","fast_bear_precedence")).evaluate(s,Position())
    assert d.status == "defense" and d.selected is None


def test_full_nuclear_requires_actual_four_dimensions(snapshot,approved):
    pol=policy(approved,"zscore_definition","equity_bond_definition","equity_bond_extreme",
               "iv_definition","margin_clear_definition")
    s=base(snapshot,zscore=-2.1,equity_bond_ratio=1.0,equity_bond_extreme=True,
           iv_short_pct=96,iv_long_pct=81,margin_cleared=True)
    d=StrategyEngine(pol).evaluate(s,Position())
    assert d.selected.rule_id == "ENTRY_NUCLEAR"
    after=confirm_execution(Position(),d,"nuclear")
    assert after.attack_weight==1 and after.nuclear
    for key in ("iv_short_pct","equity_bond_ratio"):
        incomplete=replace(s,facts={k:v for k,v in s.facts.items() if k!=key})
        d=StrategyEngine(pol).evaluate(incomplete,Position())
        assert d.selected.rule_id=="ENTRY_FIRST"
        nuclear=next(r for r in d.results if r.rule_id=="ENTRY_NUCLEAR")
        assert nuclear.status is Status.MISSING


@pytest.mark.parametrize("short,long",[(95,90),(96,80),(19,29)])
def test_iv_strict_panic_boundaries(snapshot,approved,short,long):
    pol=policy(approved,"zscore_definition","equity_bond_definition","equity_bond_extreme",
               "iv_definition","margin_clear_definition")
    s=base(snapshot,zscore=-3,equity_bond_ratio=1,equity_bond_extreme=True,
           iv_short_pct=short,iv_long_pct=long,margin_cleared=True)
    rules=entry_rules(s,Position(),pol)
    assert next(r for r in rules if r.rule_id=="ENTRY_NUCLEAR").action is None


@pytest.mark.parametrize("margin,allows",[(2.3,True),(2.3001,False)])
def test_margin_redline_strict_boundary(snapshot,approved,margin,allows):
    d=StrategyEngine(policy(approved)).evaluate(base(snapshot,margin_pct=margin),Position())
    assert (d.selected is not None) is allows


def test_unknown_redline_cannot_be_replaced_by_boolean(snapshot,approved):
    pol=replace(policy(approved),parameters={})
    d=StrategyEngine(pol).evaluate(base(snapshot,margin_entry_allowed=True),Position())
    assert d.selected is None


def test_entry_paths_conflict_without_invented_precedence(snapshot,approved):
    pol=policy(approved,"pe_definition","fast_bear_precedence")
    s=base(snapshot,week_return_pct=8,pe_percentile=49,fast_entry_allowed=True)
    assert StrategyEngine(pol).evaluate(s,Position()).status == "conflict"


def test_restore_exact_next_week_and_maximum_twice(snapshot,approved):
    pol=policy(approved,"restore_definition")
    due="2026-10-30"
    state=Position(.6,(1,),restore_count=1,pending_restore_weight=.2,restore_due=due)
    s=base(snapshot,week_close=11,week_ma10=10,restore_allowed=True)
    rule=next(r for r in entry_rules(s,state,pol) if r.rule_id=="P3_RESTORE")
    assert rule.action.fraction==.2
    from spear_shield.strategy.types import Decision
    d=Decision("actionable",rule,(rule,),"test",state,s.as_of)
    after=confirm_execution(state,d,"restore-2")
    assert after.restore_count==2 and after.pending_restore_weight==0
    for changed in (replace(state,restore_count=2),replace(state,restore_due="2026-10-23")):
        assert next(r for r in entry_rules(s,changed,pol) if r.rule_id=="P3_RESTORE").action is None


def test_research_service_audits_partial_macro_and_p0(tmp_path,snapshot):
    db=Database(f"sqlite:///{(tmp_path/'research.db').as_posix()}")
    db.init()
    with db.new_session() as session:
        result=run_research(session,snapshot(week_slopes2=(-1,-1)),Position(.5))
        assert result.decision.selected.rule_id=="P0_TREND"
        assert result.macro["complete"] is False
        assert result.defense["weights"] is None
        session.commit()
        assert load_history(session)[0]["analysis"]["macro"]["status"]=="五维不完整"
    db.close()


def test_unconfirmed_week_cannot_activate_p0_defense(tmp_path,snapshot):
    db=Database(f"sqlite:///{(tmp_path/'unconfirmed.db').as_posix()}")
    db.init()
    with db.new_session() as session:
        s=replace(snapshot(week_slopes2=(-1,-1)),weekly_final=False)
        result=run_research(session,s,Position(.5))
        assert result.decision.status=="blocked"
        assert result.defense["status"]=="未激活"
    db.close()
