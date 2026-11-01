"""策略信号中心。

展示 P0/P1/P2/P3 离场信号与建仓/加仓/减仓/清仓/防守切换信号。
每条信号必须给出可解释的触发原因，不允许只显示「买入/卖出」。
"""
from __future__ import annotations

from .base import BasePage, EmptyState


class SignalCenterPage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            title="策略信号中心",
            subtitle="P0-P3 离场 · 四档建仓 · 防守切换，每条信号附带触发依据",
            parent=parent,
        )

        self.content_layout.addWidget(
            EmptyState(
                title="暂无策略信号",
                description="策略引擎尚未接入。接入后将按优先级展示 P0 > P1 > P2 > P3 离场信号与四档建仓信号，"
                "每条信号均含触发条件、计算过程与执行建议。",
                badge_text="待接入",
            )
        )
        self.add_stretch()
