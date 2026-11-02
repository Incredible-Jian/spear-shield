"""回测工作区界面，计算引擎在Phase 6实现。"""

import json
from pathlib import Path
import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDoubleSpinBox,
    QComboBox,
    QFormLayout,
    QPushButton,
    QFileDialog,
)
from .base import BasePage, PlaceholderCard, make_card_grid
from ..charts import MarketChart
from ..widgets import note, table


class BacktestCenterPage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__("历史回测中心", "BACKTEST / 研究参数与结果工作区", parent)
        form = QFormLayout()
        self.start = QDateEdit(QDate(2015, 1, 1))
        self.end = QDateEdit(QDate.currentDate())
        self.start.setCalendarPopup(True)
        self.end.setCalendarPopup(True)
        self.capital = QDoubleSpinBox()
        self.capital.setRange(1, 1e9)
        self.capital.setValue(100000)
        self.fee = QDoubleSpinBox()
        self.fee.setDecimals(4)
        self.fee.setRange(0, 10)
        self.fee.setSuffix(" %")
        self.slippage = QDoubleSpinBox()
        self.slippage.setDecimals(4)
        self.slippage.setRange(0, 10)
        self.slippage.setSuffix(" %")
        self.benchmark = QComboBox()
        self.benchmark.addItems(["矛与盾完整策略", "持有创业板ETF", "防守资产组合"])
        for label, field in (
            ("开始日期", self.start),
            ("结束日期", self.end),
            ("初始模拟资金", self.capital),
            ("手续费", self.fee),
            ("滑点", self.slippage),
            ("策略 / 基准", self.benchmark),
        ):
            form.addRow(label, field)
        self.content_layout.addLayout(form)
        self.run = QPushButton("运行回测 · Phase 6引擎待开发")
        self.run.setEnabled(False)
        self.content_layout.addWidget(self.run)
        save = QPushButton("导出研究参数 JSON")
        save.clicked.connect(self.save)
        self.content_layout.addWidget(save)
        self.content_layout.addWidget(
            make_card_grid(
                [
                    PlaceholderCard(n, badge_text="尚无回测")
                    for n in ("年化收益", "最大回撤", "夏普比率", "胜率 / 盈亏比")
                ],
                4,
            )
        )
        chart = MarketChart(height=210)
        chart.draw(pd.DataFrame(), title="资金曲线 / 仓位变化：尚无回测结果")
        self.content_layout.addWidget(chart)
        self.content_layout.addWidget(
            table(["成交日期", "信号日期", "标的", "方向", "价格", "数量", "费用"], 130)
        )
        self.feedback = note(
            "本阶段仅配置与结果接口，不展示虚构绩效。Phase 6将处理下一交易日成交、费用、分红和日历。"
        )
        self.content_layout.addWidget(self.feedback)

    def refresh(self):
        pass

    def save(self):
        if self.start.date() > self.end.date():
            self.feedback.setText("日期范围不合法")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出研究参数", "backtest_config.json", "JSON (*.json)"
        )
        if path:
            try:
                payload = {
                    "start": self.start.date().toString("yyyy-MM-dd"),
                    "end": self.end.date().toString("yyyy-MM-dd"),
                    "initial_capital": self.capital.value(),
                    "fee_pct": self.fee.value(),
                    "slippage_pct": self.slippage.value(),
                    "strategy": self.benchmark.currentText(),
                    "execution": "next_trading_day_open",
                    "status": "configuration_only_no_backtest",
                }
                Path(path).write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as exc:
                self.feedback.setText(f"导出失败：{exc}")
