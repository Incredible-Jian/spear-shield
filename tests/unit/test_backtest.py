"""回测测试行情仅用于手算验证，不作为真实市场数据。"""

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from spear_shield.backtest import (
    BacktestConfig,
    BacktestEngine,
    CorporateAction,
    MarketData,
    Target,
    TradingCalendar,
)
from spear_shield.backtest.metrics import performance
from spear_shield.backtest.research import (
    replay_decisions,
    run_benchmarks,
    result_payload,
)
from spear_shield.backtest.reporting import persist_report, export_bundle
from spear_shield.strategy.types import Snapshot

SH = ZoneInfo("Asia/Shanghai")
DAYS = (date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9))


def at(day, hour=15, minute=30):
    return datetime.combine(day, datetime.min.time(), SH).replace(
        hour=hour, minute=minute
    )


def frame(prices=(10.0, 12.0, 13.0), adjust="qfq", days=DAYS):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(days),
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": 1000.0,
            "source": "synthetic-test-only",
            "adjust": adjust,
        }
    )


def market(df=None, **kw):
    return MarketData(
        {"159915": frame() if df is None else df},
        TradingCalendar(DAYS, "test-only", True),
        **kw
    )


def cfg(**kw):
    return BacktestConfig(DAYS[0], DAYS[-1], 1000.0, fee_rate=0, slippage=0, **kw)


def initial(weights=None):
    t = at(date(2024, 1, 4))
    return Target(t, weights or {"159915": 1}, "test-only predeclared benchmark", t)


def test_friday_signal_executes_monday_open_not_friday_close():
    t = at(DAYS[0])
    result = BacktestEngine().run(
        market(), cfg(), [Target(t, {"159915": 1}, "test-only", t)]
    )
    assert result.trades[0]["date"] == "2024-01-08"
    assert result.trades[0]["price"] == 12
    assert (
        result.curve.iloc[0].equity == 1000
        and result.curve.iloc[0].quantity_159915 == 0
    )
    assert result.curve.iloc[-1].equity == 1083


def test_callback_cannot_see_future_and_final_signal_cannot_fill():
    seen = []

    def callback(t, history, row):
        seen.append(history["159915"].date.max())
        assert history["159915"].date.max() == t.date()
        # Mutating the provided copy must not poison execution prices.
        history["159915"].loc[:, "open"] = 999
        return Target(t, {"159915": 1}, "test-only", t)

    result = BacktestEngine().run(market(), cfg(), on_close=callback)
    assert seen == list(DAYS)
    assert result.trades[0]["price"] == 12
    assert result.orders[-1]["status"] == "unfilled_end"


def test_future_price_change_does_not_change_earlier_trades_or_nav():
    a = BacktestEngine().run(market(), cfg(), [initial()])
    b = BacktestEngine().run(market(frame((10, 12, 999))), cfg(), [initial()])
    assert a.trades == b.trades
    pd.testing.assert_frame_equal(a.curve.iloc[:2], b.curve.iloc[:2])


def test_fees_slippage_budget_and_drawdown_include_initial_cost():
    config = replace(cfg(), fee_rate=0.01, slippage=0.01)
    result = BacktestEngine().run(market(frame((10, 10, 10))), config, [initial()])
    trade = result.trades[0]
    assert trade["quantity"] == 98 and trade["price"] == 10.1
    assert trade["fee"] == pytest.approx(9.898)
    assert result.curve.iloc[0].cash == pytest.approx(0.302)
    assert result.metrics["max_drawdown"] == pytest.approx(-0.019698)
    assert (result.curve.cash >= 0).all()
    assert result.metrics["win_rate"] is None  # 无卖出不伪造胜率


def test_sell_before_buy_and_proportional_buy_budget():
    bars = {"159915": frame((10, 10, 10)), "563020": frame((10, 10, 10))}
    t = at(DAYS[0])
    result = BacktestEngine().run(
        MarketData(bars, TradingCalendar(DAYS, "test")),
        cfg(),
        [initial(), Target(t, {"563020": 1}, "rotate-test", t)],
    )
    assert [x["side"] for x in result.trades] == ["buy", "sell", "buy"]
    assert result.trades[1]["realized_pnl"] == 0
    assert result.curve.iloc[-1].weight_563020 == 1
    balanced = BacktestEngine().run(
        MarketData(bars, TradingCalendar(DAYS, "test")),
        replace(cfg(), fee_rate=0.1),
        [initial({"159915": 0.5, "563020": 0.5})],
    )
    assert [t["quantity"] for t in balanced.trades] == [45, 45]


def test_suspension_is_explicit_and_order_defers_until_open():
    df = frame()
    df["suspended"] = [True, False, False]
    df.loc[0, "volume"] = 0
    result = BacktestEngine().run(market(df), cfg(), [initial()])
    assert result.trades[0]["date"] == "2024-01-08"
    assert any(o["status"] == "deferred_suspension" for o in result.orders)
    missing = frame().drop(index=1)
    with pytest.raises(ValueError, match="交易日缺失"):
        BacktestEngine().run(market(missing), cfg(), [initial()])


def test_last_day_unfilled_is_reported_not_forced_at_close():
    t = at(DAYS[-1])
    result = BacktestEngine().run(
        market(), cfg(), [Target(t, {"159915": 1}, "last", t)]
    )
    assert result.trades == []
    assert result.orders[-1]["status"] == "unfilled_end"
    assert result.metrics["total_return"] == 0


def test_raw_dividend_receivable_then_payment_no_phantom_loss():
    # Buy 100@10 before ex-date; ex-price9 + dividend receivable100 =1000 equity.
    df = frame((10, 9, 9), "none")
    event = CorporateAction("159915", DAYS[1], DAYS[2], 1, source="test-dividend")
    result = BacktestEngine().run(
        market(df, actions=(event,), actions_coverage="test period full"),
        cfg(mode="raw_events"),
        [initial()],
    )
    assert result.curve.equity.tolist() == [1000, 1000, 1000]
    assert result.curve.receivable.tolist() == [0, 100, 0]
    assert result.curve.iloc[-1].cash == 100


def test_raw_split_preserves_cost_and_quantity_and_ex_date_buyer_gets_no_dividend():
    event = CorporateAction("159915", DAYS[1], DAYS[2], 1, 2, "test-action")
    result = BacktestEngine().run(
        market(
            frame((10, 4.5, 4.5), "none"),
            actions=(event,),
            actions_coverage="test full",
        ),
        cfg(mode="raw_events"),
        [initial()],
    )
    assert result.curve.quantity_159915.tolist() == [100, 200, 200]
    assert result.curve.equity.tolist() == [1000, 1000, 1000]
    t = at(DAYS[0])
    late = BacktestEngine().run(
        market(
            frame((10, 4.5, 4.5), "none"),
            actions=(event,),
            actions_coverage="test full",
        ),
        cfg(mode="raw_events"),
        [Target(t, {"159915": 1}, "ex-date buyer", t)],
    )
    assert late.curve.receivable.sum() == 0


def test_receivable_after_end_is_equity_but_not_spendable_cash():
    event = CorporateAction("159915", DAYS[1], date(2024, 1, 20), 1, source="test")
    result = BacktestEngine().run(
        market(frame((10, 9, 9), "none"), actions=(event,), actions_coverage="test"),
        cfg(mode="raw_events"),
        [initial()],
    )
    assert result.curve.iloc[-1].cash == 0
    assert result.curve.iloc[-1].receivable == 100


@pytest.mark.parametrize(
    "change",
    [
        "nan",
        "duplicate",
        "negative",
        "bad_high",
        "wrong_adjust",
        "missing_source",
        "zero_volume",
    ],
)
def test_bad_data_never_silently_filled(change):
    df = frame()
    if change == "nan":
        df.loc[0, "open"] = float("nan")
    if change == "duplicate":
        df.loc[1, "date"] = df.loc[0, "date"]
    if change == "negative":
        df.loc[1, "close"] = -1
    if change == "bad_high":
        df.loc[1, "high"] = 1
    if change == "wrong_adjust":
        df.loc[1, "adjust"] = "none"
    if change == "missing_source":
        df.loc[1, "source"] = ""
    if change == "zero_volume":
        df.loc[1, "volume"] = 0
    with pytest.raises(ValueError):
        BacktestEngine().run(market(df), cfg(), [initial()])


def test_raw_requires_calendar_and_actions_and_qfq_rejects_double_dividend():
    with pytest.raises(ValueError, match="覆盖声明"):
        BacktestEngine().run(market(frame(adjust="none")), cfg(mode="raw_events"))
    event = CorporateAction("159915", DAYS[1], DAYS[2], 1, source="test")
    with pytest.raises(ValueError, match="禁止再叠加"):
        BacktestEngine().run(market(actions=(event,)), cfg())


def test_signal_future_evidence_and_overweight_are_rejected():
    with pytest.raises(ValueError, match="未来证据"):
        Target(at(DAYS[0]), {"159915": 1}, "test", at(DAYS[1]))
    with pytest.raises(ValueError, match="100%"):
        initial({"159915": 0.8, "563020": 0.8})
    with pytest.raises(ValueError, match="同日"):
        t = at(DAYS[0], 9, 0)
        BacktestEngine().run(market(), cfg(), [Target(t, {"159915": 1}, "test", t)])


def test_metrics_hand_values_wins_losses_and_drawdown():
    curve = pd.DataFrame({"date": pd.to_datetime(DAYS), "equity": [1100, 880, 990]})
    m = performance(
        curve,
        [
            {"side": "sell", "realized_pnl": p, "fee": 1, "slippage_cost": 2}
            for p in (20, -10, 0)
        ],
        1000,
    )
    assert m["total_return"] == pytest.approx(-0.01)
    assert m["max_drawdown"] == pytest.approx(-0.2)
    assert m["win_rate"] == pytest.approx(1 / 3) and m["payoff_ratio"] == 2
    assert m["trade_count"] == 3


def test_missing_full_strategy_is_blocked_not_flat_zero_performance():
    class Workspace:
        def history(self, code, adjust):
            return frame() if code == "159915" else frame().iloc[:0]

    runs = run_benchmarks(Workspace(), cfg())
    assert runs[0]["status"] == "blocked" and runs[0]["result"] is None
    assert runs[1]["status"] == "research_only" and runs[2]["status"] == "blocked"
    assert "行情缺失" in runs[2]["blockers"][0]


def test_decision_replay_does_not_forge_positions_or_accept_reverse_time():
    snapshots = [Snapshot(at(d), weekly_final=True) for d in DAYS]
    decisions = replay_decisions(snapshots)
    assert all(d.status == "blocked" and d.selected is None for d in decisions)
    with pytest.raises(ValueError, match="升序"):
        replay_decisions(snapshots[::-1])


def test_report_persists_all_evidence_and_escapes_csv_formula(tmp_path):
    result = BacktestEngine().run(market(), cfg(), [initial()])
    result.trades[0]["reason"] = "=TEST()"
    payload = {
        "generated_at": at(DAYS[-1]).isoformat(),
        "request": {"fee_rate": 0},
        "runs": [
            {
                "name": "test-only",
                "status": "research_only",
                "blockers": [],
                "result": result_payload(result),
            }
        ],
    }
    folder = persist_report(payload, tmp_path / "report")
    assert "'=TEST()" in (folder / "0_trades.csv").read_text(encoding="utf-8-sig")
    assert (folder / "SHA256.txt").is_file()
    import hashlib

    assert (
        hashlib.sha256((folder / "report.json").read_bytes()).hexdigest()
        == (folder / "SHA256.txt").read_text().split()[0]
    )
    export_bundle(folder, tmp_path / "report.zip")
    from zipfile import ZipFile

    with ZipFile(tmp_path / "report.zip") as archive:
        assert (
            "report.json" in archive.namelist() and "0_curve.csv" in archive.namelist()
        )


def test_signal_weights_are_frozen_even_if_original_dict_changes():
    weights = {"159915": 1.0}
    t = at(date(2024, 1, 4))
    target = Target(t, weights, "test-only", t)
    weights["159915"] = 0
    with pytest.raises(TypeError):
        target.weights["159915"] = 0
    result = BacktestEngine().run(market(), cfg(), [target])
    assert result.trades[0]["quantity"] == 100


def test_external_target_then_newer_callback_does_not_reverse_time():
    old = Target(at(DAYS[0]), {"159915": 1}, "old", at(DAYS[0]))

    def callback(t, history, row):
        if t.date() == DAYS[0]:
            # 同一时间冲突不可静默选一个。
            return Target(t, {"159915": 0}, "same-time-conflict", t)

    with pytest.raises(ValueError, match="同一时点"):
        BacktestEngine().run(market(), cfg(), [old], on_close=callback)
    older = Target(
        at(DAYS[0], 15, 0).replace(hour=15, minute=30),
        {"159915": 1},
        "old",
        at(DAYS[0]),
    )

    def later(t, history, row):
        if t.date() == DAYS[1]:
            return Target(t, {"159915": 0}, "new", t)

    result = BacktestEngine().run(market(), cfg(), [older], on_close=later)
    assert result.trades[-1]["side"] == "sell"


def test_dividend_enters_closed_trade_win_rate():
    days = (*DAYS, date(2024, 1, 10))
    df = frame((10, 10, 9, 9), "none", days)
    event = CorporateAction("159915", DAYS[2], days[3], 2, source="test")
    data = MarketData(
        {"159915": df}, TradingCalendar(days, "test", True), (event,), "test full"
    )
    t = at(DAYS[2])
    result = BacktestEngine().run(
        data,
        replace(cfg(mode="raw_events"), end=days[-1]),
        [initial(), Target(t, {"159915": 0}, "close-test", t)],
    )
    assert result.metrics["total_return"] == pytest.approx(0.1)
    assert result.trades[-1]["realized_price_pnl"] == -100
    assert result.trades[-1]["dividend_pnl"] == 200
    assert result.trades[-1]["realized_pnl"] == 100
    assert result.metrics["win_rate"] == 1


def test_short_period_annualization_is_unavailable_and_future_signals_excluded():
    t = at(date(2024, 1, 20))
    result = BacktestEngine().run(
        market(), cfg(), [Target(t, {"159915": 1}, "future", t)]
    )
    assert result.metrics["annual_return"] is None
    assert result.signals == [] and result.trades == []


def test_split_odd_lot_partial_sale_rounds_down_but_full_close_allowed():
    event = CorporateAction("159915", DAYS[1], DAYS[1], 0, 1.5, "test-split")
    data = market(
        frame((10, 10 / 1.5, 10 / 1.5), "none"),
        actions=(event,),
        actions_coverage="test full",
    )
    t = at(DAYS[0])
    result = BacktestEngine().run(
        data,
        replace(cfg(mode="raw_events"), lot_size=100),
        [initial(), Target(t, {"159915": 2 / 3}, "partial-test", t)],
    )
    assert len(result.trades) == 1 and result.curve.iloc[-1].quantity_159915 == 150
    cleared = BacktestEngine().run(
        data,
        replace(cfg(mode="raw_events"), lot_size=100),
        [initial(), Target(t, {"159915": 0}, "close-test", t)],
    )
    assert cleared.trades[-1]["quantity"] == 150


def test_common_missing_date_boundaries_are_explicit_partial_research():
    class Workspace:
        def history(self, code, adjust):
            return frame() if code == "159915" else frame().iloc[:0]

    config = replace(cfg(), start=date(2015, 1, 1), end=date(2026, 11, 3))
    run = run_benchmarks(Workspace(), config, selection="attack")[0]
    assert run["status"] == "partial_research"
    assert "2015-01-01" in run["blockers"][0] and "2024-01-05" in run["blockers"][0]
    assert "仅部分" in run["blockers"][0]


def test_report_compatible_without_dataframe_map(tmp_path, monkeypatch):
    monkeypatch.delattr(pd.DataFrame, "map")
    result = BacktestEngine().run(market(), cfg(), [initial()])
    payload = {
        "generated_at": at(DAYS[-1]).isoformat(),
        "request": {},
        "runs": [
            {
                "name": "test-only",
                "status": "research_only",
                "blockers": [],
                "result": result_payload(result),
            }
        ],
    }
    folder = persist_report(payload, tmp_path / "pandas20-report")
    assert (folder / "0_curve.csv").is_file()
