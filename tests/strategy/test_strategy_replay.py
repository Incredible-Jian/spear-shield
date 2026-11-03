"""合成证据验证完整成交闭环，不用于真实验收截图/收益报告。"""

from dataclasses import replace
from datetime import datetime, time
import numpy as np
import pandas as pd

from spear_shield.backtest.models import BacktestConfig, TradingCalendar
from spear_shield.backtest.strategy_replay import StrategyReplay
from spear_shield.services.research_dataset import OperationalDataset
from spear_shield.strategy.types import Evidence


def test_confirmed_first_entry_and_p0_are_executed_next_session_with_receipts():
    dates = pd.bdate_range("2010-01-04", periods=1800)
    prices = np.linspace(80, 100, len(dates))
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": prices,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": 1000.0,
            "source": "synthetic-test-only",
            "adjust": "qfq",
        }
    )
    cal = TradingCalendar(tuple(dates.date), "synthetic-calendar", True)
    dataset = OperationalDataset(
        frame, frame.copy(), cal, {}, {"test_only": True}, ["synthetic-test-only"]
    )
    count = [0]

    def controlled(snapshot, position):
        count[0] += 1
        facts = dict(snapshot.facts)
        values = {
            "week_slopes2": (-0.2, -0.2) if count[0] == 2 else (0.2, 0.2),
            "month_slopes2": (1.0, 1.0),
            "month_slope": 1.0,
            "week_close": 100.0,
            "week_ma60": 99.0,
            "week_ma10": 99.0,
            "effective_above_ma60": True,
            "bullish_week": True,
            "volume_pct52": 80.0,
            "risk_budget_pass": True,
            "stop_distance_pct": 1.0,
            "execution_cost_buffer_pct": 1.16,
            "margin_pct": 1.8,
            "zscore": 0.0,
            "defense_fuse": False,
            "week_return_pct": 0.0,
            "missed_first_nonbullish": False,
            "retest_ma60": False,
            "break_bear_rally_high": False,
            "max_week_drop_price": 0.0,
            "week_atr14": 1.0,
            "atr_stop_executed_this_week": False,
            "profit_pct": 0.0,
            "peak_profit_pct": 0.0,
            "post_entry_four_weeks": False,
            "second_top": False,
            "below_neckline": False,
            "rise_from_bottom_100": False,
            "six_of_eight_above_ma30": False,
            "volume_1_5": False,
            "rsi": 50.0,
        }
        for key, value in values.items():
            facts[key] = Evidence(
                value,
                "synthetic-test-only controlled evidence",
                snapshot.as_of,
                snapshot.as_of,
                snapshot.as_of,
            )
        return replace(snapshot, facts=facts, weekly_final=True)

    replay = StrategyReplay(
        dataset,
        {s: frame.copy() for s in ("159915", "563020", "511360", "511990")},
        snapshot_factory=controlled,
    )
    result = replay.run(
        BacktestConfig(dates[-30].date(), dates[-1].date(), fee_rate=0, slippage=0)
    )
    first = next(
        t for t in result.trades if t["symbol"] == "159915" and t["side"] == "buy"
    )
    clear = next(
        t for t in result.trades if t["symbol"] == "159915" and t["side"] == "sell"
    )
    assert pd.Timestamp(first["date"]).date() > pd.Timestamp(first["signal_at"]).date()
    assert pd.Timestamp(clear["date"]).date() > pd.Timestamp(clear["signal_at"]).date()
    assert any(a["selected"] == "ENTRY_FIRST" for a in replay.audit)
    assert any(a["selected"] == "P0_TREND" for a in replay.audit)
    assert any(r["stages"] == (1,) for r in replay.receipts)
    assert result.metadata["complete_strategy_validated"] is False
    assert result.metadata["attack_trade_count"] >= 2
