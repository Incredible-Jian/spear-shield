from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import pandas as pd
import pytest

from spear_shield.database.engine import Database
from spear_shield.database.strategy_audit import StrategyAudit, load_history, save_decision
from spear_shield.strategy import Policy, Position, StrategyEngine
from spear_shield.strategy.defense import defense_plan
from spear_shield.strategy.inputs import build_snapshot


def bars(freq, periods):
    dates=pd.date_range("2020-01-01", periods=periods, freq=freq)
    return pd.DataFrame({"date":dates,"open":range(100,100+periods),
        "high":range(102,102+periods),"low":range(99,99+periods),
        "close":range(101,101+periods),"volume":100.,
        "available_at":dates.tz_localize("Asia/Shanghai")+pd.Timedelta(hours=16),
        "is_final":True,"adjust":"qfq","source":"synthetic-test-only"})


def build(weekly,monthly,approved,**overrides):
    args=dict(as_of=datetime(2026,10,30,10,tzinfo=timezone.utc),
        valid_until=datetime(2026,11,1,0,tzinfo=timezone.utc),signal_symbol="399006",
        expected_week_close=weekly.iloc[-1]["date"].date(),
        expected_month_close=monthly.iloc[-1]["date"].date(),
        policy=approved("signal_series_definition"))
    args.update(overrides)
    return build_snapshot(weekly,monthly,**args)


def test_period_isolation_and_known_slope(approved):
    w,m=bars("W-FRI",65),bars("ME",65)
    before=w.copy(deep=True)
    s=build(w,m,approved)
    # close=101..165; MA60最后135.5，前期134.5；斜率百分值。
    assert s.get("week_slope") == pytest.approx(100/134.5)
    assert s.get("month_slope") == pytest.approx(100/134.5)
    pd.testing.assert_frame_equal(w,before)
    assert s.weekly_final


def test_partial_future_and_wrong_expected_week_not_usable(approved):
    w,m=bars("W-FRI",65),bars("ME",65)
    w.loc[64,"is_final"]=False
    s=build(w,m,approved)
    assert not s.weekly_final and s.get("week_close") is None
    w.loc[64,"is_final"]=True
    w.loc[64,"available_at"]=pd.Timestamp("2030-01-01",tz="UTC")
    assert not build(w,m,approved).weekly_final


def test_prefix_invariance_with_future_rows(approved):
    w,m=bars("W-FRI",70),bars("ME",70)
    asof=w.iloc[64]["available_at"].to_pydatetime()+timedelta(hours=1)
    # monthly last expected可早于完整原表末行，按照asof截断。
    month_expected=m.loc[m.available_at<=asof].iloc[-1]["date"].date()
    options=dict(as_of=asof,valid_until=asof+timedelta(days=1),
                 expected_week_close=w.iloc[64]["date"].date(),expected_month_close=month_expected)
    a=build(w,m,approved,**options)
    b=build(w.iloc[:65],m.loc[m.available_at<=asof],approved,**options)
    assert a.facts == b.facts


@pytest.mark.parametrize("change", ["duplicate","daily_as_week","raw","no_release","naive_release"])
def test_invalid_input_contract(approved,change):
    w,m=bars("W-FRI",65),bars("ME",65)
    if change=="duplicate": w.loc[64,"date"]=w.loc[63,"date"]
    elif change=="daily_as_week": w["date"]=pd.date_range("2020-01-01",periods=65)
    elif change=="raw": w["adjust"]="none"
    elif change=="no_release": w=w.drop(columns="available_at")
    elif change=="naive_release": w["available_at"]=w["available_at"].dt.tz_localize(None)
    with pytest.raises(ValueError): build(w,m,approved)


def test_missing_whole_period_resets_warmup(approved):
    w,m=bars("W-FRI",65),bars("ME",65)
    s=build(w.drop(index=30),m,approved)
    assert s.get("week_slope") is None
    assert s.get("month_slope") is not None


def test_signal_basis_not_silently_selected(approved):
    with pytest.raises(ValueError):
        build(bars("W-FRI",65),bars("ME",65),approved,policy=Policy())


def test_weekly_sop_cannot_publish_before_1530(approved):
    w,m=bars("W-FRI",65),bars("ME",65)
    w["available_at"]=w["date"].dt.tz_localize("Asia/Shanghai")+pd.Timedelta(hours=15,minutes=5)
    asof=(w.iloc[-1]["available_at"]+pd.Timedelta(minutes=5)).to_pydatetime()
    monthly=m.loc[m.available_at<=asof]
    s=build(w,monthly,approved,as_of=asof,valid_until=asof+timedelta(days=1))
    assert not s.weekly_final


@pytest.mark.parametrize("z,expected", [(-2.01,(.2,.7,.1)),(-2,(.6,.3,.1)),
    (1.5,(.6,.3,.1)),(1.51,(.8,.1,.1))])
def test_defense_exact_thresholds(snapshot,approved,z,expected):
    plan=defense_plan(snapshot(zscore=z,defense_fuse=False),
        approved("zscore_definition","defense_fuse_definition"),active=True,
        current_weights={"563020":.6,"511360":.3,"511990":.1})
    assert tuple(plan["weights"].values()) == expected
    assert sum(plan["weights"].values()) == pytest.approx(1)
    assert plan["deviations"]["563020"] == pytest.approx(expected[0]-.6)


def test_defense_fuse_does_not_invent_bond_cash_split(snapshot,approved):
    p=approved("zscore_definition","defense_fuse_definition")
    plan=defense_plan(snapshot(zscore=0,defense_fuse=True),p,active=True)
    assert plan["weights"]["563020"] == .3
    assert plan["unallocated"] == .3
    assert plan["executable"] is False
    assert defense_plan(snapshot(zscore=0),p,active=True)["executable"] is False
    assert defense_plan(snapshot(),p,active=False)["status"] == "未激活"


def test_audit_roundtrip_idempotence_and_missing_reason(tmp_path,snapshot):
    db=Database(f"sqlite:///{(tmp_path/'audit.db').as_posix()}")
    db.init()
    s=snapshot(week_slopes2=(-1,-1))
    p=Position(.5)
    policy=Policy()
    d=StrategyEngine(policy).evaluate(s,p)
    with db.new_session() as session:
        a=save_decision(session,s,p,policy,d)
        assert save_decision(session,s,p,policy,d) == a
        session.commit()
        assert session.query(StrategyAudit).count()==1
        row=load_history(session)[0]
        assert row["decision"]["selected"]["rule_id"]=="P0_TREND"
        assert row["snapshot"]["facts"]["week_slopes2"]["source"]=="synthetic-test-only"
        assert row["decision"]["results"][0]["conditions"][0]["expression"]
    db.close()
    # 重开连接，记录仍在。
    db=Database(f"sqlite:///{(tmp_path/'audit.db').as_posix()}")
    with db.new_session() as session:
        assert len(load_history(session))==1
    db.close()
