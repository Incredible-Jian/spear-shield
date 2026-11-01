"""新浪财经数据源（指数日线备援）。

仅支持沪深交易所指数（399006 等），不支持 ETF 与中证指数。
"""
from __future__ import annotations

import pandas as pd

from ..config.symbols import Symbol
from ..utils.logger import get_logger
from ..utils.retry import retry
from .base import DAILY_COLUMNS, DataProvider

logger = get_logger(__name__)


class SinaProvider(DataProvider):
    """新浪指数日线提供者（备援源）。"""

    name = "sina"

    def supports(self, symbol: Symbol) -> bool:
        return symbol.asset_type == "index" and symbol.exchange in ("SZ", "SH")

    @retry(tries=2, delay=2.0, backoff=2.0, logger=logger)
    def _fetch_index(self, symbol: Symbol) -> pd.DataFrame:
        import akshare as ak

        return ak.stock_zh_index_daily(
            symbol=f"{symbol.exchange.lower()}{symbol.code}"
        )

    def fetch_daily(
        self, symbol: Symbol, start: str, end: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        if not self.supports(symbol):
            raise NotImplementedError(
                f"新浪源不支持 {symbol.code}（{symbol.exchange}）"
            )
        raw = self._fetch_index(symbol)
        out = raw.rename(columns={
            "date": "date", "open": "open", "high": "high",
            "low": "low", "close": "close", "volume": "volume",
        })
        out["date"] = pd.to_datetime(out["date"])
        for col in ("open", "high", "low", "close", "volume"):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        if "amount" not in out.columns:
            out["amount"] = float("nan")
        out = out[out["date"].between(
            pd.to_datetime(start), pd.to_datetime(end)
        )]
        return out[list(DAILY_COLUMNS)].sort_values("date").reset_index(drop=True)

    def fetch_margin(self, start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError("新浪源不支持两融数据")
