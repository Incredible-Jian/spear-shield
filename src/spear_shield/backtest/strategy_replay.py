"""Phase4规则到实际模拟成交的回放桥；完整性与资金曲线分别报告。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time
import json
from math import isfinite
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from .engine import BacktestEngine
from .models import MarketData, Target, ProtectiveStop
from ..strategy.engine import StrategyEngine
from ..strategy.features import (
    build_operational_snapshot,
    settled_bars,
    complete_segment_indicators,
)
from ..strategy.operational import operational_policy, DEFINITION_VERSION
from ..strategy.defense import defense_plan
from ..strategy.macro import thermometer
from ..strategy.types import Position, Status
from ..strategy.rules import exit_rules
from ..portfolio.state import observe_month, confirm_execution
from ..indicators.engine import IndicatorEngine

SH = ZoneInfo("Asia/Shanghai")


class StrategyReplay:
    """预热数据独立于回测区间；所有计算仅使用截至该次信号的切片。"""

    def __init__(self, dataset, execution_bars, *, policy=None, snapshot_factory=None):
        self.dataset = dataset
        self.execution_bars = execution_bars
        self.policy = policy or operational_policy()
        self.engine = StrategyEngine(self.policy)
        self.position = Position()
        self.snapshot_factory = snapshot_factory
        self.pending = {}
        self.receipted = set()
        self.audit = []
        self.receipts = []
        self.lots = []
        self.cost = 0.0
        self.peak = None
        self.peak_profit_seen = 0.0
        self.entry_high = None
        self.entry_day = None
        self.time_stop_done = False
        self.time_window_evaluated = False
        self.restore_quantity = 0.0
        self.risk_latched = set()
        self.queued_risks = set()
        self.stop_remaining = {}
        self.fee_rate, self.slippage, self.lot_size = 0.0003, 0.0005, 1
        self.stopped_weeks = set()
        self.latest_stop = None
        calendar = dataset.calendar
        end = datetime.combine(calendar.sessions[-1], time(15, 30), SH)
        self.prepared = {}
        for key, period in (("week", "week"), ("month", "month")):
            bars = settled_bars(dataset.growth, calendar, end, period)
            self.prepared[key] = complete_segment_indicators(bars, period)
        self.prepared["defense_week"] = settled_bars(
            dataset.dividend, calendar, end, "week"
        )
        self.etf_weeks = complete_segment_indicators(
            settled_bars(execution_bars["159915"], calendar, end, "week"), "week"
        )
        self.week_closes = {pd.Timestamp(d).date() for d in self.prepared["week"].date}

    def execution(self, event):
        """只根据真实成交更新阶梯，零成交/取消不当作买入成功。"""
        trades = event["trades"]
        day = event["date"]
        self.cost = event["costs"].get("159915", 0.0)
        for trade in trades:
            if trade["symbol"] != "159915":
                continue
            if trade["side"] == "buy":
                self.lots.append(
                    {
                        "date": day.isoformat(),
                        "quantity": trade["quantity"],
                        "price": trade["price"],
                        "reason": trade["reason"],
                    }
                )
            else:
                remaining = trade["quantity"]
                for lot in self.lots:
                    taken = min(lot["quantity"], remaining)
                    lot["quantity"] -= taken
                    remaining -= taken
                self.lots = [lot for lot in self.lots if lot["quantity"] > 1e-9]
        target = event.get("target")
        if event["type"] == "stop":
            if trades:
                week = pd.Period(day, freq="W-SUN")
                sold = sum(t["quantity"] for t in trades)
                original = event["quantities"].get("159915", 0.0) + sold
                requested = (
                    int((original * event["stop"].fraction + 1e-10) // self.lot_size)
                    * self.lot_size
                )
                remaining = max(0.0, requested - sold)
                if remaining > 1e-9:
                    self.stop_remaining[week] = remaining
                else:
                    self.stopped_weeks.add(week)
                    self.stop_remaining.pop(week, None)
                self.position = replace(
                    self.position, pending_restore_weight=0.0, restore_due=None
                )
                self.restore_quantity = 0.0
        elif (
            target is not None
            and target.reason in self.pending
            and target.reason not in self.receipted
        ):
            decision = self.pending[target.reason]
            kind = decision.selected.action.kind
            if event["status"] in ("superseded", "unfilled_end"):
                self.queued_risks.discard(decision.selected.rule_id)
            attack_fills = [
                t
                for t in event.get("target_trades", trades)
                if t["symbol"] == "159915"
                and t["side"] == ("buy" if kind in ("entry", "restore") else "sell")
            ]
            if attack_fills and decision.selected.priority < 4:
                # 即使其它资产使目标仍待成交/随后被取消，已发生的风险减仓不能被遗忘后再次按比例减。
                self.risk_latched.add(decision.selected.rule_id)
            if (
                attack_fills
                and event["completed"]
                and event["status"] == "completed_with_cash_and_lot_constraints"
            ):
                signal_day = decision.as_of.astimezone(SH).date()
                later = sorted(d for d in self.week_closes if d > signal_day)
                updated = confirm_execution(
                    decision.position,
                    decision,
                    f"backtest:{target.reason}",
                    next_week_close=later[0] if later else None,
                )
                self.position = updated
                self.receipted.add(target.reason)
                self.queued_risks.discard(decision.selected.rule_id)
                if decision.selected.priority < 4:
                    self.risk_latched.add(decision.selected.rule_id)
                if kind == "entry":
                    if not decision.position.stages:
                        self.position = replace(
                            self.position,
                            third_disabled=bool(
                                decision.selected.rule_id == "ENTRY_BEAR"
                            ),
                            restore_count=0,
                        )
                        self.entry_day = day
                        self.time_stop_done = False
                        self.time_window_evaluated = False
                        # 建仓当周高点要等周结算才知道，信号周高点与成交周高点不混用。
                        self.entry_high = None
                if decision.selected.rule_id == "P1_TIME":
                    self.time_stop_done = True
                if decision.selected.rule_id == "P3_MA10":
                    self.restore_quantity = sum(t["quantity"] for t in attack_fills)
                elif kind in ("reduce", "clear"):
                    self.restore_quantity = 0.0
                elif kind == "restore":
                    self.restore_quantity = max(
                        0.0,
                        self.restore_quantity
                        - sum(t["quantity"] for t in attack_fills),
                    )
        qty = event["quantities"].get("159915", 0.0)
        if qty <= 1e-9:
            self.position = replace(
                self.position,
                attack_weight=0.0,
                stages=(),
                nuclear=False,
                entry_mode=None,
                pending_restore_weight=0.0,
                restore_due=None,
            )
            self.peak = None
            self.peak_profit_seen = 0.0
            self.entry_day = None
            self.entry_high = None
            self.restore_quantity = 0.0
        self.receipts.append(
            {
                "date": day.isoformat(),
                "type": event["type"],
                "status": event["status"],
                "completed": event["completed"],
                "actual_fills": len(trades),
                "quantities": event["quantities"],
                "costs": event["costs"],
                "stages": self.position.stages,
            }
        )

    def stop_provider(self, opening, history, state):
        if not self.policy.approved("atr_drawdown_definition"):
            return None
        week = pd.Period(opening.astimezone(SH).date(), freq="W-SUN")
        if week in self.stopped_weeks:
            return None
        known = self.etf_weeks.loc[
            self.etf_weeks.date.dt.date < opening.astimezone(SH).date()
        ]
        if known.empty:
            return None
        row = known.iloc[-1]
        if not np.isfinite(row.atr14) or row.atr14 <= 0:
            return None
        # 固定上一个已结算周收盘 - 2倍其ATR；不依赖进行中周的高/低/收。
        level = float(row.close - 2 * row.atr14)
        if level <= 0:
            return None
        self.latest_stop = level
        fraction = (
            min(1.0, self.stop_remaining[week] / state["qty"].get("159915", 1.0))
            if week in self.stop_remaining and state["qty"].get("159915", 0.0) > 0
            else 0.5
        )
        return ProtectiveStop(
            "159915",
            level,
            fraction,
            datetime.combine(row.date.date(), time(15, 30), SH),
            "P1_ATR:授权固定前周收盘-2×前周ATR；日OHLC预置止损模型",
        )

    def _context(self, as_of, row):
        day = as_of.astimezone(SH).date()
        etf = self.etf_weeks.loc[self.etf_weeks.date.dt.date <= day]
        weight = float(row.get("weight_159915", 0))
        self.position = replace(self.position, attack_weight=weight)
        quantity = float(row.get("quantity_159915", 0))
        if (
            quantity > 0
            and self.restore_quantity > 0
            and self.position.restore_due is not None
        ):
            current_price = weight * row["equity"] / quantity
            desired = self.restore_quantity * current_price / row["equity"]
            if desired <= 1:
                self.position = replace(self.position, pending_restore_weight=desired)
        facts = {
            "eligible_lot_weight": weight if self.lots else 0.0,
            "atr_stop_executed_this_week": pd.Period(day, freq="W-SUN")
            in self.stopped_weeks,
        }
        if len(etf):
            x = etf.iloc[-1]
            if len(etf) >= 2 and np.isfinite(etf.atr14.iloc[-2]):
                facts["week_atr14"] = float(etf.atr14.iloc[-2])
                facts["max_week_drop_price"] = float(
                    max(0.0, etf.close.iloc[-2] - x.low)
                )
            value = weight * row["equity"]
            quantity = float(row.get("quantity_159915", 0))
            if self.cost > 0 and quantity > 0:
                price, avg_cost = value / quantity, self.cost / quantity
                facts["profit_pct"] = (price / avg_cost - 1) * 100
                self.peak = max(self.peak or price, price)
                self.peak_profit_seen = max(self.peak_profit_seen, facts["profit_pct"])
                facts["peak_profit_pct"] = self.peak_profit_seen
                facts["drawdown_8"] = bool(price <= self.peak * 0.92)
            if self.entry_day is not None:
                entered = etf.loc[etf.date.dt.date >= self.entry_day]
                if len(entered):
                    if self.entry_high is None:
                        self.entry_high = float(entered.iloc[0].high)
                    facts["entry_week_high"] = self.entry_high
                    after = entered.iloc[1:]
                    facts["post_entry_four_weeks"] = bool(
                        len(after) >= 4 and not self.time_window_evaluated
                    )
                    if len(after) >= 4:
                        selected = etf.loc[after.head(4).index]
                        prev = etf.close.shift(1).loc[selected.index]
                        facts["sideways_rows"] = tuple(
                            (float(r.high), float(r.low), float(r.close), float(p))
                            for (_, r), p in zip(selected.iterrows(), prev)
                        )
                    facts["rise_from_bottom_100"] = bool(
                        x.close >= entered.low.min() * 2
                    )
            # 风险预算为计划止损距离估计，不把跳空风险声称为硬上限。
            if np.isfinite(x.ma60) and x.close > 0:
                distance = max(0.0, (x.close - x.ma60) / x.close)
                facts["stop_distance_pct"] = distance * 100
                facts["execution_cost_buffer_pct"] = (
                    self.fee_rate + self.slippage
                ) * 200 + self.policy.parameters["risk_gap_stress_pct"]
        return facts

    def close(self, as_of, history, row):
        day = as_of.astimezone(SH).date()
        if day not in self.week_closes:
            return None
        context = self._context(as_of, row)
        snapshot, weekly, monthly = build_operational_snapshot(
            self.dataset.growth,
            self.dataset.dividend,
            self.dataset.calendar,
            as_of=as_of,
            policy=self.policy,
            context=context,
            macros=self.dataset.macros,
            historical_time_assumption=True,
            prepared=self.prepared,
        )
        if len(weekly) >= 8 and weekly.tail(8).ma30.notna().all():
            from ..strategy.types import Evidence

            facts = dict(snapshot.facts)
            facts["six_of_eight_above_ma30"] = Evidence(
                bool((weekly.tail(8).close > weekly.tail(8).ma30).sum() >= 6),
                "授权8周中至少6周收盘>MA30",
                as_of,
                as_of,
                as_of,
            )
            snapshot = replace(snapshot, facts=facts)
        if self.snapshot_factory:
            snapshot = self.snapshot_factory(snapshot, self.position)
        month = snapshot.get("month_slope")
        if (
            isinstance(month, (float, int))
            and isfinite(month)
            and (self.position.stages or self.position.attack_weight > 0)
        ):
            self.position = observe_month(self.position, month)
        risks = exit_rules(snapshot, self.position, self.policy)
        for rule in risks:
            if rule.status is Status.CLEAR:
                self.risk_latched.discard(rule.rule_id)
        decision = self.engine.evaluate(
            snapshot,
            self.position,
            suppressed_rules=self.risk_latched | self.queued_risks,
        )
        if len(context.get("sideways_rows", ())) == 4 and all(
            all(np.isfinite(v) for v in row) for row in context["sideways_rows"]
        ):
            self.time_window_evaluated = True
        plan = defense_plan(
            snapshot,
            self.policy,
            active=self.position.attack_weight == 0
            or bool(decision.selected and decision.selected.priority == 0),
        )
        unresolved = sorted(
            {
                r.rule_id
                for r in decision.results
                if r.status in (Status.MISSING, Status.PENDING)
            }
        )
        self.audit.append(
            {
                "as_of": as_of.isoformat(),
                "decision": decision.status,
                "selected": decision.selected.rule_id if decision.selected else None,
                "unresolved_rules": unresolved,
                "explanation": decision.explanation,
                "defense": plan,
                "position": {
                    "attack_weight": self.position.attack_weight,
                    "stages": self.position.stages,
                },
                "macro": thermometer(snapshot, self.policy),
                "missing_inputs": [
                    key
                    for key in (
                        "iv_short_pct",
                        "iv_long_pct",
                        "equity_bond_ratio",
                        "margin_pct",
                        "pe_percentile",
                        "peg",
                    )
                    if snapshot.get(key) is None
                ],
                "rule_status": {r.rule_id: r.status.value for r in decision.results},
                "evidence": {
                    k: {
                        "value": e.value,
                        "source": e.source,
                        "available_at": e.available_at.isoformat(),
                    }
                    for k, e in snapshot.facts.items()
                    if not k.endswith("_input_history")
                },
            }
        )
        weights = None
        if decision.selected:
            action = decision.selected.action
            if action.kind in ("entry", "restore"):
                etf = self.etf_weeks.loc[self.etf_weeks.date.dt.date <= day]
                if len(etf) and np.isfinite(etf.iloc[-1].ma60):
                    distance = max(
                        0.0,
                        (etf.iloc[-1].close - etf.iloc[-1].ma60) / etf.iloc[-1].close,
                    )
                    if (
                        distance * action.fraction * 100
                        > self.policy.parameters["risk_budget_pct"]
                    ):
                        self.audit[-1][
                            "execution_blocker"
                        ] = "按此动作实际计划增量估算的止损风险超过授权3%预算；不缩减原档位强行成交"
                        return None
            if action.timing == "intraday":
                # 预置单由stop_provider处理；不拿当周最终低点假装提前成交。
                return None
            current = self.position.attack_weight
            attack = (
                current + action.fraction
                if action.kind in ("entry", "restore")
                else 0.0 if action.kind == "clear" else current * (1 - action.fraction)
            )
            if attack <= 1e-12:
                weights = {
                    "159915": 0.0,
                    **(plan["weights"] if plan.get("executable") else {}),
                }
            else:
                weights = {"159915": attack}
            reason = f"{as_of.date()}:{decision.selected.rule_id}"
            self.pending[reason] = decision
            if decision.selected.priority < 4:
                self.queued_risks.add(decision.selected.rule_id)
        elif self.position.attack_weight == 0 and plan.get("executable"):
            weights = {"159915": 0.0, **plan["weights"]}
            reason = f"{as_of.date()}:DEFENSE_DYNAMIC"
        if weights is None:
            return None
        # 防守每周仅在明显偏离(0.5个百分点)时再平衡，避免费用引起无限微小交易。
        if all(
            abs(float(row.get(f"weight_{s}", 0.0)) - weights.get(s, 0.0)) < 0.005
            for s in self.execution_bars
        ):
            return None
        return Target(as_of, weights, reason, as_of)

    def run(self, config):
        self.fee_rate, self.slippage, self.lot_size = (
            config.fee_rate,
            config.slippage,
            config.lot_size,
        )
        result = BacktestEngine().run(
            MarketData(self.execution_bars, self.dataset.calendar),
            replace(config, enforce_t_plus_one=True),
            on_close=self.close,
            on_execution=self.execution,
            stop_provider=self.stop_provider,
        )
        unresolved = sorted(
            {rule for row in self.audit for rule in row["unresolved_rules"]}
        )
        result.metadata.update(
            {
                "name": "矛与盾授权口径研究回放（完整性逐条审计）",
                "definition_version": DEFINITION_VERSION,
                "policy_approvals": dict(self.policy.approvals),
                "policy_parameters": dict(self.policy.parameters),
                "strategy_audit": self.audit,
                "execution_receipts": self.receipts,
                "open_lots": self.lots,
                "unresolved_rules": unresolved,
                "complete_strategy_validated": False,
                "input_gaps": sorted(
                    {key for audit in self.audit for key in audit["missing_inputs"]}
                ),
                "attack_trade_count": sum(
                    t["symbol"] == "159915" for t in result.trades
                ),
                "defense_trade_count": sum(
                    t["symbol"] != "159915" for t in result.trades
                ),
                "data_provenance": self.dataset.provenance,
                "coverage_partial": False,
                "coverage_note": f"请求{config.start}至{config.end}；实际{result.metadata['effective_start']}至{result.metadata['effective_end']}",
                "limitations": [
                    *result.metadata["limitations"],
                    *self.dataset.limitations,
                    "ATR为事先已知阈值的日OHLC止损模拟，不提供真实触发分钟；持仓T+1仅执行模型",
                    "授权操作定义不是原文额外规定；缺失规则不会被当作正常；研究回放收益不能称完整策略验收收益",
                ],
            }
        )
        cutoff = result.curve.iloc[-1].date.date()
        result.metadata["signal_input_bars"] = {
            key: json.loads(
                frame.loc[frame.date.dt.date <= cutoff].to_json(
                    orient="records", date_format="iso"
                )
            )
            for key, frame in (
                ("399006", self.dataset.growth),
                ("H30269", self.dataset.dividend),
            )
        }
        return result
