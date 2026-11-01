"""数据源注册表：优先级、降级、来源追踪测试（用假提供者）。"""
from __future__ import annotations

import pandas as pd
import pytest

from spear_shield.config.symbols import Symbol
from spear_shield.data.base import DataProvider, DataUnavailableError
from spear_shield.data.registry import DataProviderRegistry

SYM = Symbol("159915", "创业板ETF", "etf", "进攻矛", "SZ")


def _daily() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "open": [1.0, 1.1],
        "high": [1.2, 1.3],
        "low": [0.9, 1.0],
        "close": [1.1, 1.2],
        "volume": [100.0, 200.0],
        "amount": [1000.0, 2000.0],
    })


class Fake(DataProvider):
    def __init__(self, name, *, fail=False, supports=True, margin_fail=False):
        self.name = name
        self._fail = fail
        self._supports = supports
        self._margin_fail = margin_fail

    def supports(self, symbol: Symbol) -> bool:
        return self._supports

    def fetch_daily(self, symbol, start, end, adjust="qfq") -> pd.DataFrame:
        if self._fail:
            raise RuntimeError("boom")
        return _daily()

    def fetch_margin(self, start, end) -> pd.DataFrame:
        if self._margin_fail:
            raise NotImplementedError("不支持两融")
        return pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02"]),
            "margin_balance": [1.0],
            "securities_balance": [2.0],
            "margin_buy": [3.0],
            "securities_sell": [4.0],
        })


def test_uses_first_provider() -> None:
    reg = DataProviderRegistry([Fake("a"), Fake("b")])
    _, source = reg.fetch_daily(SYM, "2024-01-01", "2024-01-31")
    assert source == "a"


def test_failover_to_second() -> None:
    reg = DataProviderRegistry([Fake("a", fail=True), Fake("b")])
    _, source = reg.fetch_daily(SYM, "2024-01-01", "2024-01-31")
    assert source == "b"


def test_skips_unsupported() -> None:
    reg = DataProviderRegistry([Fake("a", supports=False), Fake("b")])
    _, source = reg.fetch_daily(SYM, "2024-01-01", "2024-01-31")
    assert source == "b"


def test_all_fail_raises() -> None:
    reg = DataProviderRegistry([Fake("a", fail=True), Fake("b", fail=True)])
    with pytest.raises(DataUnavailableError):
        reg.fetch_daily(SYM, "2024-01-01", "2024-01-31")


def test_margin_skips_not_implemented() -> None:
    reg = DataProviderRegistry([Fake("a", margin_fail=True), Fake("b")])
    _, source = reg.fetch_margin("2024-01-01", "2024-01-31")
    assert source == "b"
