"""实际缓存反向追踪与明确隔离的合成异常回归。"""

import copy
import json
from datetime import date, datetime, time
import os
from pathlib import Path
import runpy
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from spear_shield.backtest import (
    BacktestConfig,
    BacktestEngine,
    MarketData,
    Target,
    TradingCalendar,
    ProtectiveStop,
)
from spear_shield.backtest.lineage import build_lineage, trace_equity, validate_lineage
from spear_shield.strategy.features import (
    candle_features,
    settled_bars,
    complete_segment_indicators,
)
from spear_shield.strategy.operational import operational_policy
from spear_shield.strategy.types import Position, Action

ROOT = Path(__file__).resolve().parents[2]
SH = ZoneInfo("Asia/Shanghai")


@pytest.fixture(scope="module")
def real_result():
    from spear_shield.database.engine import Database
    from spear_shield.services.workspace import Workspace
    from spear_shield.services.research_dataset import load_operational_dataset
    from spear_shield.backtest.strategy_replay import StrategyReplay

    data = Path(
        os.environ.get("SPEAR_SHIELD_AUDIT_DATA_DIR", ROOT / "cache/phase5-preview")
    )
    if (
        not (data / "spear_shield.db").is_file()
        or not (ROOT / "cache/research-sources/manifest.json").is_file()
    ):
        pytest.skip("真实Phase6缓存缺失；不以合成数据代替真实审计")
    db = Database(f"sqlite:///{(data/'spear_shield.db').as_posix()}")
    w = Workspace(db)
    frames = {s: w.history(s, "qfq") for s in ("159915", "563020", "511360", "511990")}
    result = StrategyReplay(load_operational_dataset(w), frames).run(
        BacktestConfig(date(2024, 1, 2), date(2026, 10, 30), 100000.0, 0.0003, 0.0005)
    )
    db.close()
    return result


def test_real_defense_equity_receipt_order_decision_indicator_raw_chain(real_result):
    result = real_result
    graph = build_lineage(result)
    assert validate_lineage(graph)
    assert validate_lineage(json.loads(json.dumps(graph, default=str)))
    assert graph["unlinked"] == []
    equity = next(n for n in graph["nodes"]["equity"] if n["payload"]["trade_ids"])
    trace = trace_equity(graph, equity["id"])
    assert len(trace["trades"]) == 3 and all(
        t["trade"]["symbol"] != "159915" for t in trace["trades"]
    )
    assert any(r["receipt"]["actual_fills"] == 3 for r in trace["receipts"])
    decision = trace["decisions"][0]["audit"]
    signal = trace["signals"][0]["signal"]
    assert signal["weights"]["563020"] == decision["defense"]["weights"]["563020"]
    assert decision["evidence"]["zscore"]["value"] is not None
    raw_growth = next(
        r
        for r in result.metadata["signal_input_bars"]["399006"]
        if r["date"].startswith(signal["signal_at"][:10])
    )
    assert decision["evidence"]["week_close"]["value"] == raw_growth["close"]
    current = trace["equity"]["valuation"]
    cash_cost = 0.0
    for t in trace["trades"]:
        trade = t["trade"]
        bar = next(
            r
            for r in result.metadata["input_bars"][trade["symbol"]]
            if r["date"] == trade["date"]
        )
        assert trade["price"] == pytest.approx(bar["open"] * 1.0005)
        assert trade["fee"] == pytest.approx(
            trade["price"] * trade["quantity"] * 0.0003
        )
        assert (
            pd.Timestamp(trade["date"]).date() > pd.Timestamp(trade["signal_at"]).date()
        )
        cash_cost += trade["price"] * trade["quantity"] + trade["fee"]
    assert current["cash"] == pytest.approx(100000.0 - cash_cost)
    assert current["equity"] == pytest.approx(
        current["cash"] + sum(current["market_values"].values()) + current["receivable"]
    )
    assert all(
        "synthetic" not in s.lower() and "test-only" not in s.lower()
        for values in result.metadata["sources"].values()
        for s in values
    )


def test_real_missing_data_and_untriggerable_attack_are_explicit(real_result):
    graph = build_lineage(real_result)
    assert real_result.metadata["attack_trade_count"] == 0
    assert real_result.metadata["complete_strategy_validated"] is False
    assert {
        "iv_short_pct",
        "iv_long_pct",
        "equity_bond_ratio",
        "pe_percentile",
        "peg",
    } <= set(real_result.metadata["input_gaps"])
    conditions = [
        c
        for row in real_result.metadata["strategy_audit"]
        for c in row["rule_conditions"]["ENTRY_NUCLEAR"]
    ]
    assert any(
        c["truth"] == "UNKNOWN" and "equity_bond_ratio" in c["inputs"]
        for c in conditions
    )
    assert not any(
        row["selected"] == "ENTRY_NUCLEAR"
        for row in real_result.metadata["strategy_audit"]
    )
    assert graph["attribution"]["full_strategy_return"] is None
    assert abs(graph["attribution"]["total_residual"]) < 1e-6
    assert {r["symbol"] for r in graph["attribution"]["assets"]} == {
        "159915",
        "563020",
        "511360",
        "511990",
    }


def test_data_version_change_identifies_new_research_run_without_rewriting_old(
    real_result,
):
    before = build_lineage(real_result)
    revised = copy.deepcopy(real_result)
    revised.metadata["data_provenance"]["audit_revision_test"] = {
        "sha256": "f" * 64,
        "source": "synthetic metadata test only; no change to real data",
    }
    after = build_lineage(revised)
    assert before["run_id"] != after["run_id"]
    assert before["attribution"]["gain"] == after["attribution"]["gain"]
    tampered = copy.deepcopy(before)
    tampered["nodes"]["equity"][0]["payload"]["valuation"]["equity"] += 1
    with pytest.raises(ValueError, match="改变"):
        validate_lineage(tampered)
    assert validate_lineage(before)


def helpers():
    return runpy.run_path(str(ROOT / "tests/strategy/test_replay_regressions.py"))


def test_tiny_p0_is_not_discarded_as_defense_rebalance_dust():
    h = helpers()
    r = h["replay"].__wrapped__()
    r.position = Position(0.001, stages=(1,), entry_mode="normal")
    r.snapshot_factory = lambda s, p: h["snapshot"](s.as_of, week_slopes2=(-1.0, -1.0))
    target = r.close(h["instant"]("2024-01-05"), {}, h["row"](0.1, 100.0, 10000.0))
    assert target is not None and target.weights["159915"] == 0.0
    assert r.audit[-1]["target_emitted"] is True and "P0_TREND" in r.queued_risks


def test_partial_risk_sale_and_cancellation_invalidates_old_restore():
    h = helpers()
    r = h["replay"].__wrapped__()
    r.position = Position(
        0.8,
        stages=(1,),
        entry_mode="normal",
        pending_restore_weight=0.2,
        restore_due="2024-01-12",
    )
    r.restore_quantity = 20.0
    d = h["decision"](r.position, "2024-01-05", "P2_STYLE", Action("reduce", 0.5), 2)
    target = Target(d.as_of, {"159915": 0.4}, "audit-partial-risk", d.as_of)
    r.pending[target.reason] = d
    sold = h["fill"]("sell", 10.0)
    r.execution(
        h["receipt"](
            "2024-01-08",
            target=target,
            trades=[sold],
            quantity=70.0,
            cost=7000.0,
            completed=False,
            status="pending",
        )
    )
    r.execution(
        h["receipt"](
            "2024-01-09",
            target=target,
            target_trades=[sold],
            quantity=70.0,
            cost=7000.0,
            status="superseded",
        )
    )
    assert (
        r.restore_quantity == 0
        and r.position.pending_restore_weight == 0
        and r.position.restore_due is None
    )
    assert (
        r.position.attack_weight == 0.8
    )  # 该回执不伪造完整计划成交；下次收盘用真实数量估值。
    assert r.receipts[-1]["actual_fills"] == 0 and r.receipts[0]["actual_fills"] == 1


def test_cross_week_event_latch_keeps_actual_reduction_without_duplicate():
    h = helpers()
    r = h["replay"].__wrapped__()
    r.position = Position(0.8, stages=(1,), entry_mode="normal")
    r.snapshot_factory = lambda s, p: h["snapshot"](
        s.as_of, zscore=3.0, long_upper_shadow=True
    )
    target = r.close(h["instant"]("2024-01-05"), {}, h["row"]())
    r.execution(
        h["receipt"](
            "2024-01-08",
            target=target,
            trades=[h["fill"]("sell", 40.0)],
            quantity=40.0,
            cost=4000.0,
        )
    )
    assert r.close(h["instant"]("2024-01-12"), {}, h["row"](40.0)) is None
    assert (
        "P2_STYLE" in r.risk_latched
        and r.audit[-1]["rule_status"]["P2_STYLE"] == "触发"
    )


def test_nan_inside_trading_week_remains_unknown_and_rewarms():
    dates = pd.bdate_range("2022-01-03", periods=700)
    df = pd.DataFrame(
        {
            "date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        }
    )
    cal = TradingCalendar(tuple(dates.date), "synthetic-test-only", True)
    df.loc[330, "close"] = np.nan
    bars = settled_bars(
        df, cal, datetime.combine(dates[-1].date(), time(15, 30), SH), "week"
    )
    assert bars.close.isna().sum() == 1
    computed = complete_segment_indicators(bars, "week")
    gap = bars.index[bars.close.isna()][0]
    assert computed.ma60.iloc[gap + 1 : gap + 60].isna().all()
    assert np.isfinite(computed.ma60.iloc[gap + 60])


def test_incomplete_candle_history_is_unknown_not_false():
    row = {
        "open": 99.0,
        "high": 101.0,
        "low": 98.0,
        "close": 100.0,
        "ma60": 99.0,
        "ma10": 99.0,
        "volume": 1000.0,
        "ret": 1.0,
        "vol_pct52": np.nan,
    }
    assert (
        candle_features(pd.DataFrame([row]), operational_policy())[
            "two_weeks_above_ma60"
        ]
        is None
    )
    previous = {**row, "open": 101.0}
    assert (
        candle_features(pd.DataFrame([previous, row]), operational_policy())[
            "missed_first_nonbullish"
        ]
        is None
    )


def test_known_open_issue_atr_stop_must_not_be_undone_by_stale_target():
    days = (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(days),
            "open": 10.0,
            "high": 11.0,
            "low": [9.0, 7.0, 9.0],
            "close": 10.0,
            "volume": 1000.0,
            "source": "synthetic-test-only",
            "adjust": "qfq",
        }
    )
    defense = frame.copy()
    defense["suspended"] = [False, True, False]
    cal = TradingCalendar(days, "synthetic-test-only", True)
    t0 = datetime(2024, 1, 1, 15, 30, tzinfo=SH)
    t1 = datetime(2024, 1, 2, 15, 30, tzinfo=SH)
    provider = lambda opening, history, state: (
        ProtectiveStop("159915", 8.0, 0.5, t1, "synthetic-ATR")
        if opening.date() == days[1]
        else None
    )
    result = BacktestEngine().run(
        MarketData({"159915": frame, "563020": defense}, cal),
        BacktestConfig(days[0], days[-1], 1000.0, 0.0, 0.0, enforce_t_plus_one=True),
        [
            Target(t0, {"159915": 1.0}, "initial", t0),
            Target(t1, {"159915": 0.8, "563020": 0.2}, "stale", t1),
        ],
        stop_provider=provider,
    )
    assert not any(
        t["date"] == days[2].isoformat()
        and t["symbol"] == "159915"
        and t["side"] == "buy"
        for t in result.trades
    )
