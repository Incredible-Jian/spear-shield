"""数据源抽象接口与标准化 schema。

核心策略只依赖本接口，绝不直接 import 任何数据供应商，
保证数据源可替换、失败可降级。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Final

import pandas as pd

from ..config.symbols import Symbol

# 标准化日线列（amount 可能为 NaN，取决于数据源）
DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "date", "open", "high", "low", "close", "volume", "amount",
)

# 标准化两融日频列
MARGIN_COLUMNS: Final[tuple[str, ...]] = (
    "date", "margin_balance", "securities_balance",
    "margin_buy", "securities_sell",
)


class DataUnavailableError(RuntimeError):
    """所有数据源均不可用时抛出。上层据此展示「数据不可用」，绝不伪造。"""


class DataProvider(ABC):
    """数据提供者抽象基类。

    子类按能力覆写相应方法；未支持的方法抛 NotImplementedError。
    """

    name: str = "base"

    def supports(self, symbol: Symbol) -> bool:
        """是否支持获取该标的的日线。"""
        return True

    @abstractmethod
    def fetch_daily(
        self, symbol: Symbol, start: str, end: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        """获取标准化日线，返回 DAILY_COLUMNS 列。"""

    @abstractmethod
    def fetch_margin(self, start: str, end: str) -> pd.DataFrame:
        """获取两融日频数据，返回 MARGIN_COLUMNS 列。"""
