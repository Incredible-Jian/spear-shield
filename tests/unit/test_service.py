"""数据服务编排测试：缓存、刷新、质量拦截（用假注册表 + 临时库）。"""
from __future__ import annotations

import pandas as pd
import pytest

from spear_shield.config.symbols import Symbol
from spear_shield.data.base import DataProvider, DataUnavailableError
from spear_shield.data.registry import DataProviderRegistry
from spear_shield.data.service import DataService
from spear_shield.database.engine import Database
from spear_shield.database.models import DataUpdateLog

SYM = Symbol("159915", "创业板ETF", "etf", "进攻矛", "SZ")


def _daily(start: str, end: str) -> pd.DataFrame:
    dates = pd.bdate_range(start, end)
    n = len(dates)
    return pd.DataFrame({
        "date": dates,
        "open": [1.0] * n, "high": [1.2] * n, "low": [0.9] * n,
        "close": [1.1] * n, "volume": [100.0] * n, "amount": [1000.0] * n,
    })


def _bad_daily(start: str, end: str) -> pd.DataFrame:
    df = _daily(start, end)
    df.loc[0, "high"] = 0.5  # high < low → 触发质量拦截
    return df


class Fake(DataProvider):
    name = "fake"

    def __init__(self, daily=None):
        self.calls = 0
        self._daily = daily or _daily

    def fetch_daily(self, symbol, start, end, adjust="qfq") -> pd.DataFrame:
        self.calls += 1
        return self._daily(start, end)

    def fetch_margin(self, start, end) -> pd.DataFrame:
        raise NotImplementedError


def _service(tmp_path, provider: Fake) -> tuple[DataService, Database]:
    db = Database(url=f"sqlite:///{(tmp_path / 's.db').as_posix()}")
    db.init()
    return DataService(DataProviderRegistry([provider]), db), db


def test_get_daily_caches(tmp_path) -> None:
    provider = Fake()
    svc, db = _service(tmp_path, provider)
    first = svc.get_daily(SYM, "2024-01-01", "2024-01-31")
    second = svc.get_daily(SYM, "2024-01-01", "2024-01-31")
    assert len(first) == len(second)
    assert provider.calls == 1  # 第二次命中缓存
    db.close()


def test_refresh_forces_refetch(tmp_path) -> None:
    provider = Fake()
    svc, db = _service(tmp_path, provider)
    svc.get_daily(SYM, "2024-01-01", "2024-01-31")
    svc.get_daily(SYM, "2024-01-01", "2024-01-31", refresh=True)
    assert provider.calls == 2
    db.close()


def test_invalid_daily_rejected_and_logged(tmp_path) -> None:
    provider = Fake(daily=_bad_daily)
    svc, db = _service(tmp_path, provider)
    with pytest.raises(DataUnavailableError):
        svc.sync_daily(SYM, "2024-01-01", "2024-01-31")
    with db.new_session() as s:
        statuses = [r.status for r in s.query(DataUpdateLog).all()]
    assert statuses == ["invalid"]
    db.close()


def test_weekly_and_monthly(tmp_path) -> None:
    provider = Fake()
    svc, db = _service(tmp_path, provider)
    w = svc.weekly(SYM, "2024-01-01", "2024-01-31")
    m = svc.monthly(SYM, "2024-01-01", "2024-01-31")
    assert not w.empty and not m.empty
    assert list(w.columns) == list(m.columns)
    assert "amount" in w.columns
    db.close()
