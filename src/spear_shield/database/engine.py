"""数据库引擎与初始化。

Phase 1 仅负责：创建引擎、初始化会话工厂、建表（当前只有 schema_version）。
完整行情数据库在 Phase 2 开发。
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from ..utils.logger import get_logger
from .models import Base, SchemaVersion

logger = get_logger(__name__)


class Database:
    """轻量数据库门面，封装引擎、会话与初始化。"""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.DATABASE_URL
        self.engine: Engine = create_engine(self.url, future=True)
        self.session_factory = sessionmaker(
            bind=self.engine, future=True, expire_on_commit=False
        )

    def init(self) -> None:
        """建表并写入当前 schema 版本。"""
        from . import strategy_audit  # noqa: F401 — 注册增量表，不修改既有行情表
        from ..portfolio import paper_account  # noqa: F401 — 模拟账户增量表

        Base.metadata.create_all(self.engine)
        with self.session_factory() as session:
            self._ensure_schema_version(session)
        logger.info("数据库初始化完成：%s", self.url)

    def _ensure_schema_version(self, session: Session) -> None:
        existing = session.query(SchemaVersion).first()
        if existing is None:
            session.add(SchemaVersion(version="0.1.0"))
            session.commit()

    def new_session(self) -> Session:
        return self.session_factory()

    def close(self) -> None:
        self.engine.dispose()
