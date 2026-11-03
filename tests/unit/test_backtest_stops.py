"""合成日OHLC预置止损及实际成交回执，不代表分钟级成交。"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from spear_shield.backtest.engine import BacktestEngine
from spear_shield.backtest.models import (
    BacktestConfig,
    CorporateAction,
    MarketData,
    ProtectiveStop,
    ProtectedStop,
    Target,
    TradingCalendar,
)

SH = ZoneInfo("Asia/Shanghai")
DAYS = (date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9))


def at(day, hour=15, minute=30):
    return datetime.combine(day, time(hour, minute), SH)


def frame(opens=(10, 10, 10), lows=None, suspended=None, adjust="qfq"):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(DAYS),
            "open": opens,
            "high": opens,
            "low": opens if lows is None else lows,
            "close": opens,
            "volume": [0 if x else 1000 for x in (suspended or [False] * 3)],
            "suspended": suspended or [False] * 3,
            "source": "synthetic-test-only",
            "adjust": adjust,
        }
    )


def market(df=None, **kwargs):
    return MarketData(
        {"159915": frame() if df is None else df},
        TradingCalendar(DAYS, "test-only", True),
        **kwargs
    )


def config(**kwargs):
    return BacktestConfig(DAYS[0], DAYS[-1], 1000, fee_rate=0, slippage=0, **kwargs)


def target(day=None, weights=None):
    stamp = at(day or date(2024, 1, 4))
    return Target(stamp, {"159915": 1} if weights is None else weights, "target", stamp)


def preset(day=DAYS[1], fraction=1, trigger=9):
    def provider(opening, history, state):
        if opening.date() == day:
            return ProtectiveStop(
                "159915", trigger, fraction, opening - timedelta(days=1), "preset"
            )

    return provider


@pytest.mark.parametrize("opening,low,expected", [(8, 7, 8), (10, 8, 9)])
def test_gapdown_and_intraday_cross_use_fixed_line_not_future_low(
    opening, low, expected
):
    receipts = []
    cfg = replace(config(), slippage=0.01, fee_rate=0.001)
    result = BacktestEngine().run(
        market(frame((10, opening, 10), (10, low, 10))),
        cfg,
        [target()],
        stop_provider=preset(),
        on_execution=receipts.append,
    )
    buy, sell = result.trades
    assert sell["price"] == pytest.approx(expected * 0.99)
    assert sell["date"] == DAYS[1].isoformat()
    assert sell["execution_model"] == "daily_ohlc_preset_stop"
    assert "execution_at" not in sell  # 不伪造分钟
    stop_receipt = receipts[-1]
    assert stop_receipt["event"] == "stop" and stop_receipt["completed"]
    assert stop_receipt["type"] == "stop" and stop_receipt["target"] is None
    assert stop_receipt["date"] == DAYS[1]
    assert stop_receipt["trades"] == [sell]
    assert stop_receipt["state"]["qty"]["159915"] == 0
    assert stop_receipt["state"]["cost"]["159915"] == pytest.approx(0)
    assert stop_receipt["state"]["prices"]["159915"] == sell["price"]
    assert stop_receipt["prices"]["159915"] == sell["price"]
    assert receipts[0]["prices"]["159915"] == buy["price"]
    assert sell["realized_pnl"] == pytest.approx(
        sell["quantity"] * sell["price"]
        - sell["fee"]
        - buy["quantity"] * buy["price"]
        - buy["fee"]
    )
    assert result.curve.iloc[1].cash == pytest.approx(stop_receipt["state"]["cash"])


@pytest.mark.parametrize("low", [9, 9.5])
def test_untouched_or_equal_line_does_not_trigger(low):
    receipts = []
    result = BacktestEngine().run(
        market(frame(lows=(10, low, 10))),
        config(),
        [target()],
        stop_provider=preset(),
        on_execution=receipts.append,
    )
    assert len(result.trades) == 1
    assert receipts[-1]["status"] == "not_triggered"
    assert receipts[-1]["trades"] == []


@pytest.mark.parametrize("offset", [0, 1, 3600])
def test_equal_open_or_future_known_at_is_rejected_before_target_fills(offset):
    receipts = []

    def provider(opening, history, state):
        return ProtectiveStop(
            "159915", 9, 1, opening + timedelta(seconds=offset), "invalid"
        )

    with pytest.raises(ValueError, match="严格早于"):
        BacktestEngine().run(
            market(),
            config(),
            [target()],
            stop_provider=provider,
            on_execution=receipts.append,
        )
    assert receipts == []


def test_provider_only_sees_previous_history_and_copies_of_open_state():
    seen = []

    def provider(opening, history, state):
        seen.append(len(history["159915"]))
        assert (history["159915"].date < opening.date()).all()
        assert not {"high", "low", "close"} & state.keys()
        assert state["open"]["159915"] == 10
        assert state["prices"]["159915"] == 10
        if opening.date() == DAYS[0]:
            assert state["qty"]["159915"] == 0  # 在开盘目标之前
        state["qty"]["159915"] = 9999
        state["cost"]["159915"] = 9999
        state["open"]["159915"] = 9999
        history["159915"].loc[:, "open"] = 9999
        return preset()(opening, history, state)

    result = BacktestEngine().run(
        market(frame(lows=(10, 8, 10))), config(), [target()], stop_provider=provider
    )
    assert seen == [0, 1, 2]
    assert [t["price"] for t in result.trades] == [10, 9]


@pytest.mark.parametrize("enforce,expected_sells", [(False, 1), (True, 0)])
def test_t_plus_one_blocks_same_day_new_buys(enforce, expected_sells):
    receipts = []
    result = BacktestEngine().run(
        market(frame(lows=(8, 10, 10))),
        config(enforce_t_plus_one=enforce),
        [target()],
        stop_provider=preset(day=DAYS[0]),
        on_execution=receipts.append,
    )
    assert sum(t["side"] == "sell" for t in result.trades) == expected_sells
    if enforce:
        assert receipts[-1]["status"] == "deferred_t_plus_one"
        assert not receipts[-1]["completed"] and receipts[-1]["trades"] == []
        assert result.curve.quantity_159915.tolist() == [100, 100, 100]


def test_t_plus_one_can_sell_old_shares_but_not_today_top_up():
    receipts = []
    result = BacktestEngine().run(
        market(frame(lows=(10, 8, 10))),
        config(enforce_t_plus_one=True),
        [target(weights={"159915": 0.5}), target(DAYS[0])],
        stop_provider=preset(),
        on_execution=receipts.append,
    )
    assert [(t["side"], t["quantity"]) for t in result.trades] == [
        ("buy", 50),
        ("buy", 50),
        ("sell", 50),
    ]
    assert receipts[-1]["status"] == "deferred_t_plus_one"
    assert receipts[-1]["state"]["qty"]["159915"] == 50
    assert receipts[-1]["state"]["cost"]["159915"] == 500


def test_provider_controls_reissue_no_engine_weekly_deduplication():
    def provider(opening, history, state):
        return ProtectiveStop("159915", 9, 0.5, opening - timedelta(days=1), "repeat")

    result = BacktestEngine().run(
        market(frame(lows=(8, 8, 8))), config(), [target()], stop_provider=provider
    )
    assert [t["quantity"] for t in result.trades] == [100, 50, 25, 12]


def test_stop_suspension_never_fills_or_retries_without_provider():
    receipts = []
    result = BacktestEngine().run(
        market(frame(lows=(10, 8, 8), suspended=[False, True, False])),
        config(),
        [target()],
        stop_provider=preset(),
        on_execution=receipts.append,
    )
    assert len(result.trades) == 1
    assert receipts[-1]["status"] == "deferred_suspension"
    assert not receipts[-1]["completed"]


def test_actual_partial_target_receipts_and_cumulative_fills():
    receipts = []
    data = MarketData(
        {"159915": frame(), "563020": frame(suspended=[True, False, False])},
        TradingCalendar(DAYS, "test"),
    )
    t = target(weights={"159915": 0.5, "563020": 0.5})
    result = BacktestEngine().run(data, config(), [t], on_execution=receipts.append)
    first, second = receipts
    assert first["target"] is t and first["day"] == DAYS[0]
    assert first["type"] == "target" and first["date"] == DAYS[0]
    assert not first["completed"] and first["status"] == "pending"
    assert first["deferred"][0]["status"] == "deferred_suspension"
    assert [x["symbol"] for x in first["trades"]] == ["159915"]
    assert first["state"]["qty"] == {"159915": 50, "563020": 0}
    assert first["state"]["cash"] == 500
    assert first["state"]["cost"] == {"159915": 500, "563020": 0}
    assert first["quantities"] == first["state"]["qty"]
    assert first["costs"] == first["state"]["cost"]
    assert first["cash"] == first["state"]["cash"]
    assert second["completed"] and second["trades"] == result.trades[1:]
    assert second["target_trades"] == result.trades
    assert not {"close", "low", "high"} & first["state"].keys()


def test_receipt_mutation_does_not_modify_engine_or_cumulative_trades():
    def receipt(r):
        if r["trades"]:
            r["trades"][0]["quantity"] = 9999
            r["target_trades"][0]["price"] = 9999
        r["state"]["qty"]["159915"] = 9999
        r["state"]["cost"]["159915"] = 9999

    result = BacktestEngine().run(market(), config(), [target()], on_execution=receipt)
    assert result.trades[0]["quantity"] == 100
    assert result.trades[0]["price"] == 10
    assert result.curve.quantity_159915.tolist() == [100, 100, 100]


@pytest.mark.parametrize("fraction,expected", [(0.5, 0), (1, 150)])
def test_stop_lot_rounding_and_split_residual_full_liquidation(fraction, expected):
    event = CorporateAction("159915", DAYS[1], DAYS[1], 0, 1.5, "test-split")
    result = BacktestEngine().run(
        market(
            frame((10, 7, 7), (10, 6, 7), adjust="none"),
            actions=(event,),
            actions_coverage="test full",
        ),
        config(mode="raw_events", lot_size=100),
        [target()],
        stop_provider=preset(fraction=fraction),
    )
    sells = [t for t in result.trades if t["side"] == "sell"]
    assert sum(t["quantity"] for t in sells) == expected
    assert result.curve.iloc[1].quantity_159915 == 150 - expected


def test_stop_dividend_entitlement_cost_and_receivable_keep_existing_accounting():
    event = CorporateAction("159915", DAYS[1], DAYS[2], 1, source="test-dividend")
    receipts = []
    result = BacktestEngine().run(
        market(
            frame((10, 9, 9), (10, 8, 9), adjust="none"),
            actions=(event,),
            actions_coverage="test full",
        ),
        config(mode="raw_events"),
        [target()],
        stop_provider=preset(),
        on_execution=receipts.append,
    )
    sell = result.trades[-1]
    assert sell["realized_price_pnl"] == -100
    assert sell["dividend_pnl"] == 100 and sell["realized_pnl"] == 0
    assert receipts[-1]["state"]["receivable"] == 100
    assert result.curve.equity.tolist() == [1000, 1000, 1000]
    assert result.curve.cash.tolist() == [0, 900, 1000]


def test_no_fill_completion_does_not_claim_actual_trade_and_end_is_reported():
    receipts = []
    result = BacktestEngine().run(
        market(), config(lot_size=1000), [target()], on_execution=receipts.append
    )
    assert receipts[0]["completed"] and receipts[0]["trades"] == result.trades == []
    receipts.clear()
    BacktestEngine().run(
        market(), config(), [target(DAYS[-1])], on_execution=receipts.append
    )
    assert receipts[-1]["status"] == "unfilled_end"
    assert not receipts[-1]["completed"] and not receipts[-1]["trades"]


@pytest.mark.parametrize("symbol", ["563020", "511360", "511990"])
def test_stop_contract_only_accepts_159915(symbol):
    with pytest.raises(ValueError, match="仅159915"):
        ProtectiveStop(symbol, 9, 1, at(DAYS[0]), "test")


@pytest.mark.parametrize(
    "change",
    [
        {"trigger_price": 0},
        {"trigger_price": float("nan")},
        {"fraction": 0},
        {"fraction": 1.1},
        {"fraction": float("inf")},
        {"known_at": datetime(2024, 1, 4)},
        {"reason": ""},
    ],
)
def test_invalid_stop_contract(change):
    values = dict(
        symbol="159915",
        trigger_price=9,
        fraction=1,
        known_at=at(DAYS[0]),
        reason="test",
    )
    values.update(change)
    with pytest.raises(ValueError):
        ProtectiveStop(**values)
    assert ProtectedStop is ProtectiveStop
