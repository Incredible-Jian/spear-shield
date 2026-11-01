"""数据服务：抓取 → 校验 → 缓存 → 聚合 的编排层。

上层（指标 / 策略 / UI）只通过 DataService 取数，不感知数据源细节；
任何数据缺失或质量不过关都表现为 DataUnavailableError，绝不伪造。
"""
from __future__ import annotations

import pandas as pd

from ..config.symbols import Symbol
from ..database.engine import Database
from ..database.repository import (
    load_margin_daily,
    load_market_daily,
    log_update,
    upsert_margin_daily,
    upsert_market_daily,
)
from ..utils.logger import get_logger
from .base import DataUnavailableError
from .quality import validate_daily, validate_margin
from .registry import DataProviderRegistry
from .resample import resample_monthly, resample_weekly

logger = get_logger(__name__)


class DataService:
    """抓取、校验、缓存并聚合行情与两融数据。"""

    def __init__(self, registry: DataProviderRegistry, database: Database) -> None:
        self.registry = registry
        self.database = database

    # ---- 日线 ----

    def sync_daily(
        self, symbol: Symbol, start: str, end: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        """抓取并落库某标的日线；质量不过关抛 DataUnavailableError。"""
        df, source = self.registry.fetch_daily(symbol, start, end, adjust)
        problems = validate_daily(df)
        with self.database.new_session() as session:
            if problems:
                log_update(session, symbol.code, source, "invalid", len(df))
                raise DataUnavailableError(
                    f"{symbol.code} 数据质量校验未通过：{'；'.join(problems)}"
                )
            n = upsert_market_daily(
                session, symbol.code, symbol.asset_type, df, adjust, source
            )
            log_update(session, symbol.code, source, "success", n)
        logger.info("已同步 %s(%s) %s~%s 共 %d 条", symbol.code, adjust, start, end, len(df))
        return df

    def get_daily(
        self,
        symbol: Symbol,
        start: str,
        end: str,
        adjust: str = "qfq",
        refresh: bool = False,
    ) -> pd.DataFrame:
        """优先读缓存，覆盖不足时自动同步。"""
        start_ts, end_ts = pd.to_datetime(start), pd.to_datetime(end)
        if not refresh:
            with self.database.new_session() as session:
                cached = load_market_daily(session, symbol.code, adjust)
            if not cached.empty:
                cached["date"] = pd.to_datetime(cached["date"])
                if (
                    cached["date"].min() <= start_ts
                    and cached["date"].max() >= end_ts
                ):
                    return cached[
                        (cached["date"] >= start_ts) & (cached["date"] <= end_ts)
                    ].reset_index(drop=True)
        return self.sync_daily(symbol, start, end, adjust)

    def weekly(
        self, symbol: Symbol, start: str, end: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        return resample_weekly(self.get_daily(symbol, start, end, adjust))

    def monthly(
        self, symbol: Symbol, start: str, end: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        return resample_monthly(self.get_daily(symbol, start, end, adjust))

    # ---- 两融 ----

    def sync_margin(self, start: str, end: str) -> pd.DataFrame:
        df, source = self.registry.fetch_margin(start, end)
        problems = validate_margin(df)
        with self.database.new_session() as session:
            if problems:
                log_update(session, None, source, "invalid", len(df))
                raise DataUnavailableError(
                    f"两融数据质量校验未通过：{'；'.join(problems)}"
                )
            n = upsert_margin_daily(session, df, source)
            log_update(session, None, source, "success", n)
        return df

    def get_margin(self, start: str, end: str, refresh: bool = False) -> pd.DataFrame:
        start_ts, end_ts = pd.to_datetime(start), pd.to_datetime(end)
        if not refresh:
            with self.database.new_session() as session:
                cached = load_margin_daily(session)
            if not cached.empty:
                cached["date"] = pd.to_datetime(cached["date"])
                if cached["date"].min() <= start_ts and cached["date"].max() >= end_ts:
                    return cached[
                        (cached["date"] >= start_ts) & (cached["date"] <= end_ts)
                    ].reset_index(drop=True)
        return self.sync_margin(start, end)
