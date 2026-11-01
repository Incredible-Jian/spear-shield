"""数据库初始化基础测试（使用临时文件数据库）。"""
from __future__ import annotations

from spear_shield.database.engine import Database
from spear_shield.database.models import SchemaVersion


def test_database_init_creates_schema(tmp_path) -> None:
    db = Database(url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    db.init()
    with db.new_session() as session:
        versions = session.query(SchemaVersion).all()
        assert len(versions) == 1
        assert versions[0].version == "0.1.0"
    db.close()


def test_database_init_idempotent(tmp_path) -> None:
    db = Database(url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    db.init()
    db.init()  # 重复初始化不应报错或重复写入版本
    with db.new_session() as session:
        assert session.query(SchemaVersion).count() == 1
    db.close()
