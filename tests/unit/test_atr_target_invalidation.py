"""方案A安全回归：真实执行器，合成输入明确隔离，不连接账户。"""

from datetime import date, datetime, time, timedelta
from pathlib import Path
import runpy
import sqlite3
import json
import subprocess
import sys

import pandas as pd
import pytest

from spear_shield.backtest import (
    BacktestConfig,
    BacktestEngine,
    MarketData,
    ProtectiveStop,
    Target,
    TradingCalendar,
)
from spear_shield.backtest.execution_journal import ExecutionJournal

SH = __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
DAYS = (date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8))


def stamp(day):
    return datetime.combine(day, time(15, 30), SH)


def scenario(
    *,
    initial=0.8,
    old=1.0,
    gap=False,
    lows=None,
    repeated=False,
    new_entry=False,
    journal_path=None,
    backend=None,
    fee=0.0,
    slippage=0.0,
    final_close=10.0,
):
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(DAYS),
            "open": [10.0, 7.0 if gap else 10.0, 10.0],
            "high": 11.0,
            "low": lows or [9.0, 6.0 if gap else 7.0, 7.0 if repeated else 9.0],
            "close": 10.0,
            "volume": 1000.0,
            "source": "synthetic-test-only-A",
            "adjust": "qfq",
        }
    )
    defense = df.copy()
    df.loc[df.index[-1], "close"] = final_close
    defense["suspended"] = [False, True, False]
    defense.loc[defense.suspended, "volume"] = 0.0
    initial_at = stamp(DAYS[0] - timedelta(days=1))
    old_at = stamp(DAYS[0])
    targets = [
        Target(
            initial_at,
            {"159915": initial, "563020": 1 - initial},
            "initial",
            initial_at,
        ),
        Target(old_at, {"159915": old}, "old-target", old_at),
    ]
    if new_entry:
        targets.append(
            Target(
                stamp(DAYS[1]), {"159915": 0.7}, "new-weekly-decision", stamp(DAYS[1])
            )
        )
    receipts = []

    def provider(opening, history, state):
        if opening.date() == DAYS[1] or repeated and opening.date() == DAYS[2]:
            return ProtectiveStop("159915", 8.0, 0.5, old_at, "ATR-fixed-event")

    result = (backend or BacktestEngine()).run(
        MarketData(
            {"159915": df, "563020": defense},
            TradingCalendar(DAYS, "synthetic-test-only", True),
        ),
        BacktestConfig(
            DAYS[0], DAYS[-1], 1000.0, fee, slippage, enforce_t_plus_one=True
        ),
        targets,
        stop_provider=provider,
        on_execution=receipts.append,
        **({"journal_path": journal_path} if backend is None else {}),
    )
    return result, receipts, targets


def cancelled(result):
    return [o for o in result.orders if o["status"] == "cancelled_atr"]


@pytest.mark.parametrize("initial,remaining", [(0.8, 40.0), (0.6, 30.0)])
def test_partial_hundred_unit_target_is_cancelled_without_rebuy_or_liquidation(
    initial, remaining
):
    r, receipts, targets = scenario(initial=initial)
    assert list(r.curve.quantity_159915) == [initial * 100, remaining, remaining]
    assert len(cancelled(r)) == 1
    cancellation = cancelled(r)[0]
    assert cancellation["target_id"] == targets[1].target_id
    assert cancellation["executed_quantity"]["159915"]["buy"] == 0
    assert cancellation["cancelled_remaining_quantity"]["159915"]["buy"] > 0
    assert cancellation["related_stop_order_id"]
    assert not any(t["date"] == DAYS[2].isoformat() for t in r.trades)
    assert r.trades[0]["quantity"] == initial * 100  # actual old fill retained
    assert list(r.curve.quantity_563020) == pytest.approx([(1 - initial) * 100] * 3)
    cancel_receipt = next(x for x in receipts if x["status"] == "cancelled_atr")
    assert cancel_receipt["trades"] == [] and cancel_receipt["completed"] is False
    assert (
        cancel_receipt["quantities"]["159915"] == initial * 100
    )  # before independent stop fill
    assert not any(
        x["status"] == "completed_with_cash_and_lot_constraints"
        and x.get("target_id") == targets[1].target_id
        for x in receipts
    )


def test_gap_stop_cancels_wholly_unexecuted_target_before_same_cycle_buy():
    r, receipts, targets = scenario(initial=0.4, gap=True)
    cancel_index = next(
        i for i, x in enumerate(receipts) if x["status"] == "cancelled_atr"
    )
    stop_index = next(i for i, x in enumerate(receipts) if x["type"] == "stop")
    assert cancel_index < stop_index
    assert r.curve.iloc[1].quantity_159915 == 20.0
    assert not any(
        t["side"] == "buy" and t["date"] >= DAYS[1].isoformat() for t in r.trades
    )
    assert cancelled(r)[0]["invalidation_phase"] == "open_gap"
    assert cancelled(r)[0]["executed_quantity"]["159915"]["buy"] == 0


@pytest.mark.parametrize(
    "initial_weight,quantities,stop_quantities",
    [
        (0.2, [20.0, 60.0, 40.0], [20.0, 20.0]),
        (0.0, [0.0, 80.0, 40.0], [0.0, 40.0]),
    ],
)
def test_partial_stop_t_plus_one_keeps_quantity_task_without_reviving_target(
    initial_weight, quantities, stop_quantities
):
    # First day only 20 old units; next opening buys 60, remaining defense leg
    # is suspended. ATR requests 40 but only the old 20 can be sold under T+1.
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(DAYS),
            "open": 10.0,
            "high": 11.0,
            "low": [9.0, 7.0, 7.0],
            "close": 10.0,
            "volume": 1000.0,
            "source": "synthetic-test-only",
            "adjust": "qfq",
        }
    )
    defense = df.copy()
    defense["suspended"] = [False, True, False]
    defense.loc[defense.suspended, "volume"] = 0.0
    t0 = stamp(DAYS[0] - timedelta(days=1))
    t1 = stamp(DAYS[0])
    targets = [
        Target(t0, {"159915": initial_weight}, "initial", t0),
        Target(t1, {"159915": 0.8, "563020": 0.2}, "partial", t1),
    ]
    receipts = []

    def provider(opening, history, state):
        if opening.date() in DAYS[1:]:
            return ProtectiveStop("159915", 8.0, 0.5, t1, "same-event")

    r = BacktestEngine().run(
        MarketData(
            {"159915": df, "563020": defense}, TradingCalendar(DAYS, "test-only", True)
        ),
        BacktestConfig(DAYS[0], DAYS[-1], 1000.0, 0.0, 0.0, enforce_t_plus_one=True),
        targets,
        stop_provider=provider,
        on_execution=receipts.append,
    )
    stops = [x for x in receipts if x["type"] == "stop"]
    assert stops[0]["status"] == "deferred_t_plus_one"
    assert [sum(t["quantity"] for t in x["trades"]) for x in stops] == stop_quantities
    assert list(r.curve.quantity_159915) == quantities
    assert len(cancelled(r)) == 1
    assert (
        cancelled(r)[0]["executed_quantity"]["159915"]["buy"]
        == 80.0 - initial_weight * 100
    )
    assert not any(
        t["side"] == "buy" and t["date"] == DAYS[2].isoformat() for t in r.trades
    )


def test_same_event_does_not_cancel_or_sell_twice_and_new_decision_can_enter():
    r, receipts, targets = scenario(repeated=True, new_entry=True)
    assert len(cancelled(r)) == 1
    stops = [x for x in receipts if x["type"] == "stop"]
    assert len(stops[0]["trades"]) == 1
    assert stops[1]["status"] == "already_executed" and stops[1]["trades"] == []
    assert targets[2].target_id != targets[1].target_id
    assert any(
        t["side"] == "buy" and t["reason"] == "new-weekly-decision" for t in r.trades
    )
    assert cancelled(r)[0]["target_id"] == targets[1].target_id
    assert not any(t["side"] == "buy" and t["reason"] == "old-target" for t in r.trades)


def test_restart_reloads_tombstone_and_audit_without_duplicate_fills(tmp_path):
    path = tmp_path / "execution.sqlite"
    before, _, targets = scenario(repeated=True, journal_path=path)
    with sqlite3.connect(path) as db:
        count = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    # New instance/new DB connection, full bound replay reconstructs the account.
    after, _, _ = scenario(repeated=True, journal_path=path)
    assert before.trades == after.trades
    assert before.orders == after.orders
    pd.testing.assert_frame_equal(before.curve, after.curve)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == count
    journal = ExecutionJournal(path)
    tombstone = journal.cancelled(
        targets[1].target_id, stamp(date(2024, 2, 1)).isoformat()
    )
    assert tombstone["target_status"] == "cancelled_atr"
    assert (
        journal.target_state(targets[1].target_id)["target_status"] == "cancelled_atr"
    )
    assert journal.rows("stop_submission")[0]["order_state"] == "submitted"
    journal.close()


def test_actual_process_restart_keeps_cancelled_target_and_ledger(tmp_path):
    script = (
        "import runpy,json,sys; "
        "h=runpy.run_path(sys.argv[1]); "
        "r,_,_=h['scenario'](journal_path=sys.argv[2],repeated=True); "
        "print(json.dumps({'trades':r.trades,'curve':r.curve.to_json(), 'cancelled':h['cancelled'](r)}))"
    )
    args = [
        sys.executable,
        "-c",
        script,
        str(Path(__file__).resolve()),
        str(tmp_path / "restart.sqlite"),
    ]
    first = subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)
    second = subprocess.run(
        args, check=True, capture_output=True, text=True, timeout=30
    )
    assert json.loads(first.stdout) == json.loads(second.stdout)


def test_restart_rejects_different_inputs_or_reused_id_with_changed_intent(tmp_path):
    path = tmp_path / "execution.sqlite"
    _, _, targets = scenario(journal_path=path)
    with pytest.raises(ValueError, match="审计冲突"):
        scenario(initial=0.6, gap=True, journal_path=path)
    journal = ExecutionJournal(path)
    old = targets[1]
    with pytest.raises(ValueError, match="审计冲突"):
        journal.register(
            Target(
                stamp(DAYS[2]),
                {"159915": 0.9},
                "different",
                stamp(DAYS[2]),
                target_id=old.target_id,
            )
        )
    journal.close()


def test_duplicate_cancellation_is_idempotent_and_does_not_overwrite_history(tmp_path):
    journal = ExecutionJournal(tmp_path / "events.sqlite")
    payload = {
        "target_id": "old",
        "target_status": "cancelled_atr",
        "invalidation_time": stamp(DAYS[1]).isoformat(),
    }
    assert journal.append("cancel", "old", payload)
    assert not journal.append("cancel", "old", payload)
    assert journal.rows("cancel") == [payload]
    with pytest.raises(ValueError, match="审计冲突"):
        journal.append("cancel", "old", {**payload, "target_status": "pending"})
    journal.close()


def test_before_after_same_inputs_explain_only_cancelled_target_trades():
    legacy = runpy.run_path(
        str(Path(__file__).parents[1] / "fixtures/b02_legacy_engine.py")
    )["BacktestEngine"]()
    old, _, _ = scenario(backend=legacy)
    new, _, _ = scenario()
    old_fills = [
        {
            k: v
            for k, v in t.items()
            if k not in ("stop_order_id", "stop_event_id", "target_id")
        }
        for t in old.trades
    ]
    new_fills = [
        {
            k: v
            for k, v in t.items()
            if k not in ("stop_order_id", "stop_event_id", "target_id")
        }
        for t in new.trades
    ]
    assert new_fills == old_fills[: len(new_fills)]
    assert old_fills[len(new_fills) :] and all(
        t["reason"] == "old-target" for t in old_fills[len(new_fills) :]
    )
    assert len(cancelled(new)) == 1 and not cancelled(old)
    for result in (old, new):
        for row in result.curve.itertuples():
            assert row.equity == pytest.approx(
                row.cash + row.quantity_159915 * 10 + row.quantity_563020 * 10
            )
    assert old.metrics["final_equity"] == new.metrics["final_equity"] == 920.0


def test_touching_line_does_not_expand_atr_trigger_or_cancel():
    r, _, _ = scenario(lows=[9.0, 8.0, 9.0])
    assert not cancelled(r)
    assert not any(
        t.get("execution_model") == "daily_ohlc_preset_stop" for t in r.trades
    )


def test_fees_slippage_and_equity_difference_are_explained_by_cancelled_old_target():
    legacy = runpy.run_path(
        str(Path(__file__).parents[1] / "fixtures/b02_legacy_engine.py")
    )["BacktestEngine"]()
    before, _, _ = scenario(backend=legacy, fee=0.001, slippage=0.002, final_close=11.0)
    after, _, _ = scenario(fee=0.001, slippage=0.002, final_close=11.0)
    assert before.metrics["fees"] > after.metrics["fees"]
    assert before.metrics["slippage_cost"] > after.metrics["slippage_cost"]
    assert before.metrics["final_equity"] != after.metrics["final_equity"]
    assert len(cancelled(after)) == 1
    assert all(
        t["reason"] == "old-target"
        for t in before.trades
        if t["date"] == DAYS[2].isoformat()
    )
    assert not any(t["date"] == DAYS[2].isoformat() for t in after.trades)
    for result in (before, after):
        row = result.curve.iloc[-1]
        assert row.equity == pytest.approx(
            row.cash + row.quantity_159915 * 11.0 + row.quantity_563020 * 10.0
        )
        assert result.metrics["fees"] == pytest.approx(
            sum(t["fee"] for t in result.trades)
        )
        assert result.metrics["slippage_cost"] == pytest.approx(
            sum(t["slippage_cost"] for t in result.trades)
        )


def test_replay_bridge_consumes_actual_cancel_without_confirming_partial_stage():
    from spear_shield.strategy.types import Position, Action

    helpers = runpy.run_path(
        str(Path(__file__).parents[1] / "strategy/test_replay_regressions.py")
    )
    bridge = helpers["replay"].__wrapped__()
    result, receipts, targets = scenario()
    old = targets[1]
    bridge.pending[old.reason] = helpers["decision"](
        Position(),
        DAYS[0].isoformat(),
        "ENTRY_FIRST",
        Action("entry", 0.5, stages=(1,)),
    )
    for event in receipts:
        bridge.execution(event)
    assert old.reason not in bridge.pending
    assert old.reason not in bridge.receipted
    assert bridge.position.stages == ()
    assert sum(lot["quantity"] for lot in bridge.lots) == 40.0
    assert bridge.cost == 400.0
    assert len([r for r in bridge.receipts if r["status"] == "cancelled_atr"]) == 1
    assert bridge.receipts[-1]["actual_fills"] == 1


@pytest.mark.parametrize("failure_kind", ["stop_submission", "receipt"])
def test_stop_submission_or_receipt_failure_aborts_without_reviving_target(
    tmp_path, monkeypatch, failure_kind
):
    path = tmp_path / "failure.sqlite"
    original = ExecutionJournal.append

    def fail(self, kind, key, payload):
        if kind == failure_kind and (
            kind != "receipt" or payload.get("type") == "stop"
        ):
            raise OSError("synthetic-test-only audit write failure")
        return original(self, kind, key, payload)

    monkeypatch.setattr(ExecutionJournal, "append", fail)
    with pytest.raises(OSError, match="write failure"):
        scenario(journal_path=path)
    journal = ExecutionJournal(path)
    assert len(journal.rows("cancel")) == 1
    assert not any(r["type"] == "stop" for r in journal.rows("receipt"))
    journal.close()
    monkeypatch.setattr(ExecutionJournal, "append", original)
    restored, _, _ = scenario(journal_path=path)
    assert restored.curve.iloc[-1].quantity_159915 == 40.0
    assert len(cancelled(restored)) == 1
