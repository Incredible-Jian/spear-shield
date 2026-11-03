"""历史回测：数据契约、执行引擎及基准研究。"""

from .engine import BacktestEngine
from .models import (
    BacktestConfig,
    BacktestResult,
    CorporateAction,
    MarketData,
    Target,
    TradingCalendar,
)

__all__ = [
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
    "CorporateAction",
    "MarketData",
    "Target",
    "TradingCalendar",
]
