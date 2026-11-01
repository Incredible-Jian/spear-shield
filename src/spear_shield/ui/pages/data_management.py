"""数据管理中心。

支持数据源配置、手动更新、自动定时更新、数据缓存、缺失/异常检查、更新失败提醒、历史导入与导出。
所有数据必须显示来源与更新时间；数据不可用时明确标注，绝不编造或伪装。
"""
from __future__ import annotations

from .base import BasePage, EmptyState, PlaceholderCard, make_card_grid


class DataManagementPage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            title="数据管理中心",
            subtitle="数据源配置 · 更新 · 缓存 · 质量检查 · 导入导出",
            parent=parent,
        )

        cards = [
            PlaceholderCard("数据源", hint="AkShare（待配置）", badge_text="待接入"),
            PlaceholderCard("最近更新时间", hint="—", badge_text="待接入"),
            PlaceholderCard("缺失数据", hint="质量检查待接入", badge_text="待接入"),
            PlaceholderCard("异常数据", hint="质量检查待接入", badge_text="待接入"),
        ]
        self.content_layout.addWidget(make_card_grid(cards, columns=4))

        self.content_layout.addWidget(
            EmptyState(
                title="数据引擎尚未接入",
                description="接入后将支持：数据源配置、手动/定时更新、本地缓存、缺失与异常检查、"
                "更新失败提醒、历史数据导入与 CSV/Excel 导出。数据不可用时将明确显示「数据不可用」，"
                "绝不把缓存数据伪装成实时数据。",
                badge_text="待接入",
            )
        )
        self.add_stretch()
