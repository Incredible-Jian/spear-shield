"""显式缓存参考价模拟：追加订单/回执/净值，不是交易所撮合或策略自动下单。"""

from datetime import datetime, timezone, time
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import uuid
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import String, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database.models import Base
from ..services.market_view import quote_view
from ..config.symbols import get_symbol
from .paper_account import (
    PaperAccount,
    PaperHolding,
    PaperTrade,
    SCALE,
    ETFS,
    trade,
    account_view,
)

SH = ZoneInfo("Asia/Shanghai")
MODEL = "cache-reference-simulation-v1"


class PaperAccountOrigin(Base):
    __tablename__ = "paper_account_origin"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observed_from: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(40))


class PaperOrder(Base):
    __tablename__ = "paper_order"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    request: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="")


class PaperReceipt(Base):
    __tablename__ = "paper_receipt"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text)


class PaperRiskEvent(Base):
    __tablename__ = "paper_risk_event"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class PaperOrderEvent(Base):
    __tablename__ = "paper_order_event"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text)


class PaperEquityMark(Base):
    __tablename__ = "paper_equity_mark"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[str] = mapped_column(String(40))
    payload: Mapped[str] = mapped_column(Text)


def plain(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str
    )


def moment(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("模拟时点须带时区")
    return value


def finish_order(session, order, as_of=None):
    state = order_view(session, order)
    body = {k: state[k] for k in ("id", "status", "reason", "filled_quantity")}
    key = hashlib.sha256(plain(body).encode()).hexdigest()
    if session.get(PaperOrderEvent, key) is None:
        session.add(
            PaperOrderEvent(
                id=key,
                order_id=order.id,
                payload=plain({**body, "recorded_at": moment(as_of).isoformat()}),
            )
        )
    session.flush()
    return state


def write_lock(session):
    connection = session.connection()
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def execute_reference_order(
    session,
    workspace,
    code,
    side,
    quantity,
    *,
    fee_rate=0.0003,
    slippage=0.0005,
    allow_intraday=False,
    order_id=None,
    as_of=None,
    max_fill_quantity=None,
    attempt_id="initial",
    allow_failed_cache=False
):
    """调用者提交事务；失败SQL须回滚。首次flush订单取得SQLite写锁后才读资金。"""
    now = moment(as_of)
    if now > datetime.now(timezone.utc):
        raise ValueError("不得将未来时点作为当前模拟成交时间")
    write_lock(session)
    if (
        code not in ETFS
        or side not in ("buy", "sell")
        or isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or not 0 < quantity <= 10**7
    ):
        raise ValueError("仅限四ETF、合法买卖方向和正整数模拟份额")
    if max_fill_quantity is not None and (
        isinstance(max_fill_quantity, bool)
        or not isinstance(max_fill_quantity, int)
        or max_fill_quantity < 1
    ):
        raise ValueError("部分成交上限须为正整数；只是模拟执行上限，不推断市场流动性")
    if not isinstance(allow_intraday, bool) or not isinstance(allow_failed_cache, bool):
        raise ValueError("盘中参考价许可须为明确布尔值")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("执行请求须有唯一标识")
    costs = [Decimal(str(x)) for x in (fee_rate, slippage)]
    if any(not x.is_finite() or not 0 <= x < 1 for x in costs):
        raise ValueError("费用和滑点比例须在[0,1)")
    intent = dict(
        code=code,
        side=side,
        quantity=quantity,
        fee_rate=str(costs[0]),
        slippage=str(costs[1]),
        allow_intraday=allow_intraday,
        allow_failed_cache=allow_failed_cache,
        execution_model=MODEL,
    )
    order_id = order_id or uuid.uuid4().hex
    order = session.get(PaperOrder, order_id)
    if order is not None:
        old = json.loads(order.request)
        if {k: old[k] for k in intent} != intent:
            raise ValueError("不得复用订单ID改变模拟意图")
        if now < datetime.fromisoformat(old["submitted_at"]):
            raise ValueError("不得在订单提交之前模拟执行")
        if order.status in ("FILLED", "REJECTED", "CANCELLED"):
            return order_view(session, order)
    else:
        order = PaperOrder(
            id=order_id,
            status="PENDING",
            request=plain({**intent, "submitted_at": now.isoformat()}),
            reason="等待合格原始行情",
        )
        session.add(order)
    session.flush()
    fill_id = hashlib.sha256(plain([order_id, attempt_id]).encode()).hexdigest()
    if session.get(PaperReceipt, fill_id) is not None:
        return finish_order(session, order, now)
    if session.get(PaperAccount, 1) is None:
        order.status = "REJECTED"
        order.reason = "模拟账户未初始化"
        return finish_order(session, order, now)
    origin = session.get(PaperAccountOrigin, 1)
    if origin is None or now < datetime.fromisoformat(origin.observed_from):
        order.reason = (
            "UNKNOWN：账户状态时点未确认或晚于模拟时点；不能将当前余额回填历史"
        )
        return finish_order(session, order, now)
    latest_update = next((r for r in workspace.updates() if r["symbol"] == code), None)
    if (
        latest_update
        and latest_update["status"] != "success"
        and not allow_failed_cache
    ):
        order.reason = (
            "UNKNOWN：最近行情更新未成功；请成功更新或明确确认使用有日期标签的旧缓存"
        )
        return finish_order(session, order, now)
    raw = workspace.history(code, "none")
    if len(raw):
        known = pd.to_datetime(raw.updated_at, utc=True, errors="coerce") <= now
        raw = raw.loc[known & (raw.date.dt.date <= now.astimezone(SH).date())].copy()
    quote = quote_view(get_symbol(code), raw, pd.DataFrame(), now=now)
    if quote["price"] is None or not quote.get("complete") and not allow_intraday:
        order.reason = "UNKNOWN：原始价缺失、异常或未收盘；不使用前复权/手工价替代"
        return finish_order(session, order, now)
    if (now.astimezone(SH).date() - pd.Timestamp(quote["date"]).date()).days > 4:
        order.reason = "UNKNOWN：原始缓存超过4个自然日；请更新后重试（模拟数据新鲜度约束，非策略参数）"
        return finish_order(session, order, now)
    done = sum(
        json.loads(r.payload)["filled_quantity"]
        for r in session.query(PaperReceipt).filter_by(order_id=order_id).all()
    )
    fill_quantity = min(
        quantity - done,
        max_fill_quantity if max_fill_quantity is not None else quantity,
    )
    holding = session.get(PaperHolding, code)
    if side == "sell" and quantity - done > (holding.quantity if holding else 0):
        order.status = "REJECTED" if not done else "PARTIAL"
        order.reason = "模拟持仓不足，禁止超额卖出"
        return finish_order(session, order, now)
    if side == "sell" and code in ("159915", "563020"):
        today = now.astimezone(SH).date()
        bought = sum(
            r.quantity
            for r in session.query(PaperTrade).filter_by(code=code, side="buy").all()
            if datetime.fromisoformat(r.time).astimezone(SH).date() == today
        )
        holding = session.get(PaperHolding, code)
        if fill_quantity > max(0, (holding.quantity if holding else 0) - bought):
            order.status = "REJECTED"
            order.reason = "模拟T+1可卖份额不足；不把延期或拒绝当成交"
            return finish_order(session, order, now)
    reference = Decimal(str(quote["price"]))
    price = (reference * (1 + costs[1] if side == "buy" else 1 - costs[1])).quantize(
        Decimal(".0001"), rounding=ROUND_HALF_UP
    )
    fee = (price * fill_quantity * costs[0]).quantize(
        Decimal(".0001"), rounding=ROUND_HALF_UP
    )
    try:
        trade_id = trade(
            session, code, side, fill_quantity, price, fee, recorded_at=now
        )
    except ValueError as exc:
        order.status = "REJECTED" if not done else "PARTIAL"
        order.reason = str(exc)
        return finish_order(session, order, now)
    receipt = {
        **intent,
        "order_id": order_id,
        "trade_id": trade_id,
        "fill_id": fill_id,
        "attempt_id": attempt_id,
        "filled_quantity": fill_quantity,
        "fill_limit_assumption": max_fill_quantity,
        "status": "FILLED",
        "simulated": True,
        "model_time": now.isoformat(),
        "quote": quote,
        "reference_price": float(reference),
        "model_price": float(price),
        "fee": float(fee),
        "slippage_cost": float(abs(price - reference) * fill_quantity),
        "limitations": "缓存参考价情景模拟；不是当时市场可执行价或真实成交，不校验完整交易所规则/分红",
    }
    session.add(PaperReceipt(id=fill_id, order_id=order_id, payload=plain(receipt)))
    order.status = "FILLED" if done + fill_quantity == quantity else "PARTIAL"
    order.reason = "已按来源可追溯的原始缓存价进行模型模拟；未成交余量不视为成交"
    session.flush()
    mark_equity(session, workspace, as_of=now)
    return finish_order(session, order, now)


def order_view(session, order):
    receipts = [
        json.loads(r.payload)
        for r in session.query(PaperReceipt).filter_by(order_id=order.id).all()
    ]
    return {
        "id": order.id,
        "status": order.status,
        "reason": order.reason,
        "request": json.loads(order.request),
        "receipts": receipts,
        "filled_quantity": sum(r["filled_quantity"] for r in receipts),
        "receipt": receipts[-1] if receipts else None,
    }


def cancel_order(session, order_id):
    write_lock(session)
    order = session.get(PaperOrder, order_id)
    if order is None:
        raise ValueError("订单不存在")
    if order.status in ("PENDING", "PARTIAL"):
        order.status = "CANCELLED"
        order.reason = "用户取消未成交模拟意图；历史成交保留"
    return finish_order(session, order)


def execution_history(session):
    orders = [order_view(session, o) for o in session.query(PaperOrder).all()]
    marks = [
        json.loads(r.payload)
        for r in session.query(PaperEquityMark).order_by(PaperEquityMark.id).all()
    ]
    return {
        "orders": orders,
        "marks": marks,
        "order_events": [
            json.loads(r.payload) for r in session.query(PaperOrderEvent).all()
        ],
        "risk_events": [
            json.loads(r.payload) for r in session.query(PaperRiskEvent).all()
        ],
    }


def mark_equity(session, workspace, *, as_of=None, persist=True):
    now = moment(as_of)
    if persist:
        write_lock(session)
    origin = session.get(PaperAccountOrigin, 1)
    if origin is None or now < datetime.fromisoformat(origin.observed_from):
        raise ValueError("账户可知时点未知；先确认旧账户当前状态，不回填历史")
    quotes = {}
    valuation_issues = []
    for code in ETFS:
        raw = workspace.history(code, "none")
        if len(raw):
            raw = raw.loc[
                (pd.to_datetime(raw.updated_at, utc=True) <= now)
                & (raw.date.dt.date <= now.astimezone(SH).date())
            ]
        q = quote_view(get_symbol(code), raw, pd.DataFrame(), now=now)
        if q["price"] is not None:
            quotes[code] = {
                "price": q["price"],
                "date": q["date"],
                "source": q["source"],
                "updated": q["updated"],
                "completion": q["completion"],
            }
            held = session.get(PaperHolding, code)
            if held and held.quantity:
                latest = next(
                    (r for r in workspace.updates() if r["symbol"] == code), None
                )
                if (
                    now.astimezone(SH).date() - pd.Timestamp(q["date"]).date()
                ).days > 4 or (latest and latest["status"] != "success"):
                    valuation_issues.append(
                        code + ":缓存过期或最近更新失败；估值仅供观察"
                    )
    view = account_view(session, quotes)
    if not view["initialized"]:
        raise ValueError("请先初始化模拟账户")
    realized = sum(r.realized for r in session.query(PaperTrade).all()) / SCALE
    fees = sum(r.fee for r in session.query(PaperTrade).all()) / SCALE
    receipts = [json.loads(r.payload) for r in session.query(PaperReceipt).all()]
    mark = {
        "as_of": now.isoformat(),
        "cash": view["cash"],
        "initial": view["initial"],
        "equity": view["equity"],
        "market_value": view["market_value"],
        "holdings": view["holdings"],
        "quotes": quotes,
        "realized_pnl": realized,
        "fees": fees,
        "slippage_cost": (
            None
            if any(r["slippage_cost"] is None for r in receipts)
            else sum(r["slippage_cost"] for r in receipts)
        ),
        "return_pct": (
            (view["equity"] / view["initial"] - 1) * 100
            if view["equity"] is not None
            else None
        ),
        "quality": (
            "TRUE" if view["equity"] is not None and not valuation_issues else "UNKNOWN"
        ),
        "valuation_issues": valuation_issues,
        "scope": "原始缓存估值，非实盘净值；各标的实际行情日期见quotes；未含完整公司行动",
    }
    payload = plain(mark)
    # Identical refresh does not multiply equity history at the same instant.
    last = session.query(PaperEquityMark).order_by(PaperEquityMark.id.desc()).first()
    if persist and (last is None or last.payload != payload):
        session.add(PaperEquityMark(as_of=now.isoformat(), payload=payload))
    session.flush()
    return mark


def adopt_legacy_account(session):
    write_lock(session)
    if session.get(PaperAccount, 1) is None:
        raise ValueError("账户未初始化")
    if session.get(PaperAccountOrigin, 1) is None:
        session.add(
            PaperAccountOrigin(
                id=1,
                observed_from=moment().isoformat(),
                mode="USER_CONFIRMED_CURRENT_STATE",
            )
        )
        session.flush()


def record_manual_order(session, code, side, quantity, price, fee=0):
    """兼容显式手工记账；绝不作为缓存模拟的缺价自动降级路径。"""
    now = moment()
    order_id = uuid.uuid4().hex
    write_lock(session)
    request = {
        "code": code,
        "side": side,
        "quantity": quantity,
        "execution_model": "manual-ledger-unverified",
        "submitted_at": now.isoformat(),
    }
    trade_id = trade(session, code, side, quantity, price, fee, recorded_at=now)
    receipt = {
        **request,
        "filled_quantity": quantity,
        "model_price": price,
        "reference_price": None,
        "fee": fee,
        "slippage_cost": None,
        "order_id": order_id,
        "trade_id": trade_id,
        "fill_id": order_id,
        "model_time": now.isoformat(),
        "simulated": True,
        "quote": {
            "date": None,
            "source": "USER_INPUT_UNVERIFIED",
            "quality": "UNKNOWN",
        },
        "limitations": "用户明确选择手工记账；没有核验市场价格，不能冒充真实行情模拟成交",
    }
    session.add(
        PaperOrder(
            id=order_id,
            status="FILLED",
            request=plain(request),
            reason=receipt["limitations"],
        )
    )
    session.add(PaperReceipt(id=order_id, order_id=order_id, payload=plain(receipt)))
    session.flush()
    return finish_order(session, session.get(PaperOrder, order_id), now)
