"""回测数据契约；权重 1=100%，费用和滑点为小数比例。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from typing import Mapping
from types import MappingProxyType

import pandas as pd

CORE = frozenset(("159915", "563020", "511360", "511990"))


@dataclass(frozen=True)
class BacktestConfig:
    start: date
    end: date
    initial_cash: float = 100000.0
    fee_rate: float = 0.0003
    slippage: float = 0.0005
    mode: str = "qfq_research"
    lot_size: int = 1

    def __post_init__(self):
        if (
            self.start > self.end
            or not isfinite(self.initial_cash)
            or self.initial_cash <= 0
        ):
            raise ValueError("非法日期或初始资金")
        if any(
            not isfinite(x) or not 0 <= x < 1 for x in (self.fee_rate, self.slippage)
        ):
            raise ValueError("费用/滑点须在[0,1)")
        if self.mode not in ("qfq_research", "raw_events"):
            raise ValueError("未知回测模式")
        if (
            isinstance(self.lot_size, bool)
            or not isinstance(self.lot_size, int)
            or self.lot_size < 1
        ):
            raise ValueError("交易单位须为正整数")


@dataclass(frozen=True)
class TradingCalendar:
    sessions: tuple[date, ...]
    source: str
    # 表示输入方声明的完整性，不由程序推断/认证。
    complete: bool = False

    def __post_init__(self):
        object.__setattr__(self, "sessions", tuple(self.sessions))
        if not isinstance(self.complete, bool):
            raise ValueError("日历完整性声明须为布尔值")
        if (
            not self.source.strip()
            or not self.sessions
            or tuple(sorted(set(self.sessions))) != self.sessions
        ):
            raise ValueError("日历须有来源且日期唯一升序")


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    ex_date: date
    pay_date: date
    cash_per_unit: float = 0.0  # 税后、拆分前每份现金；输入方负责税务口径
    split_ratio: float = 1.0
    source: str = ""

    def __post_init__(self):
        if (
            self.symbol not in CORE
            or self.pay_date < self.ex_date
            or not self.source.strip()
            or not isfinite(self.cash_per_unit)
            or self.cash_per_unit < 0
            or not isfinite(self.split_ratio)
            or self.split_ratio <= 0
        ):
            raise ValueError("非法分红/拆分事件")


@dataclass(frozen=True)
class MarketData:
    bars: Mapping[str, pd.DataFrame]
    calendar: TradingCalendar
    actions: tuple[CorporateAction, ...] = ()
    actions_coverage: str = ""  # 原始价模式须有覆盖本次区间的外部声明/文档引用


@dataclass(frozen=True)
class Target:
    signal_at: datetime
    weights: Mapping[str, float]
    reason: str
    available_at: datetime

    def __post_init__(self):
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        if any(
            t.tzinfo is None or t.utcoffset() is None
            for t in (self.signal_at, self.available_at)
        ):
            raise ValueError("信号和可用时间须带时区")
        if self.available_at > self.signal_at or not self.reason.strip():
            raise ValueError("信号不得使用未来证据且须有原因")
        if (
            not self.weights
            or set(self.weights) - CORE
            or any(not isfinite(w) or not 0 <= w <= 1 for w in self.weights.values())
            or sum(self.weights.values()) > 1 + 1e-12
        ):
            raise ValueError("仅限核心ETF，权重和不得超过100%")


@dataclass
class BacktestResult:
    config: BacktestConfig
    curve: pd.DataFrame
    trades: list[dict]
    orders: list[dict]
    signals: list[dict]
    metrics: dict
    metadata: dict = field(default_factory=dict)
