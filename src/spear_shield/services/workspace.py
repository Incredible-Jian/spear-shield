"""桌面工作区数据：本地读取、校验、导入与原子备份，不在读取时隐式联网。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid
import numpy as np
import pandas as pd

from ..config.symbols import CORE_ETFS, TRACKING_INDICES
from ..database.models import MarketDaily, DataUpdateLog
from ..database.repository import upsert_market_daily, log_update
from ..data.quality import validate_daily

SYMBOLS = {s.code: s for s in (*CORE_ETFS, *TRACKING_INDICES)}
PRICE_LABELS = {"qfq": "前复权", "none": "原始行情"}


def normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy(deep=True)
    if "amount" not in df:
        df["amount"] = np.nan
    required = ("date", "open", "high", "low", "close", "volume", "amount")
    if missing := set(required) - set(df):
        raise ValueError(f"缺少列:{sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"], errors="raise")
    if df["date"].dt.tz is not None or not df.date.eq(df.date.dt.normalize()).all():
        raise ValueError("date须为不带时区的交易日日期")
    for col in required[1:]:
        df[col] = pd.to_numeric(df[col], errors="raise")
    problems = validate_daily(df)
    if not np.isfinite(df[list(required[1:6])]).all().all():
        problems.append("OHLCV存在非有限值")
    if (df[["open", "high", "low", "close"]] <= 0).any().any() or (df.volume < 0).any():
        problems.append("价格非正或成交量为负")
    if df.amount.notna().any() and (
        (df.amount.dropna() < 0).any() or not np.isfinite(df.amount.dropna()).all()
    ):
        problems.append("成交额非法")
    if problems:
        raise ValueError("；".join(problems))
    return df[list(required)].sort_values("date").reset_index(drop=True)


class Workspace:
    def __init__(self, database):
        self.db = database

    def history(self, code, adjust="qfq") -> pd.DataFrame:
        if code not in SYMBOLS or adjust not in PRICE_LABELS:
            raise ValueError("未知标的或复权类型")
        with self.db.new_session() as session:
            rows = (
                session.query(MarketDaily)
                .filter_by(symbol_code=code, adjust=adjust)
                .order_by(MarketDaily.date)
                .all()
            )
            frame = pd.DataFrame(
                [
                    {
                        "date": r.date,
                        "open": r.open,
                        "high": r.high,
                        "low": r.low,
                        "close": r.close,
                        "volume": r.volume,
                        "amount": r.amount,
                        "source": r.source,
                        "updated_at": r.updated_at,
                        "adjust": r.adjust,
                    }
                    for r in rows
                ],
                columns=[
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "source",
                    "updated_at",
                    "adjust",
                ],
            )
            frame["date"] = pd.to_datetime(frame["date"])
            return frame

    def summary(self) -> list[dict]:
        records = []
        for code, symbol in SYMBOLS.items():
            for adjust in PRICE_LABELS:
                df = self.history(code, adjust)
                records.append(
                    {
                        "code": code,
                        "name": symbol.name,
                        "adjust": adjust,
                        "rows": len(df),
                        "latest": str(df.iloc[-1].date) if len(df) else "—",
                        "close": float(df.iloc[-1].close) if len(df) else None,
                        "source": (
                            ", ".join(sorted(set(df.source))) if len(df) else "数据缺失"
                        ),
                        "updated": (
                            str(df.updated_at.max()) + " UTC" if len(df) else "—"
                        ),
                    }
                )
        return records

    def store(self, code, adjust, frame, source):
        if code not in SYMBOLS or adjust not in PRICE_LABELS or not source.strip():
            raise ValueError("标的/复权/来源不合法")
        df = normalize_history(frame)
        if df.empty:
            raise ValueError("空数据不覆盖缓存")
        with self.db.new_session() as session:
            upsert_market_daily(
                session, code, SYMBOLS[code].asset_type, df, adjust, source
            )
            log_update(session, code, source, "success", len(df))
        return len(df)

    def failure(self, code, source, status="failed"):
        with self.db.new_session() as session:
            log_update(session, code, source, status, 0)

    def updates(self):
        with self.db.new_session() as session:
            rows = (
                session.query(DataUpdateLog)
                .order_by(DataUpdateLog.id.desc())
                .limit(100)
                .all()
            )
            return [
                {
                    "symbol": r.symbol_code,
                    "source": r.source,
                    "status": r.status,
                    "rows": r.row_count,
                    "time": str(r.finished_at) + " UTC",
                }
                for r in rows
            ]

    def backup(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        target = (
            folder
            / f"spear_shield_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.sqlite3"
        )
        with self.db.engine.connect() as connection:
            raw = connection.connection.driver_connection
            with sqlite3.connect(target) as destination:
                raw.backup(destination)
        return target
