"""模拟交易账户。

支持模拟资金、模拟买卖、仓位变化、成本计算、持仓盈亏、历史操作记录，并与策略建议对比。
不连接真实券商账户。
"""
from __future__ import annotations

from .base import BasePage, EmptyState, PlaceholderCard, make_card_grid


class AccountPage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            title="模拟交易账户",
            subtitle="模拟资金 · 持仓 · 盈亏 · 操作记录（不连接真实券商）",
            parent=parent,
        )

        cards = [
            PlaceholderCard("模拟资金", hint="尚未设置", badge_text="待接入"),
            PlaceholderCard("持仓市值", hint="—", badge_text="待接入"),
            PlaceholderCard("持仓盈亏", hint="—", badge_text="待接入"),
            PlaceholderCard("当前仓位", hint="—", badge_text="待接入"),
        ]
        self.content_layout.addWidget(make_card_grid(cards, columns=4))

        self.content_layout.addWidget(
            EmptyState(
                title="模拟账户尚未初始化",
                description="接入后将支持设置模拟资金、模拟买入/卖出、成本计算、持仓盈亏、"
                "历史操作记录，以及与策略建议仓位的对比。",
                badge_text="待接入",
            )
        )
        self.add_stretch()
