"""核心资产池与跟踪指数定义（锁死，严禁变更）。

来源：策略文档第一章 1.1。核心可交易标的为 4 只场内 ETF，
399006 / H30269 为对应的跟踪指数，用于指标计算，不直接交易。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    """单一标的定义。"""

    code: str        # 交易/指数代码，如 "159915"
    name: str        # 中文名称
    asset_type: str  # "etf"（场内基金） | "index"（指数）
    role: str        # 在策略中的角色
    exchange: str    # "SZ" | "SH" | "CSI"（中证指数）


# 核心可交易资产（4 只 ETF，进攻/防守/收益/现金）
CORE_ETFS: tuple[Symbol, ...] = (
    Symbol("159915", "创业板ETF", "etf", "进攻矛", "SZ"),
    Symbol("563020", "红利低波ETF", "etf", "防守盾", "SH"),
    Symbol("511360", "短融ETF", "etf", "稳健收益池", "SH"),
    Symbol("511990", "华宝添益", "etf", "流动性现金池", "SH"),
)

# 跟踪指数（仅用于指标计算与研究，不进入核心交易标的池）
TRACKING_INDICES: tuple[Symbol, ...] = (
    Symbol("399006", "创业板指", "index", "进攻矛跟踪指数", "SZ"),
    Symbol("H30269", "中证红利低波", "index", "防守盾跟踪指数", "CSI"),
)

# 全部核心标的（ETF + 跟踪指数）
CORE_SYMBOLS: tuple[Symbol, ...] = CORE_ETFS + TRACKING_INDICES

# 供研究模块展示的辅助指数（不进入核心交易标的池）
AUXILIARY_INDICES: tuple[Symbol, ...] = (
    Symbol("000300", "沪深300", "index", "辅助观察", "CSI"),
)


def get_symbol(code: str) -> Symbol:
    """按代码查找标的，找不到抛出 KeyError。"""
    for s in CORE_SYMBOLS + AUXILIARY_INDICES:
        if s.code == code:
            return s
    raise KeyError(f"未知标的代码: {code}")
