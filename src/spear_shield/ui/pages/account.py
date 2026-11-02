"""模拟账户持久记账与原始缓存估值。"""

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
)
from .base import BasePage, PlaceholderCard, make_card_grid
from ..widgets import table, fill, note, display
from ...config.symbols import CORE_ETFS
from ...portfolio.paper_account import initialize, trade
from ..charts import AllocationChart


class AccountPage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__(
            "模拟交易账户", "PAPER / 手工记账 · 现金 · 成本 · 持仓 · 历史", parent
        )
        self.controller = controller
        self.cards = [
            PlaceholderCard(n)
            for n in ("可用现金", "持仓市值", "模拟总权益", "累计盈亏")
        ]
        self.content_layout.addWidget(make_card_grid(self.cards, 4))
        row = QHBoxLayout()
        self.initial = QDoubleSpinBox()
        self.initial.setRange(1, 1e9)
        self.initial.setValue(100000)
        self.initial.setPrefix("初始资金 ¥ ")
        self.create = QPushButton("初始化模拟账户")
        row.addWidget(self.initial)
        row.addWidget(self.create)
        self.content_layout.addLayout(row)
        form = QHBoxLayout()
        self.symbol = QComboBox()
        self.symbol.addItems([s.code + " " + s.name for s in CORE_ETFS])
        self.qty = QSpinBox()
        self.qty.setRange(1, 10**7)
        self.qty.setValue(100)
        self.qty.setPrefix("份额 ")
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 1e6)
        self.price.setDecimals(4)
        self.price.setPrefix("手工模拟价 ")
        self.fee = QDoubleSpinBox()
        self.fee.setDecimals(4)
        self.fee.setRange(0, 1e6)
        self.fee.setPrefix("费用 ")
        for w in (self.symbol, self.qty, self.price, self.fee):
            form.addWidget(w)
        self.content_layout.addLayout(form)
        actions = QHBoxLayout()
        self.buy = QPushButton("模拟买入")
        self.sell = QPushButton("模拟卖出")
        actions.addWidget(self.buy)
        actions.addWidget(self.sell)
        actions.addStretch()
        self.content_layout.addLayout(actions)
        self.feedback = note("")
        self.content_layout.addWidget(self.feedback)
        allocations = QHBoxLayout()
        self.actual_chart = AllocationChart()
        self.suggested_chart = AllocationChart()
        allocations.addWidget(self.actual_chart)
        allocations.addWidget(self.suggested_chart)
        self.content_layout.addLayout(allocations)
        self.positions = table(
            ["标的", "份额", "平均成本", "原始价市值", "持仓盈亏", "行情日期"], 160
        )
        self.trades = table(
            [
                "记录时间 UTC",
                "标的",
                "方向",
                "份额",
                "手工模拟价",
                "费用",
                "已实现盈亏",
            ],
            200,
        )
        self.content_layout.addWidget(self.positions)
        self.content_layout.addWidget(self.trades)
        self.content_layout.addWidget(
            note(
                "手工模拟价由你输入，不代表市场成交。只用原始缓存估值，缺价不填补。未校验T+1、申报单位和分红；不连接券商。正式策略仍受确认项阻塞。"
            )
        )
        self.create.clicked.connect(self.initialize)
        self.buy.clicked.connect(lambda: self.order("buy"))
        self.sell.clicked.connect(lambda: self.order("sell"))
        self.refresh()

    def initialize(self):
        try:
            with self.controller.database.new_session() as session:
                initialize(session, self.initial.value())
                session.commit()
            self.controller.refresh()
            self.refresh()
            self.feedback.setText("模拟账户已创建并持久保存")
        except Exception as exc:
            self.feedback.setText(str(exc))

    def order(self, side):
        try:
            with self.controller.database.new_session() as session:
                trade(
                    session,
                    self.symbol.currentText().split()[0],
                    side,
                    self.qty.value(),
                    self.price.value(),
                    self.fee.value(),
                )
                session.commit()
            self.controller.refresh()
            self.refresh()
            self.feedback.setText("已记录模拟操作，无真实订单")
        except Exception as exc:
            self.feedback.setText(str(exc))

    def refresh(self):
        if not self.controller:
            return
        a = self.controller.account
        ready = a["initialized"]
        if ready:
            self.initial.setValue(a["initial"])
        self.create.setEnabled(not ready)
        self.initial.setEnabled(not ready)
        self.buy.setEnabled(ready)
        self.sell.setEnabled(ready)
        values = (
            a.get("cash"),
            a.get("market_value"),
            a.get("equity"),
            a["equity"] - a["initial"] if a.get("equity") is not None else None,
        )
        for card, value in zip(self.cards, values):
            card.update_value(
                display(value),
                "原始缓存估值，非实时" if ready else "尚未设置模拟资金",
                "模拟" if ready else "未初始化",
            )
        fill(
            self.positions,
            [
                [
                    h[k]
                    for k in (
                        "code",
                        "quantity",
                        "average",
                        "value",
                        "pnl",
                        "quote_date",
                    )
                ]
                for h in a["holdings"]
            ],
        )
        fill(
            self.trades,
            [
                [
                    r[k]
                    for k in (
                        "time",
                        "code",
                        "side",
                        "quantity",
                        "price",
                        "fee",
                        "realized",
                    )
                ]
                for r in a["trades"]
            ],
        )
        actual = {}
        if a.get("equity"):
            actual = {h["code"]: h["value"] / a["equity"] for h in a["holdings"]}
            actual["现金"] = a["cash"] / a["equity"]
        self.actual_chart.draw(
            actual,
            (
                "模拟实际配置 · 原始缓存价"
                if actual
                else "模拟配置：账户未建或原始估值缺失"
            ),
        )
        latest = self.controller.audits[0] if self.controller.audits else None
        defense = (
            ((latest.get("analysis") or {}).get("defense") or {}) if latest else {}
        )
        weights = defense.get("weights") or {}
        if defense.get("unallocated"):
            weights = {**weights, "待分配": defense["unallocated"]}
        self.suggested_chart.draw(
            weights, "防守端内部建议 / " + defense.get("status", "待确认")
        )
