"""历史回测中心。

支持自定义时间范围、初始资金、手续费、滑点、分红与复权处理、基准对比。
严格避免未来数据泄露、前视偏差与幸存者偏差。
"""
from __future__ import annotations

from .base import BasePage, EmptyState


class BacktestCenterPage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            title="历史回测中心",
            subtitle="矛与盾完整策略 · 持有创业板ETF基准 · 防守资产组合基准",
            parent=parent,
        )

        self.content_layout.addWidget(
            EmptyState(
                title="回测引擎尚未接入",
                description="接入后将支持：自定义时间范围、初始资金、手续费/滑点、分红与复权处理、"
                "年化收益、最大回撤、夏普比率、胜率、盈亏比、资金曲线、仓位变化与逐笔交易记录。"
                "信号生成与模拟执行严格分离，周线收盘后按下一交易日可执行价格模拟成交。",
                badge_text="待接入",
            )
        )
        self.add_stretch()
