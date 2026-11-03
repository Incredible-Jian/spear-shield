"""日事件回测：公司行动 -> 开盘成交 -> 收盘估值 -> 信号；不做隐式补价。"""

from __future__ import annotations

from datetime import datetime, time
from copy import deepcopy
import hashlib
import json
from math import floor
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .metrics import performance
from .models import (
    BacktestConfig,
    BacktestResult,
    MarketData,
    Target,
    ProtectiveStop,
    CORE,
)

SH = ZoneInfo("Asia/Shanghai")


def validate_market(data: MarketData, config: BacktestConfig):
    if not data.bars or set(data.bars) - CORE:
        raise ValueError("无行情或存在非核心标的")
    if config.mode == "raw_events" and (
        not data.calendar.complete or not data.actions_coverage.strip()
    ):
        raise ValueError("原始价模式须完整交易日历与公司行动覆盖声明")
    if config.mode == "qfq_research" and data.actions:
        raise ValueError("前复权模式禁止再叠加现金分红/拆分")
    sessions = [d for d in data.calendar.sessions if config.start <= d <= config.end]
    if not sessions:
        raise ValueError("区间没有交易日")
    output = {}
    for symbol, raw in data.bars.items():
        required = {
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
            "adjust",
        }
        if missing := required - set(raw):
            raise ValueError(f"{symbol}缺少字段:{sorted(missing)}")
        df = raw.copy(deep=True)
        dates = pd.to_datetime(df.date, errors="raise")
        if (
            dates.isna().any()
            or dates.dt.tz is not None
            or not dates.eq(dates.dt.normalize()).all()
            or dates.duplicated().any()
        ):
            raise ValueError("行情日期须唯一且为无时区日期")
        df["date"] = dates.dt.date
        df = (
            df.loc[df.date.between(config.start, config.end)]
            .set_index("date")
            .sort_index()
        )
        if set(sessions) != set(df.index):
            raise ValueError(f"{symbol}交易日缺失/不在日历；不自动填补或缩短回测区间")
        expected = "qfq" if config.mode == "qfq_research" else "none"
        if (
            not df.adjust.eq(expected).all()
            or not df.source.map(lambda x: isinstance(x, str) and bool(x.strip())).all()
        ):
            raise ValueError("复权类型或来源不合法")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="raise")
            if not np.isfinite(df[col]).all():
                raise ValueError("非有限行情")
        if (
            (df[["open", "high", "low", "close"]] <= 0).any().any()
            or (df.volume < 0).any()
            or (df.high < df[["open", "low", "close"]].max(axis=1)).any()
            or (df.low > df[["open", "close"]].min(axis=1)).any()
        ):
            raise ValueError("OHLCV非法")
        if "suspended" not in df:
            df["suspended"] = False
        if not df.suspended.map(lambda x: isinstance(x, (bool, np.bool_))).all():
            raise ValueError("suspended须为布尔值")
        # 零成交量不足以证明停牌；非停牌缺成交量拒绝，不猜测开盘能成交。
        if ((df.volume == 0) & ~df.suspended).any():
            raise ValueError("零成交量须提供显式停牌标记")
        output[symbol] = df
    seen = set()
    for event in data.actions:
        key = (event.symbol, event.ex_date)
        if key in seen or event.symbol not in output:
            raise ValueError("公司行动重复或缺少标的行情")
        seen.add(key)
        if (
            config.start <= event.ex_date <= config.end
            and event.ex_date not in sessions
        ):
            raise ValueError("除权日不在交易日历")
    return sessions, output


class BacktestEngine:
    def run(
        self,
        data: MarketData,
        config: BacktestConfig,
        targets=(),
        *,
        on_close=None,
        on_execution=None,
        stop_provider=None,
    ):
        """on_close只接收截至当日的副本；返回Target或None，可独立注入策略。

        给定targets必须来自外部已知信息；时点校验不能认证调用者的数据真实性。
        未成交订单逐日重试至成交/被新目标替代/区间结束，均记录原因。

        on_execution(receipt)在每次目标尝试/终止及止损检查后调用。receipt含
        type(target/stop)、target、stop、date、status、completed、trades(本次)、
        target_trades(本目标累计)和state(cash/qty/cost/open/prices/receivable)。
        扁平quantities/costs/cash/prices对应state的qty/cost/cash/prices；
        event/day为type/date别名。deferred列出目标各标的延期原因。
        completed不保证精确目标权重，现金和整手约束正常完成也为True；
        部分延期/未成交为False，只按trades推进成交状态。state不含当日
        high/low/close；prices为open或截至本事件的最近实际成交价。
        stop_provider(opening, history_until_previous_session, state_at_open)在
        开盘目标执行前调用，返回仅当日有效的ProtectiveStop或None。固定线
        按日low严格小于trigger触发；这是日OHLC预置止损模型，无分钟时点。
        """
        sessions, bars = validate_market(data, config)
        schedule = sorted(targets, key=lambda t: t.signal_at)
        if len({t.signal_at for t in schedule}) != len(schedule):
            raise ValueError("同一时点存在冲突目标")
        for target in schedule:
            if set(target.weights) - set(bars):
                raise ValueError("目标标的缺少行情")
            if target.signal_at.astimezone(SH).time() < time(15, 30):
                raise ValueError("仅接受15:30后收盘信号，禁止同日盘中目标")
        cash = config.initial_cash
        qty = {s: 0.0 for s in bars}
        cost = {s: 0.0 for s in bars}
        income_basis = {s: 0.0 for s in bars}
        actions = tuple(data.actions)
        action_log = []
        receivables = []
        trades, orders, signals, curve = [], [], [], []
        pending = None
        cursor = 0
        target_fills = {}

        def state(prices=None):
            opens = {s: float(bars[s].loc[day, "open"]) for s in bars}
            return {
                "cash": cash,
                "qty": dict(qty),
                "cost": dict(cost),
                "open": opens,
                "prices": dict(execution_prices if prices is None else prices),
                "receivable": sum(v for _, v in receivables),
            }

        def receipt(
            event,
            target,
            status,
            completed,
            fills=(),
            stop=None,
            prices=None,
            deferred=(),
        ):
            if on_execution is not None:
                snapshot = state(prices)
                on_execution(
                    {
                        "type": event,
                        "event": event,
                        "target": target,
                        "stop": stop,
                        "date": day,
                        "day": day,
                        "status": status,
                        "completed": completed,
                        "trades": deepcopy(list(fills)),
                        "target_trades": deepcopy(
                            target_fills.get(
                                target.signal_at if target is not None else None, []
                            )
                        ),
                        "deferred": deepcopy(list(deferred)),
                        "state": snapshot,
                        "quantities": dict(snapshot["qty"]),
                        "costs": dict(snapshot["cost"]),
                        "cash": snapshot["cash"],
                        "prices": dict(snapshot["prices"]),
                    }
                )

        def sell(s, amount, price, reference, reason, signal_at):
            nonlocal cash
            fee = amount * price * config.fee_rate
            released = cost[s] * amount / qty[s]
            dividend_pnl = income_basis[s] * amount / qty[s]
            income_basis[s] -= dividend_pnl
            cost[s] -= released
            qty[s] -= amount
            cash += amount * price - fee
            price_pnl = amount * price - fee - released
            return {
                "date": day.isoformat(),
                "signal_at": signal_at,
                "symbol": s,
                "side": "sell",
                "price": price,
                "quantity": amount,
                "fee": fee,
                "slippage_cost": amount * abs(price - reference),
                "realized_pnl": price_pnl + dividend_pnl,
                "realized_price_pnl": price_pnl,
                "dividend_pnl": dividend_pnl,
                "reason": reason,
            }

        def record(target):
            signals.append(
                {
                    "signal_at": target.signal_at.isoformat(),
                    "available_at": target.available_at.isoformat(),
                    "weights": dict(target.weights),
                    "reason": target.reason,
                }
            )

        def enqueue(target, day):
            nonlocal pending
            record(target)
            if pending:
                if pending.signal_at == target.signal_at:
                    raise ValueError("同一时点存在冲突目标")
                older = pending if pending.signal_at < target.signal_at else target
                orders.append(
                    {
                        "date": day.isoformat(),
                        "signal_at": older.signal_at.isoformat(),
                        "status": "superseded",
                        "reason": older.reason,
                    }
                )
                receipt("target", older, "superseded", True)
                if pending.signal_at > target.signal_at:
                    return
            pending = target

        for day in sessions:
            execution_prices = {s: float(bars[s].loc[day, "open"]) for s in bars}
            opening = datetime.combine(day, time(9, 30), SH)
            closing = datetime.combine(day, time(15, 30), SH)
            # 当日开盘之前已知的信号才可成交，同日盘后信号只能在后续交易日开盘。
            while cursor < len(schedule) and schedule[cursor].signal_at < opening:
                target = schedule[cursor]
                if target.signal_at.astimezone(SH).date() >= day:
                    raise ValueError("目标须在执行日前生成；禁止同日信号提前成交")
                enqueue(target, day)
                cursor += 1
            for event in actions:
                if event.ex_date == day:
                    entitlement = qty[event.symbol] * event.cash_per_unit
                    receivables.append((event.pay_date, entitlement))
                    income_basis[event.symbol] += entitlement
                    action_log.append(
                        {
                            "date": day.isoformat(),
                            "symbol": event.symbol,
                            "source": event.source,
                            "cash_entitlement": entitlement,
                            "pay_date": event.pay_date.isoformat(),
                            "split_ratio": event.split_ratio,
                        }
                    )
                    qty[event.symbol] *= event.split_ratio
                    # 拆分只改变份数，总成本不变；分红作为独立收益，不再减成本。
            paid = sum(v for due, v in receivables if due <= day)
            cash += paid
            receivables = [(due, v) for due, v in receivables if due > day]
            due_value = sum(v for _, v in receivables)
            bought_today = {s: 0.0 for s in bars}

            def sellable(s):
                return (
                    max(0.0, qty[s] - bought_today[s])
                    if (config.enforce_t_plus_one and s in {"159915", "563020"})
                    else qty[s]
                )

            stop = None
            if stop_provider is not None:
                history = {
                    s: df.loc[df.index < day].copy(deep=True).reset_index()
                    for s, df in bars.items()
                }
                stop = stop_provider(opening, history, state())
                if stop is not None:
                    if not isinstance(stop, ProtectiveStop):
                        raise ValueError("stop_provider须返回ProtectiveStop或None")
                    if stop.known_at >= opening:
                        raise ValueError("止损known_at须严格早于当日开盘")
                    if stop.symbol not in bars:
                        raise ValueError("止损标的缺少行情")
            if pending:
                trade_start = len(trades)
                order_start = len(orders)
                opens = {s: float(bars[s].loc[day, "open"]) for s in bars}
                equity = cash + due_value + sum(qty[s] * opens[s] for s in bars)
                desired = {
                    s: floor(
                        (equity * pending.weights.get(s, 0) / opens[s] + 1e-10)
                        / config.lot_size
                    )
                    * config.lot_size
                    for s in bars
                }
                delayed = False
                for side in ("sell", "buy"):
                    # 买入采用等比例现金预算，避免字典排序偏袒某一资产。
                    needs = {s: max(0, desired[s] - qty[s]) for s in bars}
                    required_cash = sum(
                        needs[s]
                        * opens[s]
                        * (1 + config.slippage)
                        * (1 + config.fee_rate)
                        for s in bars
                        if not bars[s].loc[day, "suspended"]
                    )
                    scale = (
                        min(1.0, max(0, cash) / required_cash) if required_cash else 1.0
                    )
                    for s in sorted(bars):
                        delta = desired[s] - qty[s]
                        if (side == "sell" and delta >= -1e-9) or (
                            side == "buy" and delta <= 1e-9
                        ):
                            continue
                        if bars[s].loc[day, "suspended"]:
                            delayed = True
                            orders.append(
                                {
                                    "date": day.isoformat(),
                                    "symbol": s,
                                    "status": "deferred_suspension",
                                    "reason": pending.reason,
                                }
                            )
                            continue
                        # 整笔清仓允许处置拆分零碎份额；普通减仓按配置单位取整。
                        amount = (
                            (
                                qty[s]
                                if desired[s] == 0
                                else floor((-delta + 1e-10) / config.lot_size)
                                * config.lot_size
                            )
                            if side == "sell"
                            else floor((delta * scale + 1e-10) / config.lot_size)
                            * config.lot_size
                        )
                        if amount <= 1e-9:
                            continue
                        if side == "sell" and amount > sellable(s) + 1e-9:
                            delayed = True
                            amount = (
                                floor(sellable(s) / config.lot_size) * config.lot_size
                            )
                            orders.append(
                                {
                                    "date": day.isoformat(),
                                    "symbol": s,
                                    "status": "deferred_t_plus_one",
                                    "reason": pending.reason,
                                }
                            )
                            if amount <= 1e-9:
                                continue
                        price = opens[s] * (
                            1 + config.slippage
                            if side == "buy"
                            else 1 - config.slippage
                        )
                        fee = amount * price * config.fee_rate
                        pnl = None
                        price_pnl = None
                        dividend_pnl = None
                        if side == "buy":
                            cash -= amount * price + fee
                            cost[s] += amount * price + fee
                            qty[s] += amount
                            bought_today[s] += amount
                        else:
                            released = cost[s] * amount / qty[s]
                            dividend_pnl = income_basis[s] * amount / qty[s]
                            income_basis[s] -= dividend_pnl
                            cost[s] -= released
                            qty[s] -= amount
                            cash += amount * price - fee
                            price_pnl = amount * price - fee - released
                            pnl = price_pnl + dividend_pnl
                        trades.append(
                            {
                                "date": day.isoformat(),
                                "signal_at": pending.signal_at.isoformat(),
                                "symbol": s,
                                "side": side,
                                "price": price,
                                "quantity": amount,
                                "fee": fee,
                                "slippage_cost": amount * abs(price - opens[s]),
                                "realized_pnl": pnl,
                                "realized_price_pnl": price_pnl,
                                "dividend_pnl": dividend_pnl,
                                "reason": pending.reason,
                            }
                        )
                if cash < -1e-6:
                    raise ArithmeticError("回测现金透支")
                orders.append(
                    {
                        "date": day.isoformat(),
                        "signal_at": pending.signal_at.isoformat(),
                        "status": (
                            "pending"
                            if delayed
                            else "completed_with_cash_and_lot_constraints"
                        ),
                        "reason": pending.reason,
                    }
                )
                fills = trades[trade_start:]
                for fill in fills:
                    execution_prices[fill["symbol"]] = fill["price"]
                target_fills.setdefault(pending.signal_at, []).extend(deepcopy(fills))
                receipt(
                    "target",
                    pending,
                    orders[-1]["status"],
                    not delayed,
                    fills,
                    deferred=[
                        o
                        for o in orders[order_start:]
                        if o["status"].startswith("deferred_")
                    ],
                )
                if not delayed:
                    pending = None
            if stop is not None:
                s = stop.symbol
                bar = bars[s].loc[day]
                fills = []
                status = "not_triggered"
                # 停牌即使输入low越线也不能成交；不推断触发分钟。
                if bar["suspended"]:
                    status = "deferred_suspension"
                elif float(bar["low"]) < stop.trigger_price:
                    requested = (
                        qty[s]
                        if stop.fraction == 1
                        else (
                            floor((qty[s] * stop.fraction + 1e-10) / config.lot_size)
                            * config.lot_size
                        )
                    )
                    amount = requested
                    status = "completed_with_cash_and_lot_constraints"
                    if amount > sellable(s) + 1e-9:
                        amount = floor(sellable(s) / config.lot_size) * config.lot_size
                        status = "deferred_t_plus_one"
                    if amount > 1e-9:
                        reference = min(float(bar["open"]), stop.trigger_price)
                        fill = sell(
                            s,
                            amount,
                            reference * (1 - config.slippage),
                            reference,
                            stop.reason,
                            stop.known_at.isoformat(),
                        )
                        fill["execution_model"] = "daily_ohlc_preset_stop"
                        trades.append(fill)
                        fills.append(fill)
                    elif not qty[s]:
                        status = "no_position"
                orders.append(
                    {
                        "date": day.isoformat(),
                        "symbol": s,
                        "status": status,
                        "reason": stop.reason,
                        "execution_model": "daily_ohlc_preset_stop",
                    }
                )
                for fill in fills:
                    execution_prices[fill["symbol"]] = fill["price"]
                receipt(
                    "stop",
                    None,
                    status,
                    status not in {"deferred_suspension", "deferred_t_plus_one"},
                    fills,
                    stop,
                )
            values = {s: qty[s] * float(bars[s].loc[day, "close"]) for s in bars}
            equity = cash + due_value + sum(values.values())
            row = {
                "date": pd.Timestamp(day),
                "cash": max(0.0, cash),
                "receivable": due_value,
                "equity": equity,
                **{f"weight_{s}": v / equity for s, v in values.items()},
                **{f"quantity_{s}": v for s, v in qty.items()},
            }
            curve.append(row)
            # 在收盘回调之前吸收本日已知的外部目标，统一按时间排序。
            while cursor < len(schedule) and schedule[cursor].signal_at <= closing:
                enqueue(schedule[cursor], day)
                cursor += 1
            if on_close:
                history = {
                    s: df.loc[:day].copy(deep=True).reset_index()
                    for s, df in bars.items()
                }
                target = on_close(closing, history, dict(row))
                if target:
                    if target.signal_at != closing or set(target.weights) - set(bars):
                        raise ValueError("策略回调须返回当日收盘后且标的有行情的目标")
                    enqueue(target, day)
        if pending:
            orders.append(
                {
                    "date": sessions[-1].isoformat(),
                    "status": "unfilled_end",
                    "reason": pending.reason,
                }
            )
            receipt("target", pending, "unfilled_end", False)
        # 区间结束以后的预先给定目标不可进入过去的信号报告。
        signals.sort(key=lambda item: datetime.fromisoformat(item["signal_at"]))
        frame = pd.DataFrame(curve)
        input_bars = {
            s: [
                {
                    "date": day.isoformat(),
                    **{
                        c: row[c]
                        for c in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "source",
                            "adjust",
                            "suspended",
                        )
                    },
                }
                for day, row in df.iterrows()
            ]
            for s, df in bars.items()
        }
        fingerprint = hashlib.sha256(
            json.dumps(input_bars, sort_keys=True, default=str, allow_nan=False).encode(
                "utf-8"
            )
        ).hexdigest()
        return BacktestResult(
            config,
            frame,
            trades,
            orders,
            signals,
            performance(frame, trades, config.initial_cash),
            {
                "mode": config.mode,
                "calendar_source": data.calendar.source,
                "calendar_complete_declared": data.calendar.complete,
                "actions_coverage": data.actions_coverage,
                "sources": {s: sorted(set(df.source)) for s, df in bars.items()},
                "corporate_action_log": action_log,
                "input_bars": input_bars,
                "input_sha256": fingerprint,
                "metric_conventions": "Rf=0; Sharpe252; ddof1; drawdown includes initial capital; annual unavailable under1year; weighted-average closed sells include dividend entitlements",
                "effective_start": sessions[0].isoformat(),
                "effective_end": sessions[-1].isoformat(),
                "sell_lot_policy": "partial_round_down_to_lot; full_liquidation_allows_split_residual",
                "execution": "next_session_open_with_fees_slippage_and_lot_constraints",
                "stop_execution": "daily_ohlc_preset_stop; low<trigger; min(open,trigger)*(1-slippage); no_intraday_timestamp; valid_for_one_session",
                "enforce_t_plus_one": config.enforce_t_plus_one,
                "limitations": (
                    [
                        "回溯前复权研究单位，不是真实份额成交；不保证分红再投资总收益",
                        "历史复权版本/日历完整性未经认证，不可当作正式策略PIT回测",
                    ]
                    if config.mode == "qfq_research"
                    else [
                        "公司行动与日历完整性为输入方声明；T+1为可选份额约束；不含涨跌停队列与市场冲击"
                    ]
                ),
            },
        )
