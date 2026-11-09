"""Phase6.5只读审计：内容寻址反向链与逐资产损益，不改变订单/成交。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path


def digest(value):
    def encode(obj):
        if is_dataclass(obj):
            return asdict(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "item"):
            return obj.item()
        raise TypeError(type(obj).__name__)

    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=encode,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def implementation_hashes():
    root = Path(__file__).resolve().parents[1]
    names = (
        "strategy/operational.py",
        "strategy/rules.py",
        "strategy/engine.py",
        "strategy/features.py",
        "backtest/engine.py",
        "backtest/strategy_replay.py",
        "backtest/metrics.py",
        "backtest/lineage.py",
        "services/research_dataset.py",
        "portfolio/state.py",
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names
    }


def financial_attribution(result):
    """逐日恒等式：Delta市值+交易现金流+分红权益变动；费用仅扣一次。"""
    bars = result.metadata["input_bars"]
    prices = {
        s: {r["date"]: float(r["close"]) for r in rows} for s, rows in bars.items()
    }
    trades_by_date = {}
    for t in result.trades:
        trades_by_date.setdefault(t["date"], []).append(t)
    events = result.metadata.get("corporate_action_log", [])
    previous_value = {s: 0.0 for s in bars}
    previous_receivable = {s: 0.0 for s in bars}
    total_pnl = {s: 0.0 for s in bars}
    paid_to_date = {s: 0.0 for s in bars}
    previous_cash = result.config.initial_cash
    previous_equity = result.config.initial_cash
    daily = []
    cash_unexplained = 0.0
    for _, row in result.curve.iterrows():
        date = row.date.date().isoformat()
        fills = trades_by_date.get(date, [])
        flows = {
            s: sum(
                (1 if t["side"] == "sell" else -1) * t["price"] * t["quantity"]
                - t["fee"]
                for t in fills
                if t["symbol"] == s
            )
            for s in bars
        }
        values = {s: float(row[f"quantity_{s}"]) * prices[s][date] for s in bars}
        receivable, paid = {}, {}
        for s in bars:
            paid_now = sum(
                e["cash_entitlement"]
                for e in events
                if e["symbol"] == s and e["date"] <= date and e["pay_date"] <= date
            )
            paid[s] = paid_now - paid_to_date[s]
            paid_to_date[s] = paid_now
            receivable[s] = sum(
                e["cash_entitlement"]
                for e in events
                if e["symbol"] == s and e["date"] <= date < e["pay_date"]
            )
        pnl = {
            s: values[s]
            - previous_value[s]
            + flows[s]
            + paid[s]
            + receivable[s]
            - previous_receivable[s]
            for s in bars
        }
        independent_cash = (
            float(row.cash) - previous_cash - sum(flows.values()) - sum(paid.values())
        )
        residual = (
            float(row.equity) - previous_equity - sum(pnl.values()) - independent_cash
        )
        cash_unexplained += independent_cash
        for s in bars:
            total_pnl[s] += pnl[s]
        daily.append(
            {
                "date": date,
                "previous_equity": previous_equity,
                "equity": float(row.equity),
                "asset_pnl": pnl,
                "cash_independent_pnl": independent_cash,
                "equity_reconciliation_residual": residual,
                "cash": float(row.cash),
                "receivable": float(row.receivable),
                "market_values": values,
            }
        )
        previous_value, previous_receivable = values, receivable
        previous_cash, previous_equity = float(row.cash), float(row.equity)
    asset_rows = []
    for s in bars:
        trades = [t for t in result.trades if t["symbol"] == s]
        asset_rows.append(
            {
                "symbol": s,
                "scope": (
                    "attack"
                    if s == "159915"
                    else (
                        "defense_dividend"
                        if s == "563020"
                        else "stable_income" if s == "511360" else "money_etf"
                    )
                ),
                "trade_count": len(trades),
                "net_pnl": total_pnl[s],
                "contribution_to_initial_cash": total_pnl[s]
                / result.config.initial_cash,
                "fees": sum(t["fee"] for t in trades),
                "slippage_cost_already_in_fill_price": sum(
                    t["slippage_cost"] for t in trades
                ),
                "dividends_paid": paid_to_date[s],
                "dividends_receivable": previous_receivable[s],
                "end_market_value": previous_value[s],
                "buy_notional": sum(
                    t["price"] * t["quantity"] for t in trades if t["side"] == "buy"
                ),
                "sell_notional": sum(
                    t["price"] * t["quantity"] for t in trades if t["side"] == "sell"
                ),
            }
        )
    gain = float(result.curve.iloc[-1].equity) - result.config.initial_cash
    return {
        "status": "研究单位损益归因，非资产独立收益率或完整策略收益",
        "assets": asset_rows,
        "cash": {
            "independent_pnl": cash_unexplained,
            "end_balance": previous_cash,
            "interest_model": "none",
        },
        "gain": gain,
        "attributed_gain": sum(total_pnl.values()) + cash_unexplained,
        "total_residual": gain - sum(total_pnl.values()) - cash_unexplained,
        "max_daily_residual": max(
            abs(r["equity_reconciliation_residual"]) for r in daily
        ),
        "daily": daily,
        "full_strategy_return": (
            None
            if result.metadata.get("complete_strategy_validated") is False
            else "not_certified_benchmark"
        ),
        "limitations": result.metadata.get("limitations", []),
    }


def build_lineage(result):
    """后验连接事实，不伪造缺失信号/回执。未能链接的记录明确列出。"""
    meta = result.metadata
    identity = {
        "config": asdict(result.config),
        "definition_version": meta.get("definition_version"),
        "policy": {
            "approvals": meta.get("policy_approvals", {}),
            "parameters": meta.get("policy_parameters", {}),
        },
        "execution_input_sha256": meta.get("input_sha256"),
        "signal_inputs_sha256": digest(meta.get("signal_input_bars", {})),
        "etf_warmup_sha256": digest(meta.get("etf_indicator_input_bars", [])),
        "source_versions": meta.get("data_provenance", {}),
        "corporate_action_log": meta.get("corporate_action_log", []),
        "implementation_sha256": implementation_hashes(),
    }
    run_id = digest(identity)
    nodes = {
        k: []
        for k in ("decisions", "signals", "orders", "trades", "receipts", "equity")
    }

    def node(kind, payload):
        data = {"run_id": run_id, **payload}

        # 冻结为可持久化JSON值；dataclass不能在保存后变成repr字符串破坏哈希。
        def plain(obj):
            if is_dataclass(obj):
                return asdict(obj)
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            if hasattr(obj, "item"):
                return obj.item()
            raise TypeError(type(obj).__name__)

        data = json.loads(
            json.dumps(data, default=plain, ensure_ascii=False, allow_nan=False)
        )
        item = {"id": f"{kind}:{digest(data)}", "payload": data}
        nodes[kind].append(item)
        return item["id"]

    decision_by_time = {}
    for i, audit in enumerate(meta.get("strategy_audit", [])):
        identifier = node(
            "decisions",
            {
                "index": i,
                "audit": audit,
                "input_ref": identity["execution_input_sha256"],
                "signal_input_ref": identity["signal_inputs_sha256"],
                "source_versions_ref": digest(identity["source_versions"]),
            },
        )
        decision_by_time[audit["as_of"]] = identifier
    signal_by_key = {}
    unlinked = []
    for i, signal in enumerate(result.signals):
        decision_id = decision_by_time.get(signal["signal_at"])
        kind = (
            "strategy_decision"
            if decision_id
            else (
                "predeclared_benchmark"
                if not meta.get("strategy_audit")
                else "unlinked"
            )
        )
        identifier = node(
            "signals",
            {
                "index": i,
                "signal": dict(signal),
                "decision_id": decision_id,
                "kind": kind,
            },
        )
        signal_by_key[(signal["signal_at"], signal["reason"])] = identifier
        if kind == "unlinked":
            unlinked.append({"kind": "signal", "id": identifier})
    order_by_key = {}
    stop_receipts = {
        (r["date"], r["stop_instruction"]["reason"]): r["stop_instruction"]
        for r in meta.get("execution_receipts", [])
        if r.get("stop_instruction")
    }
    standing_signals = {}
    for i, order in enumerate(result.orders):
        candidates = [
            v
            for (at, reason), v in signal_by_key.items()
            if reason == order["reason"]
            and (not order.get("signal_at") or at == order["signal_at"])
        ]
        instruction = (
            stop_receipts.get((order["date"], order["reason"]))
            if order.get("execution_model") == "daily_ohlc_preset_stop"
            else None
        )
        if instruction:
            key = digest(instruction)
            if key not in standing_signals:
                decision_id = node(
                    "decisions",
                    {
                        "index": f"standing:{key}",
                        "audit": {
                            "as_of": instruction["known_at"],
                            "kind": "actual_preset_stop_instruction",
                            "selected": "P1_ATR",
                            "instruction": instruction,
                        },
                        "input_ref": identity["execution_input_sha256"],
                        "signal_input_ref": identity["etf_warmup_sha256"],
                    },
                )
                standing_signals[key] = node(
                    "signals",
                    {
                        "index": f"standing:{key}",
                        "signal": instruction,
                        "decision_id": decision_id,
                        "kind": "actual_preset_stop_instruction",
                    },
                )
            candidates = [standing_signals[key]]
        identifier = node(
            "orders",
            {
                "index": i,
                "order": dict(order),
                "signal_id": candidates[0] if len(candidates) == 1 else None,
            },
        )
        order_by_key.setdefault((order["date"], order["reason"]), []).append(identifier)
    trade_ids = []
    order_payloads = {n["id"]: n["payload"]["order"] for n in nodes["orders"]}
    fill_lookup = {}
    trades_by_date = {}
    for i, trade in enumerate(result.trades):
        candidates = [
            i
            for i in order_by_key.get((trade["date"], trade["reason"]), [])
            if not order_payloads[i].get("symbol")
            or order_payloads[i]["symbol"] == trade["symbol"]
        ]
        identifier = node(
            "trades",
            {
                "index": i,
                "trade": dict(trade),
                "order_ids": candidates,
                "raw_bar_ref": {
                    "input_sha256": meta.get("input_sha256"),
                    "symbol": trade["symbol"],
                    "date": trade["date"],
                },
            },
        )
        trade_ids.append(identifier)
        fill_lookup.setdefault(digest(trade), []).append(identifier)
        trades_by_date.setdefault(trade["date"], []).append(identifier)
        if not candidates:
            unlinked.append({"kind": "trade_order", "id": identifier})
    receipts_by_date = {}
    for i, receipt in enumerate(meta.get("execution_receipts", [])):
        fills = receipt.get("trade_fills", [])
        links = [
            identifier
            for fill in fills
            for identifier in fill_lookup.get(digest(fill), [])
        ]
        identifier = node(
            "receipts", {"index": i, "receipt": receipt, "trade_ids": links}
        )
        receipts_by_date.setdefault(receipt["date"], []).append(identifier)
        if receipt.get("actual_fills", 0) and len(links) != receipt["actual_fills"]:
            unlinked.append({"kind": "receipt_fills", "id": identifier})
    attribution = financial_attribution(result)
    previous_id = None
    for i, row in enumerate(attribution["daily"]):
        identifier = node(
            "equity",
            {
                "index": i,
                "valuation": row,
                "previous_equity_id": previous_id,
                "receipt_ids": receipts_by_date.get(row["date"], []),
                "trade_ids": trades_by_date.get(row["date"], []),
                "raw_price_refs": [
                    {
                        "symbol": s,
                        "date": row["date"],
                        "input_sha256": meta.get("input_sha256"),
                    }
                    for s in meta["input_bars"]
                ],
            },
        )
        previous_id = identifier
    # 保护单与历史旧报告未必有已保存完整指令，不捏造普通周线信号。
    stop_orders = [
        n
        for n in nodes["orders"]
        if n["payload"]["order"].get("execution_model") == "daily_ohlc_preset_stop"
    ]
    return {
        "schema_version": 1,
        "run_id": run_id,
        "identity": identity,
        "nodes": nodes,
        "unlinked": unlinked,
        "stop_instruction_orders": len(stop_orders),
        "attribution": attribution,
        "status": "PARTIAL" if unlinked else "LINKED",
        "meaning": "记录链接和数值对账不是历史实际发布时间、版权或完整策略收益认证",
    }


def validate_lineage(lineage):
    if digest(lineage["identity"]) != lineage["run_id"]:
        raise ValueError("运行身份哈希不匹配")
    for kind, nodes in lineage["nodes"].items():
        for item in nodes:
            if item["id"] != f"{kind}:{digest(item['payload'])}":
                raise ValueError(f"{kind}节点内容已改变")
    lookup = {n["id"] for nodes in lineage["nodes"].values() for n in nodes}
    for nodes in lineage["nodes"].values():
        for item in nodes:
            payload = item["payload"]
            for key in ("decision_id", "signal_id", "previous_equity_id"):
                if payload.get(key) and payload[key] not in lookup:
                    raise ValueError("反向引用缺失")
            for key in ("order_ids", "trade_ids", "receipt_ids"):
                if any(i not in lookup for i in payload.get(key, [])):
                    raise ValueError("反向引用缺失")
    if (
        abs(lineage["attribution"]["total_residual"]) > 1e-6
        or lineage["attribution"]["max_daily_residual"] > 1e-6
    ):
        raise ValueError("资金对账不一致")
    return True


def trace_equity(lineage, equity_id):
    validate_lineage(lineage)
    lookup = {
        n["id"]: n["payload"] for group in lineage["nodes"].values() for n in group
    }
    equity = lookup[equity_id]
    receipts = [lookup[i] for i in equity["receipt_ids"]]
    trades = [lookup[i] for i in equity["trade_ids"]]
    orders = [lookup[i] for trade in trades for i in trade["order_ids"]]
    signals = [lookup[o["signal_id"]] for o in orders if o["signal_id"]]
    decisions = [lookup[s["decision_id"]] for s in signals if s["decision_id"]]
    return {
        "equity": equity,
        "receipts": receipts,
        "trades": trades,
        "orders": orders,
        "signals": signals,
        "decisions": decisions,
        "input_refs": equity["raw_price_refs"],
        "run_identity": lineage["identity"],
    }
