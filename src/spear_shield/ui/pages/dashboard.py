"""系统总览 Dashboard。

目标：让用户在 10 秒内理解当前市场环境。
Phase 1 阶段所有数据项显示「待接入」占位，不展示任何虚构行情。
"""
from __future__ import annotations

from .base import BasePage, EmptyState, PlaceholderCard, make_card_grid


class DashboardPage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            title="系统总览",
            subtitle="当前市场环境、周期趋势、五维温度与策略裁决一览",
            parent=parent,
        )

        cards = [
            PlaceholderCard("当前市场状态", badge_text="待接入"),
            PlaceholderCard("月线趋势", hint="60月线斜率待计算", badge_text="待接入"),
            PlaceholderCard("周线趋势", hint="60周线斜率待计算", badge_text="待接入"),
            PlaceholderCard("双周期共振", hint="月线 × 周线矩阵待计算", badge_text="待接入"),
            PlaceholderCard("五维宏观温度", hint="0 / 5 维可计算", badge_text="待接入"),
            PlaceholderCard("建议进攻/防守", hint="策略引擎待接入", badge_text="待接入"),
            PlaceholderCard("最高风险信号", hint="P0-P3 待接入", badge_text="待接入"),
            PlaceholderCard("数据更新时间", hint="数据引擎待接入", badge_text="待接入"),
        ]
        self.content_layout.addWidget(make_card_grid(cards, columns=4))

        self.content_layout.addWidget(
            EmptyState(
                title="最近一次策略裁决",
                description="策略引擎尚未接入。接入后将在此展示最近一次的建仓 / 加仓 / 减仓 / 清仓裁决及触发依据。",
                badge_text="待接入",
            )
        )
        self.add_stretch()
