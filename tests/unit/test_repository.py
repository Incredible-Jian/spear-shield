"""数据仓储落库/读取测试（临时 SQLite）。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from spear_shield.database.engine import Database
from spear_shield.database.repository import (
    load_margin_daily,
    load_market_daily,
    upsert_margin_daily,
    upsert_market_daily,
)

_DAILY_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


def _daily() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "open": [10.0, 11.0],
        "high": [12.0, 13.0],
        "low": [9.0, 10.0],
        "close": [11.0, 12.0],
        "volume": [100.0, 200.0],
        "amount": [1000.0, 2000.0],
    })


def _db(tmp_path) -> Database:
    db = Database(url=f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    db.init()
    return db


def test_market_daily_roundtrip(tmp_path) -> None:
    db = _db(tmp_path)
    with db.new_session() as s:
        assert upsert_market_daily(s, "159915", "etf", _daily(), "qfq", "fake") == 2
    with db.new_session() as s:
        out = load_market_daily(s, "159915", "qfq")
    assert list(out.columns) == _DAILY_COLS
    assert len(out) == 2
    assert out["date"].iloc[0] == date(2024, 1, 2)
    assert out["close"].iloc[1] == 12.0
    db.close()


def test_market_daily_overwrites(tmp_path) -> None:
    db = _db(tmp_path)
    df = _daily()
    with db.new_session() as s:
        upsert_market_daily(s, "159915", "etf", df, "qfq", "fake")
    changed = df.copy()
    changed.loc[0, "close"] = 99.0
    with db.new_session() as s:
        upsert_market_daily(s, "159915", "etf", changed, "qfq", "fake")
    with db.new_session() as s:
        out = load_market_daily(s, "159915", "qfq")
    assert len(out) == 2  # 覆盖而非追加
    assert out["close"].iloc[0] == 99.0
    db.close()


def test_margin_daily_roundtrip(tmp_path) -> None:
    db = _db(tmp_path)
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02"]),
        "margin_balance": [1.0],
        "securities_balance": [2.0],
        "margin_buy": [3.0],
        "securities_sell": [4.0],
    })
    with db.new_session() as s:
        upsert_margin_daily(s, df, "fake")
    with db.new_session() as s:
        out = load_margin_daily(s)
    assert len(out) == 1
    assert out["margin_balance"].iloc[0] == 1.0
    db.close()
