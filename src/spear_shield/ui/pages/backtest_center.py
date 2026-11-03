"""历史回测工作区：独立进程、本地结果与正式策略阻塞状态。"""

import json
from pathlib import Path
import sys
from uuid import uuid4
import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDoubleSpinBox,
    QComboBox,
    QFormLayout,
    QPushButton,
    QFileDialog,
    QHBoxLayout,
)
from .base import BasePage, PlaceholderCard, make_card_grid
from ..charts import MarketChart
from ..widgets import note, table, fill, display
from ..jobs import ProcessJob
from ...backtest.reporting import export_bundle


class BacktestCenterPage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__("历史回测中心", "BACKTEST / 研究参数与结果工作区", parent)
        self.controller = controller
        self.payload = None
        self.report_dir = None
        self.job = ProcessJob(self)
        self.job.timer.timeout.disconnect()
        self.job.timer.timeout.connect(lambda: self.job.cancel("回测超时；结果未载入"))
        self.job.succeeded.connect(self.completed)
        self.job.failed.connect(self.failed)
        self.job.busy_changed.connect(self.busy_changed)
        form = QFormLayout()
        other_form = QFormLayout()
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
        self.benchmark.addItems(
            [
                "矛与盾完整策略（检查阻塞项）",
                "持有创业板ETF · 研究",
                "防守固定配比 · 研究",
                "三方案对比",
            ]
        )
        self.defense = []
        for value in (60, 30, 10):
            spin = QDoubleSpinBox()
            spin.setRange(0, 100)
            spin.setValue(value)
            spin.setSuffix(" %")
            self.defense.append(spin)
        for index, (label, field) in enumerate(
            (
                ("开始日期", self.start),
                ("结束日期", self.end),
                ("初始模拟资金", self.capital),
                ("手续费", self.fee),
                ("滑点", self.slippage),
                ("策略 / 基准", self.benchmark),
            )
        ):
            (form if index < 4 else other_form).addRow(label, field)
        for name, field in zip(
            ("防守基准初始红利", "防守基准初始短融", "防守基准初始货币"), self.defense
        ):
            other_form.addRow(name, field)
        forms = QHBoxLayout()
        forms.setSpacing(24)
        forms.addLayout(form)
        forms.addLayout(other_form)
        self.content_layout.addWidget(
            note(
                "当前为前复权研究单位回测；完整策略有阻塞项时不计算其收益。防守基准是固定初始配比买入持有。"
            )
        )
        self.content_layout.addLayout(forms)
        row = QHBoxLayout()
        self.run = QPushButton("运行 / 检查方案")
        self.run.setEnabled(controller is not None)
        self.run.clicked.connect(self.execute)
        self.cancel = QPushButton("取消回测")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(
            lambda: self.job.cancel("已取消回测；不载入中间结果")
        )
        row.addWidget(self.run)
        row.addWidget(self.cancel)
        self.content_layout.addLayout(row)
        save = QPushButton("导出研究参数 JSON")
        save.clicked.connect(self.save)
        self.export = QPushButton("导出完整报告 ZIP（JSON / HTML / CSV）")
        self.export.setEnabled(False)
        self.export.clicked.connect(self.export_report)
        exports = QHBoxLayout()
        exports.addWidget(save)
        exports.addWidget(self.export)
        self.content_layout.addLayout(exports)
        self.comparison = table(
            ["方案", "状态", "累计收益", "年化收益", "最大回撤", "夏普", "成交次数"],
            150,
        )
        self.content_layout.addWidget(self.comparison)
        self.cards = [
            PlaceholderCard(n, badge_text="尚无回测")
            for n in ("年化收益", "最大回撤", "夏普比率", "胜率 / 盈亏比")
        ]
        self.content_layout.addWidget(make_card_grid(self.cards, 4))
        self.chart = MarketChart(height=240)
        self.allocation = MarketChart(height=190)
        self.chart.draw(pd.DataFrame(), title="资金曲线：尚无回测结果")
        self.allocation.draw(pd.DataFrame(), title="仓位变化：尚无回测结果")
        self.content_layout.addWidget(self.chart)
        self.content_layout.addWidget(self.allocation)
        self.trades = table(
            ["成交日期", "信号时间", "标的", "方向", "价格", "研究单位数量", "费用"],
            180,
        )
        self.content_layout.addWidget(self.trades)
        self.feedback = note(
            "基准使用前复权研究单位、开盘模拟成交，不是真实份额。固定防守基准为初始买入持有，非当前策略配比。"
            "完整策略缺规则确认/历史数据时只列阻塞项，不显示0收益。图表显示全区间，报告保存在独立数据目录。"
        )
        self.content_layout.addWidget(self.feedback)

    def refresh(self):
        pass

    def request(self):
        if self.start.date() > self.end.date():
            raise ValueError("日期范围不合法")
        weights = dict(
            zip(("563020", "511360", "511990"), (s.value() / 100 for s in self.defense))
        )
        if abs(sum(weights.values()) - 1) > 1e-9:
            raise ValueError("防守基准权重须合计100%")
        return {
            "start": self.start.date().toString("yyyy-MM-dd"),
            "end": self.end.date().toString("yyyy-MM-dd"),
            "initial_cash": self.capital.value(),
            "fee_rate": self.fee.value() / 100,
            "slippage": self.slippage.value() / 100,
            "selection": ("strategy", "attack", "defense", "comparison")[
                self.benchmark.currentIndex()
            ],
            "defense_weights": weights,
            "mode": "qfq_research",
        }

    def execute(self):
        try:
            request = self.request()
            folder = self.controller.data_dir / "backtests"
            folder.mkdir(parents=True, exist_ok=True)
            request.update(
                database=str(self.controller.database.engine.url.database),
                output_dir=str(folder),
            )
            path = folder / f"request_{uuid4().hex}.json"
            path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            self.payload = None
            self.report_dir = None
            self.export.setEnabled(False)
            self.render_empty()
            self.feedback.setText(
                "正在独立进程读取缓存并运行回测；可切换页面或取消。无隐式联网。"
            )
            self.job.start(
                sys.executable,
                ["-m", "spear_shield.backtest.worker", str(path)],
                timeout_ms=120000,
            )
        except Exception as exc:
            self.failed(str(exc))

    def busy_changed(self, busy):
        self.run.setEnabled(not busy and self.controller is not None)
        self.cancel.setEnabled(busy)

    def failed(self, message):
        from ...utils.logger import get_logger

        get_logger(__name__).warning("回测失败：%s", message)
        self.feedback.setText(f"回测未完成：{message}")

    def render_empty(self):
        fill(self.trades, [])
        fill(self.comparison, [])
        for card in self.cards:
            card.update_value("—", "无可计算结果", "待计算")
        self.chart.draw(pd.DataFrame(), title="无资金曲线")
        self.allocation.draw(pd.DataFrame(), title="无仓位曲线")

    def completed(self, response):
        self.payload = response["data"]
        self.report_dir = response["report_dir"]
        self.export.setEnabled(True)
        rows, messages, results = [], [], []
        pct = lambda v: "—" if v is None else f"{v:.2%}"
        for item in self.payload["runs"]:
            result = item["result"]
            metrics = result["metrics"] if result else {}
            status = (
                "部分区间研究"
                if item["status"] == "partial_research"
                else "仅研究" if result else "阻塞"
            )
            rows.append(
                [
                    item["name"],
                    status,
                    pct(metrics.get("total_return")),
                    pct(metrics.get("annual_return")),
                    pct(metrics.get("max_drawdown")),
                    display(metrics.get("sharpe")),
                    metrics.get("trade_count", "—"),
                ]
            )
            messages.extend(f"{item['name']}：{b}" for b in item["blockers"])
            if result:
                messages.append(
                    f"{item['name']}：{result['metadata'].get('coverage_note', '')}"
                )
                results.append(result)
        fill(self.comparison, rows)
        if results:
            result = results[0]
            metrics = result["metrics"]
            values = [
                pct(metrics["annual_return"]),
                pct(metrics["max_drawdown"]),
                display(metrics["sharpe"]),
                f"{pct(metrics['win_rate'])} / {display(metrics['payoff_ratio'])}",
            ]
            for card, value in zip(self.cards, values):
                card.update_value(
                    value,
                    "首个可计算方案；夏普Rf=0 / 年252日",
                    (
                        "部分区间"
                        if result["metadata"].get("coverage_partial", False)
                        else "仅研究"
                    ),
                )
            curve = None
            columns = []
            for i, r in enumerate(results):
                df = pd.DataFrame(r["curve"])
                df["date"] = pd.to_datetime(df.date)
                col = f"方案{i+1}净值"
                columns.append(col)
                current = df[["date", "equity"]].rename(columns={"equity": col})
                current[col] /= r["config"]["initial_cash"]
                curve = (
                    current
                    if curve is None
                    else curve.merge(current, on="date", how="outer")
                )
            self.chart.draw(
                curve.sort_values("date"),
                title="全区间研究净值对比（方案顺序见上表）",
                lines=columns,
                max_points=None,
            )
            df = pd.DataFrame(result["curve"])
            df["date"] = pd.to_datetime(df.date)
            cols = [c for c in df if c.startswith("weight_")]
            self.allocation.draw(
                df,
                title="首个成功研究方案 · 全区间实际权重（1=100%）",
                lines=cols,
                max_points=None,
            )
            fill(
                self.trades,
                [
                    [
                        t["date"],
                        t["signal_at"],
                        t["symbol"],
                        t["side"],
                        t["price"],
                        t["quantity"],
                        t["fee"],
                    ]
                    for r in results
                    for t in r["trades"]
                ],
            )
            messages.extend(result["metadata"]["limitations"])
        self.feedback.setText("\n".join([f"报告已保存：{self.report_dir}", *messages]))

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出回测研究报告", "backtest_report.zip", "ZIP (*.zip)"
        )
        if path and self.report_dir:
            try:
                export_bundle(self.report_dir, path)
                self.feedback.setText(f"完整研究报告已导出：{path}")
            except Exception as exc:
                self.failed(str(exc))

    def save(self):
        if self.start.date() > self.end.date():
            self.feedback.setText("日期范围不合法")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出研究参数", "backtest_config.json", "JSON (*.json)"
        )
        if path:
            try:
                payload = self.request()
                Path(path).write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as exc:
                self.feedback.setText(f"导出失败：{exc}")
