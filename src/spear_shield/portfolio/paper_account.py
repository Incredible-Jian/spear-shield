"""手工模拟记账，整数万分之一元存储；不连接券商、不触发策略订单。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..config.symbols import CORE_ETFS
from ..database.models import Base

ETFS = {s.code for s in CORE_ETFS}
SCALE = 10000


def units(value) -> int:
    try:
        number = Decimal(str(value))
        scaled = number * SCALE
        if (
            not number.is_finite()
            or scaled != scaled.to_integral_value()
            or abs(scaled) > 10**14
        ):
            raise ValueError("金额须为有限数，最多4位小数且在支持范围内")
        return int(scaled)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("金额格式错误") from exc


class PaperAccount(Base):
    __tablename__ = "paper_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initial: Mapped[int] = mapped_column(BigInteger)
    cash: Mapped[int] = mapped_column(BigInteger)


class PaperHolding(Base):
    __tablename__ = "paper_holding"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)
    cost: Mapped[int] = mapped_column(BigInteger)


class PaperTrade(Base):
    __tablename__ = "paper_trade"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    time: Mapped[str] = mapped_column(String(40))
    code: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(BigInteger)
    fee: Mapped[int] = mapped_column(BigInteger)
    realized: Mapped[int] = mapped_column(BigInteger)


def initialize(session, initial):
    amount = units(initial)
    if amount <= 0:
        raise ValueError("初始资金须大于0")
    if session.get(PaperAccount, 1):
        raise ValueError("账户已初始化，不允许覆盖资金和记录")
    session.add(PaperAccount(id=1, initial=amount, cash=amount))
    from .paper_execution import PaperAccountOrigin

    session.add(
        PaperAccountOrigin(
            id=1,
            observed_from=datetime.now(timezone.utc).isoformat(),
            mode="NEW_SIMULATED_ACCOUNT",
        )
    )
    session.flush()


def trade(session, code, side, quantity, price, fee=0, *, recorded_at=None):
    if code not in ETFS or side not in ("buy", "sell"):
        raise ValueError("仅支持核心四只ETF的模拟买卖")
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or not 0 < quantity <= 10**7
    ):
        raise ValueError(
            "份额须为1至10000000的整数；此为手工模拟，不校验交易所申报单位"
        )
    p, f = units(price), units(fee)
    if p <= 0 or f < 0:
        raise ValueError("价格须正且费用非负")
    account = session.get(PaperAccount, 1)
    if account is None:
        raise ValueError("请先初始化模拟账户")
    holding = session.get(PaperHolding, code)
    amount = p * quantity
    realized = 0
    if side == "buy":
        if amount + f > account.cash:
            raise ValueError("模拟现金不足")
        if holding is None:
            holding = PaperHolding(code=code, quantity=0, cost=0)
            session.add(holding)
        account.cash -= amount + f
        holding.quantity += quantity
        holding.cost += amount + f
    else:
        if holding is None or quantity > holding.quantity:
            raise ValueError("模拟持仓不足，禁止卖空")
        allocated = (
            holding.cost
            if quantity == holding.quantity
            else holding.cost * quantity // holding.quantity
        )
        new_cash = account.cash + amount - f
        if not 0 <= new_cash < 2**63:
            raise ValueError("模拟现金超出范围或费用不足以支付")
        realized = amount - f - allocated
        account.cash = new_cash
        holding.quantity -= quantity
        holding.cost -= allocated
    entry = PaperTrade(
        time=(recorded_at or datetime.now(timezone.utc)).isoformat(),
        code=code,
        side=side,
        quantity=quantity,
        price=p,
        fee=f,
        realized=realized,
    )
    session.add(entry)
    session.flush()
    return entry.id


def account_view(session, raw_quotes: dict):
    account = session.get(PaperAccount, 1)
    if account is None:
        return {"initialized": False, "holdings": [], "trades": []}
    holdings = []
    complete = True
    total = 0
    for holding in session.query(PaperHolding).filter(PaperHolding.quantity > 0).all():
        quote = raw_quotes.get(holding.code)
        value = units(quote["price"]) * holding.quantity if quote else None
        complete &= value is not None
        if value is not None:
            total += value
        holdings.append(
            {
                "code": holding.code,
                "quantity": holding.quantity,
                "cost": holding.cost / SCALE,
                "average": holding.cost / holding.quantity / SCALE,
                "price": quote["price"] if quote else None,
                "source": quote.get("source", "未记录") if quote else "UNKNOWN",
                "value": value / SCALE if value is not None else None,
                "pnl": (value - holding.cost) / SCALE if value is not None else None,
                "quote_date": quote["date"] if quote else "原始价缺失",
            }
        )
    records = session.query(PaperTrade).order_by(PaperTrade.id.desc()).limit(500).all()
    return {
        "initialized": True,
        "initial": account.initial / SCALE,
        "cash": account.cash / SCALE,
        "market_value": total / SCALE if complete else None,
        "equity": (account.cash + total) / SCALE if complete else None,
        "holdings": holdings,
        "trades": [
            {
                "time": r.time,
                "code": r.code,
                "side": r.side,
                "quantity": r.quantity,
                "price": r.price / SCALE,
                "fee": r.fee / SCALE,
                "realized": r.realized / SCALE,
            }
            for r in records
        ],
    }
