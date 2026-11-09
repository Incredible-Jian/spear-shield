"""AkShare 数据源实现（主源）。

- ETF 日线：东方财富 fund_etf_hist_em（前复权）
- 指数日线：东方财富 index_zh_a_hist
- 两融日频：东方财富 stock_margin_account_info

东方财富接口存在限流，已加指数退避重试；最终失败会原样抛出，
由注册表降级或上层标记「数据不可用」。
"""

from __future__ import annotations

import pandas as pd

from ..config.symbols import Symbol
from ..utils.logger import get_logger
from ..utils.retry import retry
from .base import DAILY_COLUMNS, MARGIN_COLUMNS, DataProvider

logger = get_logger(__name__)

_EM_DAILY_RENAME = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}

_MARGIN_RENAME = {
    "日期": "date",
    "融资余额": "margin_balance",
    "融券余额": "securities_balance",
    "融资买入额": "margin_buy",
    "融券卖出额": "securities_sell",
}


def _to_yyyymmdd(value: str) -> str:
    """'YYYY-MM-DD' / 'YYYYMMDD' → 'YYYYMMDD'。"""
    return value.replace("-", "")


def _normalize_daily(df: pd.DataFrame) -> pd.DataFrame:
    """将东财/新浪原始列重命名并标准化为 DAILY_COLUMNS。"""
    out = df.rename(columns=_EM_DAILY_RENAME)
    if "date" not in out.columns:
        # 兼容新浪源英文列
        out = out.rename(columns={"date": "date"})
    out["date"] = pd.to_datetime(out["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "amount" not in out.columns:
        out["amount"] = float("nan")
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    return out[list(DAILY_COLUMNS)]


class AkShareProvider(DataProvider):
    """AkShare（东方财富为主）数据提供者。"""

    name = "akshare"

    def supports(self, symbol: Symbol) -> bool:
        return symbol.asset_type in ("etf", "index")

    @retry(tries=3, delay=2.0, backoff=2.0, logger=logger)
    def _fetch_etf(
        self, symbol: Symbol, start: str, end: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        import akshare as ak  # 延迟导入，便于测试与启动加速

        return ak.fund_etf_hist_em(
            symbol=symbol.code,
            period="daily",
            start_date=_to_yyyymmdd(start),
            end_date=_to_yyyymmdd(end),
            adjust="" if adjust == "none" else adjust,
        )

    @retry(tries=3, delay=2.0, backoff=2.0, logger=logger)
    def _fetch_index(self, symbol: Symbol, start: str, end: str) -> pd.DataFrame:
        import akshare as ak

        if symbol.code == "H30269":
            raw = ak.stock_zh_index_daily_em(symbol="csiH30269")
            dates = pd.to_datetime(raw["date"])
            return raw.loc[dates.between(pd.Timestamp(start), pd.Timestamp(end))].copy()
        return ak.index_zh_a_hist(
            symbol=symbol.code,
            period="daily",
            start_date=_to_yyyymmdd(start),
            end_date=_to_yyyymmdd(end),
        )

    def fetch_daily(
        self, symbol: Symbol, start: str, end: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        if adjust not in ("qfq", "hfq", "none"):
            raise ValueError("adjust必须为qfq/hfq/none")
        if symbol.asset_type == "etf":
            raw = self._fetch_etf(symbol, start, end, adjust)
        elif symbol.asset_type == "index":
            raw = self._fetch_index(symbol, start, end)
        else:
            raise NotImplementedError(f"不支持的资产类型: {symbol.asset_type}")
        return _normalize_daily(raw)

    @retry(tries=3, delay=2.0, backoff=2.0, logger=logger)
    def fetch_margin(self, start: str, end: str) -> pd.DataFrame:
        import akshare as ak

        raw = ak.stock_margin_account_info()
        out = raw.rename(columns=_MARGIN_RENAME)
        if "date" not in out.columns:
            raise ValueError("两融数据缺少日期列，接口可能已变更")
        out["date"] = pd.to_datetime(out["date"])
        for col in MARGIN_COLUMNS:
            if col == "date":
                continue
            if col not in out.columns:
                out[col] = float("nan")
            out[col] = pd.to_numeric(out[col], errors="coerce")

        out = out[out["date"].between(pd.to_datetime(start), pd.to_datetime(end))]
        # 若接口返回分市场多行，按日期聚合（数值求和）
        if out["date"].duplicated().any():
            out = out.groupby("date", as_index=False)[list(MARGIN_COLUMNS[1:])].sum()
        return out.sort_values("date").reset_index(drop=True)
