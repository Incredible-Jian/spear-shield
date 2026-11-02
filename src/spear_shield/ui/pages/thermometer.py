"""五维来源、公式与审计历史曲线。"""

import pandas as pd
from PySide6.QtWidgets import QComboBox
from .base import BasePage, PlaceholderCard, make_card_grid
from ..widgets import table, fill, note, display
from ..charts import MarketChart


class ThermometerPage(BasePage):
    NAMES = ("60月线斜率", "股债性价比", "风格Z-Score", "期权IV", "两融水位")
    FORMULAS = (
        "(本月MA60/上月MA60-1)×100；>0做多，≤0防守",
        "沪深300全收益/二级债基；逼近1.0阈值待确认",
        "(创业板/红利比值-156周均值)/156周标准差；±2",
        "短IV>95且长IV>80恐慌；<20且<30自满",
        "两融余额/流通市值；红线2.3%–2.5%待明确",
    )

    def __init__(self, controller=None, parent=None):
        super().__init__("五维宏观温度计", "MACRO / 指标证据 · 阈值 · 历史变化", parent)
        self.controller = controller
        self.cards = [
            PlaceholderCard(n, hint=f, badge_text="数据缺失" if i == 3 else "待确认")
            for i, (n, f) in enumerate(zip(self.NAMES, self.FORMULAS))
        ]
        self.content_layout.addWidget(make_card_grid(self.cards, 3))
        self.select = QComboBox()
        self.select.addItems(self.NAMES)
        self.content_layout.addWidget(self.select)
        self.details = table(["指标", "公式 / 阈值", "来源", "可用时间"], 190)
        self.content_layout.addWidget(self.details)
        self.chart = MarketChart(height=260)
        self.content_layout.addWidget(self.chart)
        self.content_layout.addWidget(
            note(
                "曲线只读取真实审计值。IV/股债缺失时不显示合成温度分数；未确认窗口与标的不能形成完整五维判断。"
            )
        )
        self.select.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        if not self.controller:
            return
        latest = self.controller.audits[0] if self.controller.audits else None
        dims = (
            ((latest.get("analysis") or {}).get("macro") or {}).get("dimensions", [])
            if latest
            else []
        )
        rows = []
        for i, name in enumerate(self.NAMES):
            d = dims[i] if len(dims) > i else {}
            values = d.get("value", [])
            value = (
                " / ".join(display(v) for v in values)
                if any(v is not None for v in values)
                else "—"
            )
            self.cards[i].update_value(
                value,
                self.FORMULAS[i],
                d.get("status", "数据缺失" if i == 3 else "待确认"),
                "warn",
            )
            rows.append(
                [
                    name,
                    self.FORMULAS[i],
                    ", ".join(d.get("sources", [])) or "未接入",
                    ", ".join(d.get("timestamps", [])) or "—",
                ]
            )
        fill(self.details, rows)
        idx = self.select.currentIndex()
        history = []
        for audit in reversed(self.controller.audits):
            dims = ((audit.get("analysis") or {}).get("macro") or {}).get(
                "dimensions", []
            )
            if len(dims) > idx:
                value = dims[idx].get("value", [None])[0]
                if isinstance(value, (int, float)):
                    history.append(
                        {
                            "date": pd.Timestamp(audit["snapshot"]["as_of"])
                            .tz_convert("Asia/Shanghai")
                            .date(),
                            "value": value,
                        }
                    )
        frame = (
            pd.DataFrame(history).drop_duplicates("date", keep="last")
            if history
            else pd.DataFrame()
        )
        self.chart.draw(
            frame,
            title=self.NAMES[idx] + " · 审计历史",
            lines=("value",),
            thresholds=(-2, 2) if idx == 2 else (0,) if idx == 0 else (),
        )
