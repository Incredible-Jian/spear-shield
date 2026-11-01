"""双周期共振分析。

月线定战略方向，周线定交易裁决。共振矩阵：
上+上=绝对主升浪 / 上+下=牛市中期回调 / 下+上=熊市反弹 / 下+下=绝对主跌浪。
"""
from __future__ import annotations

from .base import BasePage, EmptyState, PlaceholderCard, make_card_grid


class CycleResonancePage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            title="双周期共振分析",
            subtitle="月线负责战略方向，周线负责交易裁决",
            parent=parent,
        )

        cards = [
            PlaceholderCard("月线方向", hint="60月线斜率待计算", badge_text="待接入"),
            PlaceholderCard("周线方向", hint="60周线斜率待计算", badge_text="待接入"),
            PlaceholderCard("共振象限", hint="共振矩阵待判定", badge_text="待接入"),
            PlaceholderCard("当前策略阶段", hint="建仓 / 持股 / 防守待判定", badge_text="待接入"),
        ]
        self.content_layout.addWidget(make_card_grid(cards, columns=4))

        self.content_layout.addWidget(
            EmptyState(
                title="月线 / 周线 K 线图",
                description="接入行情数据后，此区域将展示月线与周线 K 线、60月线、60周线及其斜率。",
                badge_text="待接入",
            )
        )
        self.add_stretch()
