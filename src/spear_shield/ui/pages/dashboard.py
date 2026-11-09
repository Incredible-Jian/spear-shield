"""真实缓存报价与策略状态。"""

from .base import BasePage, PlaceholderCard, make_card_grid
from ..widgets import table, fill, note, display
from ..charts import MarketChart
from ...config.symbols import CORE_SYMBOLS
from ...services.market_view import quote_view
from PySide6.QtWidgets import QHBoxLayout, QPushButton


class DashboardPage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__(
            "系统总览", "ALL-WEATHER / 周期观察 · 风险裁决 · 资产配置", parent
        )
        self.controller = controller
        self.cards = [
            PlaceholderCard(t)
            for t in ("市场环境", "五维完整性", "最高级风险", "最新裁决")
        ]
        self.content_layout.addWidget(make_card_grid(self.cards, 4))
        self.summary = note("正在读取本地缓存")
        self.content_layout.addWidget(self.summary)
        controls = QHBoxLayout()
        self.update = QPushButton("更新六标的研究行情")
        self.cancel = QPushButton("取消更新")
        controls.addWidget(self.update)
        controls.addWidget(self.cancel)
        self.content_layout.addLayout(controls)
        self.feedback = note("仅主动更新时联网；失败继续显示已保存的真实缓存。")
        self.content_layout.addWidget(self.feedback)
        self.quotes = table(
            [
                "核心标的",
                "最新可用价 / 口径",
                "涨跌幅",
                "行情日期",
                "缓存写入时间",
                "完成性 / 质量",
                "来源",
            ],
            245,
        )
        self.content_layout.addWidget(self.quotes)
        self.chart = MarketChart(height=280)
        self.content_layout.addWidget(self.chart)
        self.content_layout.addWidget(
            note(
                "本地缓存不是实时订阅；正式裁决读取可追溯审计，缺失数据不视为风险已经排除。"
            )
        )
        if controller:
            self.update.clicked.connect(controller.fetch_core)
            self.cancel.clicked.connect(controller.cancel_updates)
            controller.message.connect(self.feedback.setText)
            controller.job.busy_changed.connect(self._busy_changed)
        self.refresh()

    def _busy_changed(self, busy):
        self.update.setEnabled(not busy and not self.controller.batch_active)
        self.cancel.setEnabled(busy or self.controller.batch_active)

    def refresh(self):
        if not self.controller:
            return
        c = self.controller
        latest = c.audits[0] if c.audits else None
        self.cards[0].update_value(
            "待裁决", "周期观察不等于已确认交易方向", "待确认", "warn"
        )
        self.cards[1].update_value(
            "UNKNOWN", "IV缺失 · 股债与其他定义待确认", "五维不完整", "warn"
        )
        selected = latest["decision"]["selected"] if latest else None
        self.cards[2].update_value(
            selected["rule_id"] if selected else "不可判定",
            "P0 > P1 > P2 > P3",
            "未通过完整审核",
            "warn",
        )
        self.cards[3].update_value(
            latest["decision"]["status"] if latest else "暂无记录",
            latest["snapshot"]["as_of"] if latest else "前往信号中心运行可用性诊断",
            "审计历史",
        )
        rows = []
        records = []
        for symbol in CORE_SYMBOLS:
            record = quote_view(
                symbol, c.history(symbol.code, "none"), c.history(symbol.code)
            )
            records.append(record)
            rows.append(
                [
                    symbol.name + " " + symbol.code,
                    display(record["price"]) + " / " + record["basis"],
                    (
                        f"{record['change_pct']:+.2f}%"
                        if record["change_pct"] is not None
                        else "UNKNOWN"
                    ),
                    record["date"],
                    record["updated"],
                    record["completion"]
                    + "\n"
                    + record["quality"]
                    + (" / " + "；".join(record["issues"]) if record["issues"] else ""),
                    record["source"],
                ]
            )
        fill(self.quotes, rows)
        self.quotes.resizeRowsToContents()
        self.quotes.setFixedHeight(
            self.quotes.horizontalHeader().height()
            + sum(self.quotes.rowHeight(i) for i in range(self.quotes.rowCount()))
            + 6
        )
        available = sum(r["price"] is not None for r in records)
        self.summary.setText(
            f"六标的可观察 {available}/6 · 缓存不是实时订阅，价格口径不得混用 · 五维策略仍不完整 · 模拟账户："
            + ("已初始化" if c.account["initialized"] else "未初始化")
        )
        self.cards[0].update_value(
            f"{available}/6 可观察", "两指数与四ETF，质量与日期见下表", "本地缓存"
        )
        self.update.setEnabled(not c.job.busy and not c.batch_active)
        self.cancel.setEnabled(c.job.busy or c.batch_active)
        self.chart.draw(
            c.history("159915"),
            title="159915 创业板ETF · 前复权缓存 / 最近180根",
            lines=("close",),
        )
