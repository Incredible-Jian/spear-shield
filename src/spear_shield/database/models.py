"""数据库 ORM 模型。

Phase 1 仅提供声明式基类与 SchemaVersion 表，用于验证 SQLite + SQLAlchemy 链路。
完整行情/指标/信号/账户模型在 Phase 2 起逐步补充。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
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
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )
