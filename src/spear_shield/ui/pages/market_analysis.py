"""进攻与防守资产分析。

展示创业板ETF / 红利低波ETF / 短融ETF / 货币ETF 的价格走势、收益率、波动率、回撤、建议权重与模拟账户实际权重。
"""
from __future__ import annotations

from .base import BasePage, EmptyState, PlaceholderCard, make_card_grid


class MarketAnalysisPage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            title="进攻与防守资产分析",
            subtitle="创业板ETF(159915) · 红利低波ETF(563020) · 短融ETF(511360) · 货币ETF(511990)",
            parent=parent,
        )

        cards = [
            PlaceholderCard("创业板ETF 159915", hint="进攻矛 · 待接入行情", badge_text="待接入"),
            PlaceholderCard("红利低波ETF 563020", hint="防守盾 · 待接入行情", badge_text="待接入"),
            PlaceholderCard("短融ETF 511360", hint="稳健收益池 · 待接入行情", badge_text="待接入"),
            PlaceholderCard("华宝添益 511990", hint="流动性现金池 · 待接入行情", badge_text="待接入"),
        ]
        self.content_layout.addWidget(make_card_grid(cards, columns=4))

        self.content_layout.addWidget(
            EmptyState(
                title="价格走势 · 收益率 · 波动率 · 回撤 · 建议权重",
                description="接入行情数据后，此区域将展示四大资产的价格走势与风险收益指标，以及建议权重与实际权重的偏差。",
                badge_text="待接入",
            )
        )
        self.add_stretch()
