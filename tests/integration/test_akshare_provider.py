"""AkShare 真实数据源集成测试（网络不可用时自动跳过）。"""
from __future__ import annotations

import pytest

from spear_shield.config.symbols import Symbol
from spear_shield.data.akshare_provider import AkShareProvider
from spear_shield.data.quality import validate_daily, validate_margin

ETF = Symbol("159915", "创业板ETF", "etf", "进攻矛", "SZ")
INDEX = Symbol("399006", "创业板指", "index", "进攻矛跟踪指数", "SZ")


def test_fetch_etf_daily() -> None:
    provider = AkShareProvider()
    try:
        df = provider.fetch_daily(ETF, "2024-01-02", "2024-01-31")
    except Exception as exc:  # noqa: BLE001 — 网络/接口波动时跳过
        pytest.skip(f"网络或接口不可用: {exc}")
    assert not df.empty
    assert validate_daily(df) == []


def test_fetch_index_daily() -> None:
    provider = AkShareProvider()
    try:
        df = provider.fetch_daily(INDEX, "2024-01-02", "2024-01-31")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"网络或接口不可用: {exc}")
    assert not df.empty
    assert validate_daily(df) == []


def test_fetch_margin() -> None:
    provider = AkShareProvider()
    try:
        df = provider.fetch_margin("2024-01-01", "2024-01-31")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"网络或接口不可用: {exc}")
    assert not df.empty
    assert validate_margin(df) == []
