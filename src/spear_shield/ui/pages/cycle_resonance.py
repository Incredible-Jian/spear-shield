"""周/月观察图及正式矩阵状态。"""

import pandas as pd
from PySide6.QtWidgets import QComboBox
from .base import BasePage, PlaceholderCard, make_card_grid
from ..charts import MarketChart
from ..widgets import table, fill, note, display
from ...data.resample import resample_weekly, resample_monthly
from ...indicators.engine import IndicatorEngine


class CycleResonancePage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__(
            "双周期共振", "CYCLES / 60月线战略方向 · 60周线交易裁决", parent
        )
        self.controller = controller
        self.cards = [
            PlaceholderCard(n)
            for n in ("月线MA60斜率观察", "周线MA60斜率观察", "正式共振象限")
        ]
        self.content_layout.addWidget(make_card_grid(self.cards, 3))
        self.select = QComboBox()
        self.select.addItems(["399006 创业板指", "159915 创业板ETF"])
        self.content_layout.addWidget(self.select)
        self.matrix = table(["月线", "周线", "原文共振矩阵"], 120)
        fill(
            self.matrix,
            [
                ["向上", "向上", "绝对主升浪"],
                ["向上", "向下", "牛市中期回调"],
                ["向下", "向上", "熊市反弹中继"],
                ["向下", "向下", "绝对主跌浪"],
            ],
        )
        self.content_layout.addWidget(self.matrix)
        self.week = MarketChart(height=280)
        self.month = MarketChart(height=280)
        self.content_layout.addWidget(self.week)
        self.content_layout.addWidget(self.month)
        self.content_layout.addWidget(
            note(
                "按已有缓存聚合，末根可能未完结且交易日覆盖尚未确认；观察数值不作为正式周/月裁决。"
            )
        )
        self.select.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        if not self.controller:
            return
        code = self.select.currentText().split()[0]
        df = self.controller.history(code)
        for label, period, aggregate, chart in (
            ("周", "week", resample_weekly, self.week),
            ("月", "month", resample_monthly, self.month),
        ):
            bars = aggregate(df) if len(df) else df
            values = IndicatorEngine(period).compute(bars).data if len(bars) else bars
            slope = values.iloc[-1].slope_ma60 if len(values) else None
            self.cards[0 if period == "month" else 1].update_value(
                display(slope) + "%" if slope is not None and pd.notna(slope) else "—",
                "仅观察；预热不足为—",
                "非正式裁决",
            )
            chart.draw(
                values,
                title=f"{code} {label}K / MA60 · 观察图",
                candles=True,
                lines=("ma60",),
            )
        latest = self.controller.audits[0] if self.controller.audits else None
        cycle = (
            ((latest.get("analysis") or {}).get("cycle") or {}).get("status")
            if latest
            else None
        )
        self.cards[2].update_value(
            cycle or "待确认",
            "信号序列/周线方向需确认；观察图不推导象限",
            "正式状态",
            "warn",
        )
