"""五维宏观温度计。

五维：60月线斜率 / 股债性价比 / 风格Z-Score / 期权IV / 两融水位。
依据负责人决策：
- 期权IV（D2）当前无免费数据源 → 标记「数据缺失」。
- 股债性价比（D3）标的与数据源待确认 → 标记「待确认」。
两者均不参与核弹级建仓判断。
"""
from __future__ import annotations

from .base import BasePage, EmptyState, PlaceholderCard, make_card_grid


class ThermometerPage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            title="五维宏观温度计",
            subtitle="宏观估值底 · 风格轮动 · 双周期趋势 · 期权情绪 · 两融杠杆",
            parent=parent,
        )

        cards = [
            PlaceholderCard(
                "第一维 · 60月线斜率",
                hint="(本月60月线−上月60月线)÷上月60月线",
                badge_text="待接入",
            ),
            PlaceholderCard(
                "第二维 · 股债性价比",
                hint="沪深300全收益 ÷ 二级债基（标的待确认）",
                badge_text="待确认",
            ),
            PlaceholderCard(
                "第三维 · 风格Z-Score",
                hint="(创业板/红利−156周均值)÷156周标准差",
                badge_text="待接入",
            ),
            PlaceholderCard(
                "第四维 · 期权IV双轨",
                hint="159915期权IV百分位（无免费数据源）",
                badge_text="数据缺失",
            ),
            PlaceholderCard(
                "第五维 · 两融水位",
                hint="两融余额占流通市值比",
                badge_text="待接入",
            ),
        ]
        self.content_layout.addWidget(make_card_grid(cards, columns=3))

        self.content_layout.addWidget(
            EmptyState(
                title="综合温度可视化",
                description="接入真实数据后，此区域将展示五维综合温度、历史走势图与阈值线。",
                badge_text="待接入",
            )
        )
        self.add_stretch()
