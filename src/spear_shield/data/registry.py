"""数据源注册表：按优先级路由，失败自动降级到备援源。

所有源均失败时抛 DataUnavailableError，绝不伪造数据。
"""
from __future__ import annotations

import pandas as pd

from ..config.symbols import Symbol
from ..utils.logger import get_logger
from .base import DataProvider, DataUnavailableError

logger = get_logger(__name__)


class DataProviderRegistry:
    """按优先级依次尝试多个数据提供者。"""

    def __init__(self, providers: list[DataProvider]) -> None:
        self.providers = providers

    def fetch_daily(
        self, symbol: Symbol, start: str, end: str, adjust: str = "qfq"
    ) -> tuple[pd.DataFrame, str]:
        errors: list[str] = []
        for provider in self.providers:
            if not provider.supports(symbol):
                continue
            try:
                df = provider.fetch_daily(symbol, start, end, adjust)
                if df.empty:
                    errors.append(f"{provider.name}: 返回空数据")
                    continue
                return df, provider.name
            except Exception as exc:  # noqa: BLE001 — 降级逻辑需捕获任意源异常
                logger.warning(
                    "数据源 %s 获取 %s 失败: %s", provider.name, symbol.code, exc
                )
                errors.append(f"{provider.name}: {exc}")
        raise DataUnavailableError(
            f"无法获取 {symbol.code} 日线：{'；'.join(errors) or '无可用数据源'}"
        )

    def fetch_margin(self, start: str, end: str) -> tuple[pd.DataFrame, str]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                df = provider.fetch_margin(start, end)
                if df.empty:
                    errors.append(f"{provider.name}: 返回空数据")
                    continue
                return df, provider.name
            except NotImplementedError:
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("数据源 %s 获取两融失败: %s", provider.name, exc)
                errors.append(f"{provider.name}: {exc}")
        raise DataUnavailableError(
            f"无法获取两融数据：{'；'.join(errors) or '无可用数据源'}"
        )
