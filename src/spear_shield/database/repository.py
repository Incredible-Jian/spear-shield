"""数据仓储：行情与两融的落库、读取与更新日志。"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import DataUpdateLog, MarginDaily, MarketDaily, _utcnow

_DAILY_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


def upsert_market_daily(
    session: Session,
    symbol_code: str,
    asset_type: str,
    df: pd.DataFrame,
    adjust: str,
    source: str,
) -> int:
    """按 symbol+adjust 覆盖写入指定日期区间，返回写入行数。"""
    if df.empty:
        return 0
    dates = [d.date() for d in pd.to_datetime(df["date"])]
    session.query(MarketDaily).filter(
        MarketDaily.symbol_code == symbol_code,
        MarketDaily.adjust == adjust,
        MarketDaily.date.in_(dates),
    ).delete(synchronize_session=False)

    rows = [
        MarketDaily(
            symbol_code=symbol_code,
            asset_type=asset_type,
            date=row["date"].date(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            amount=float(row["amount"]) if pd.notna(row["amount"]) else None,
            adjust=adjust,
            source=source,
        )
        for _, row in df.iterrows()
    ]
    session.bulk_save_objects(rows)
    session.commit()
    return len(rows)


def load_market_daily(
    session: Session, symbol_code: str, adjust: str = "qfq"
) -> pd.DataFrame:
    """读取某标的的全部日线（按日期升序）。"""
    rows = (
        session.query(MarketDaily)
        .filter(
            MarketDaily.symbol_code == symbol_code,
            MarketDaily.adjust == adjust,
        )
        .order_by(MarketDaily.date)
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=_DAILY_COLS)
    return pd.DataFrame(
        [{
            "date": r.date, "open": r.open, "high": r.high,
            "low": r.low, "close": r.close, "volume": r.volume,
            "amount": r.amount,
        } for r in rows]
    )


def market_daily_date_range(
    session: Session, symbol_code: str, adjust: str = "qfq"
) -> tuple | None:
    """返回 (min_date, max_date) 或 None。"""
    row = session.query(
        func.min(MarketDaily.date), func.max(MarketDaily.date)
    ).filter(
        MarketDaily.symbol_code == symbol_code,
        MarketDaily.adjust == adjust,
    ).one()
    if row[0] is None:
        return None
    return (row[0], row[1])


def upsert_margin_daily(session: Session, df: pd.DataFrame, source: str) -> int:
    """覆盖写入两融数据，返回写入行数。"""
    if df.empty:
        return 0
    dates = [d.date() for d in pd.to_datetime(df["date"])]
    session.query(MarginDaily).filter(MarginDaily.date.in_(dates)).delete(
        synchronize_session=False
    )
    rows = [
        MarginDaily(
            date=row["date"].date(),
            margin_balance=float(row["margin_balance"]),
            securities_balance=float(row["securities_balance"]),
            margin_buy=float(row["margin_buy"]),
            securities_sell=float(row["securities_sell"]),
            source=source,
        )
        for _, row in df.iterrows()
    ]
    session.bulk_save_objects(rows)
    session.commit()
    return len(rows)


def load_margin_daily(session: Session) -> pd.DataFrame:
    """读取两融日频数据（按日期升序）。"""
    rows = session.query(MarginDaily).order_by(MarginDaily.date).all()
    if not rows:
        return pd.DataFrame(columns=["date", "margin_balance",
                                     "securities_balance", "margin_buy",
                                     "securities_sell"])
    return pd.DataFrame([{
        "date": r.date, "margin_balance": r.margin_balance,
        "securities_balance": r.securities_balance,
        "margin_buy": r.margin_buy, "securities_sell": r.securities_sell,
    } for r in rows])


def log_update(
    session: Session,
    symbol_code: str | None,
    source: str,
    status: str,
    row_count: int,
) -> None:
    """记录一次数据更新结果。"""
    session.add(DataUpdateLog(
        symbol_code=symbol_code,
        source=source,
        finished_at=_utcnow(),
        row_count=row_count,
        status=status,
    ))
    session.commit()
