"""B02诊断证据：断言缺陷的实际因果链，不代表允许重买或修复验收通过。

禁止重买的不变量仍由原有 strict xfail 测试保留；本文件不替换其预期。
全部行情为隔离的三日合成数据，不连接任何交易或行情服务。
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import runpy
from pathlib import Path

from spear_shield.backtest import (
    BacktestConfig,
    BacktestEngine,
    MarketData,
    ProtectiveStop,
    Target,
    TradingCalendar,
)

SH = ZoneInfo("Asia/Shanghai")
SAME_WEEK = (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))
CROSS_WEEK = (date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8))


@pytest.fixture(autouse=True)
def frozen_before_fix_engine(monkeypatch):
    """Keep original defect assertions as historical diagnosis; safety tests use production."""
    legacy = runpy.run_path(
        str(Path(__file__).parents[1] / "fixtures/b02_legacy_engine.py")
    )
    monkeypatch.setitem(globals(), "BacktestEngine", legacy["BacktestEngine"])


def run_scenario(
    days=SAME_WEEK,
    *,
    defer_defense=True,
    trigger_stop=True,
    starting_weights=None,
    old_weights=None,
):
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(days),
            "open": 10.0,
            "high": 11.0,
            "low": [9.0, 7.0 if trigger_stop else 9.0, 9.0],
            "close": 10.0,
            "volume": 1000.0,
            "source": "synthetic-test-only-B02-diagnosis",
            "adjust": "qfq",
        }
    )
    defense = frame.copy()
    defense["suspended"] = [False, defer_defense, False]
    defense.loc[defense.suspended, "volume"] = 0.0
    at = lambda day: datetime.combine(day, time(15, 30), SH)
    initial_at, old_at = at(days[0] - timedelta(days=1)), at(days[0])
    targets = (
        Target(initial_at, starting_weights or {"159915": 1.0}, "initial", initial_at),
        Target(
            old_at, old_weights or {"159915": 0.8, "563020": 0.2}, "old-mixed", old_at
        ),
    )
    receipts = []

    def stop_provider(opening, history, state):
        if opening.date() == days[1]:
            return ProtectiveStop("159915", 8.0, 0.5, old_at, "synthetic-ATR")
        return None

    result = BacktestEngine().run(
        MarketData(
            {"159915": frame, "563020": defense},
            TradingCalendar(days, "synthetic-test-only-B02-diagnosis", True),
        ),
        BacktestConfig(days[0], days[-1], 1000.0, 0.0, 0.0, enforce_t_plus_one=True),
        targets,
        stop_provider=stop_provider,
        on_execution=receipts.append,
    )
    return result, receipts


@pytest.mark.parametrize(
    "days", [SAME_WEEK, CROSS_WEEK], ids=["same-week", "cross-week"]
)
def test_diagnosis_stale_target_rebuys_after_actual_stop_without_new_signal(days):
    result, receipts = run_scenario(days)
    assert list(result.curve.quantity_159915) == [100.0, 40.0, 73.0]
    pending = next(
        r for r in receipts if r["date"] == days[1] and r["type"] == "target"
    )
    stop = next(r for r in receipts if r["type"] == "stop")
    retried = next(
        r for r in receipts if r["date"] == days[2] and r["type"] == "target"
    )
    assert pending["status"] == "pending" and not pending["completed"]
    assert pending["deferred"][0]["status"] == "deferred_suspension"
    assert pending["quantities"]["159915"] == 80.0
    assert stop["target"] is None and stop["completed"]
    assert stop["quantities"]["159915"] == 40.0
    assert [(t["side"], t["quantity"], t["price"]) for t in stop["trades"]] == [
        ("sell", 40.0, 8.0)
    ]
    assert retried["target"] is pending["target"]
    assert retried["target"].weights["159915"] == 0.8
    assert retried["completed"] and retried["quantities"]["159915"] == 73.0
    assert [(t["symbol"], t["side"], t["quantity"]) for t in retried["trades"]] == [
        ("159915", "buy", 33.0),
        ("563020", "buy", 18.0),
    ]
    # 最后成交仍引用旧信号；ATR卖出没有进入旧目标自己的累计成交。
    assert all(
        t["signal_at"] == pending["target"].signal_at.isoformat()
        for t in retried["trades"]
    )
    assert len(retried["target_trades"]) == 3
    assert all(t["reason"] == "old-mixed" for t in retried["target_trades"])
    assert len(result.signals) == 2
    assert not any(r["status"] == "superseded" for r in receipts)
    assert result.metrics["final_equity"] == pytest.approx(920.0)


@pytest.mark.parametrize(
    "defer_defense,trigger_stop,end_attack",
    [(False, True, 40.0), (True, False, 80.0)],
    ids=["no-pending-target", "no-stop-fill"],
)
def test_diagnosis_removing_either_cause_removes_attack_rebuy(
    defer_defense, trigger_stop, end_attack
):
    result, receipts = run_scenario(
        defer_defense=defer_defense, trigger_stop=trigger_stop
    )
    assert result.curve.iloc[-1].quantity_159915 == end_attack
    assert not any(
        t["date"] == SAME_WEEK[-1].isoformat()
        and t["symbol"] == "159915"
        and t["side"] == "buy"
        for t in result.trades
    )
    stop = next(r for r in receipts if r["type"] == "stop")
    assert bool(stop["trades"]) is trigger_stop


def test_diagnosis_attack_only_target_also_rebuys_if_existing_defense_sale_is_delayed():
    # 与StrategyReplay.close正进攻目标相同的权重形状：未列资产目标隐含为0。
    # 不调用策略生成器，不声称此合成持仓已通过其建仓滤网。
    result, receipts = run_scenario(
        starting_weights={"159915": 0.5, "563020": 0.5},
        old_weights={"159915": 0.8},
    )
    assert list(result.curve.quantity_159915) == [50.0, 25.0, 76.0]
    assert list(result.curve.quantity_563020) == [50.0, 50.0, 0.0]
    target = next(
        r for r in receipts if r["date"] == SAME_WEEK[1] and r["type"] == "target"
    )
    stop = next(r for r in receipts if r["type"] == "stop")
    retried = receipts[-1]
    assert target["status"] == "pending" and target["trades"] == []
    assert dict(target["target"].weights) == {"159915": 0.8}
    assert stop["trades"][0]["quantity"] == 25.0
    assert retried["target"] is target["target"]
    assert any(
        t["side"] == "buy" and t["symbol"] == "159915" and t["quantity"] == 51.0
        for t in retried["trades"]
    )
    assert len(result.signals) == 2
    assert result.metrics["final_equity"] == pytest.approx(950.0)
