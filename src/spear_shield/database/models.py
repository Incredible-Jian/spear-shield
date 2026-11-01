"""数据库 ORM 模型。

Phase 2 起补充行情与两融表；账户/信号/指标快照表在后续阶段加入。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """返回 naive UTC 时间（配合不带时区的 DateTime 列，避免弃用警告）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""


class SchemaVersion(Base):
    """数据库结构版本记录（用于后续迁移）。"""

    __tablename__ = "schema_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MarketDaily(Base):
    """标的日线行情（前复权 + 原始，来源与更新时间可追溯）。"""

    __tablename__ = "market_daily"
    __table_args__ = (
        UniqueConstraint("symbol_code", "date", "adjust", name="uq_market_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_code: Mapped[str] = mapped_column(String(16), index=True)
    asset_type: Mapped[str] = mapped_column(String(16))  # etf / index
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    adjust: Mapped[str] = mapped_column(String(8))  # qfq / hfq / none
    source: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MarginDaily(Base):
    """全市场两融账户统计（日频）。"""

    __tablename__ = "margin_daily"
    __table_args__ = (UniqueConstraint("date", name="uq_margin_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    margin_balance: Mapped[float] = mapped_column(Float)      # 融资余额
    securities_balance: Mapped[float] = mapped_column(Float)  # 融券余额
    margin_buy: Mapped[float] = mapped_column(Float)          # 融资买入额
    securities_sell: Mapped[float] = mapped_column(Float)     # 融券卖出额
    source: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class DataUpdateLog(Base):
    """数据更新日志（用于缺失/异常/延迟预警追溯）。"""

    __tablename__ = "data_update_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))  # success / failed / empty / invalid
