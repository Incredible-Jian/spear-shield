"""模拟账户持久记账与原始缓存估值。"""

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
    QCheckBox,
)
from .base import BasePage, PlaceholderCard, make_card_grid
from ..widgets import table, fill, note, display
from ...config.symbols import CORE_ETFS
from ...portfolio.paper_account import initialize, trade
from ..charts import AllocationChart
from ..charts import MarketChart
from ...portfolio.paper_execution import (
    execute_reference_order,
    cancel_order,
    mark_equity,
    record_manual_order,
    adopt_legacy_account,
)
import pandas as pd
import uuid


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
        self.buy.setText("手工记账买入（价格未核验）")
        self.sell.setText("手工记账卖出（价格未核验）")
        actions.addWidget(self.buy)
        actions.addWidget(self.sell)
        actions.addStretch()
        self.content_layout.addLayout(actions)
        model = QHBoxLayout()
        self.market_buy = QPushButton("原始缓存参考价模拟买入")
        self.market_sell = QPushButton("原始缓存参考价模拟卖出")
        self.refresh_raw = QPushButton("更新所选原始行情")
        for widget in (self.market_buy, self.market_sell, self.refresh_raw):
            model.addWidget(widget)
        self.content_layout.addLayout(model)
        options = QHBoxLayout()
        self.allow_intraday = QCheckBox("明确允许未收盘参考价（不用于周裁决）")
        self.allow_failed = QCheckBox("明确确认更新失败后使用有日期标签的缓存")
        self.fill_limit = QSpinBox()
        self.fill_limit.setRange(0, 10**7)
        self.fill_limit.setPrefix("本次模拟份额上限（0=全部） ")
        for w in (self.allow_intraday, self.allow_failed, self.fill_limit):
            options.addWidget(w)
        self.content_layout.addLayout(options)
        self.content_layout.addWidget(
            note(
                "缓存模型费率0.03%、滑点0.05%，沿用已有研究参数；部分成交上限是用户模拟假设，不代表真实流动性。缺价/过期不自动切换手工价。"
            )
        )
        self.feedback = note("")
        self.content_layout.addWidget(self.feedback)
        allocations = QHBoxLayout()
        self.actual_chart = AllocationChart()
        self.suggested_chart = AllocationChart()
        allocations.addWidget(self.actual_chart)
        allocations.addWidget(self.suggested_chart)
        self.content_layout.addLayout(allocations)
        self.positions = table(
            [
                "标的",
                "份额",
                "平均成本",
                "最新原始价",
                "原始价市值",
                "浮动盈亏",
                "行情日期",
                "来源",
            ],
            160,
        )
        self.trades = table(
            [
                "记录时间 UTC",
                "标的",
                "方向",
                "份额",
                "模拟记账价",
                "费用",
                "已实现盈亏",
            ],
            200,
        )
        self.content_layout.addWidget(self.positions)
        self.content_layout.addWidget(self.trades)
        self.orders = table(
            [
                "订单ID",
                "状态",
                "标的/方向",
                "计划/成交份额",
                "参考行情日/来源",
                "模型记账价",
                "费用/滑点",
                "原因",
            ],
            210,
        )
        self.content_layout.addWidget(self.orders)
        self.fills = table(
            [
                "模拟成交ID",
                "订单ID",
                "模拟时间",
                "标的/方向",
                "成交份额",
                "参考 / 模型价",
                "行情日/来源",
                "手续费 / 滑点",
            ],
            190,
        )
        self.content_layout.addWidget(self.fills)
        controls = QHBoxLayout()
        self.retry = QPushButton("重试选中未完成模拟订单")
        self.cancel_order = QPushButton("取消选中剩余意图")
        self.save_mark = QPushButton("保存当前账户估值快照")
        self.adopt = QPushButton("确认旧账户当前状态（不回填历史）")
        for w in (self.retry, self.cancel_order, self.save_mark, self.adopt):
            controls.addWidget(w)
        self.content_layout.addLayout(controls)
        self.equity_chart = MarketChart(height=220)
        self.content_layout.addWidget(self.equity_chart)
        self.execution_summary = note("已实现盈亏 / 费用 / 滑点 / 收益率：账户未初始化")
        self.content_layout.addWidget(self.execution_summary)
        self.content_layout.addWidget(
            note(
                "手工按钮明确使用用户输入的未核验价格；缓存模型按钮只读原始价，不因缺价自动降级。两者均非真实成交。模型对股票ETF施加T+1约束，不含完整公司行动、申报单位或盘口；不连接券商。"
            )
        )
        self.create.clicked.connect(self.initialize)
        self.buy.clicked.connect(lambda: self.order("buy"))
        self.sell.clicked.connect(lambda: self.order("sell"))
        self.market_buy.clicked.connect(lambda: self.market_order("buy"))
        self.market_sell.clicked.connect(lambda: self.market_order("sell"))
        self.refresh_raw.clicked.connect(
            lambda: self.controller.fetch(
                self.symbol.currentText().split()[0],
                "2010-01-01",
                pd.Timestamp.now(tz="Asia/Shanghai").date().isoformat(),
                "none",
            )
        )
        self.retry.clicked.connect(self.retry_order)
        self.cancel_order.clicked.connect(self.cancel_selected)
        self.save_mark.clicked.connect(self.mark)
        self.adopt.clicked.connect(self.adopt_legacy)
        self.refresh()

    def initialize(self):
        try:
            with self.controller.database.new_session() as session:
                initialize(session, self.initial.value())
                mark_equity(session, self.controller.workspace)
                session.commit()
            self.controller.refresh()
            self.refresh()
            self.feedback.setText("模拟账户已创建并持久保存")
        except Exception as exc:
            self.feedback.setText(str(exc))

    def order(self, side):
        try:
            with self.controller.database.new_session() as session:
                record_manual_order(
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

    def market_order(self, side):
        self._execute(
            self.symbol.currentText().split()[0],
            side,
            self.qty.value(),
            allow_intraday=self.allow_intraday.isChecked(),
            allow_failed_cache=self.allow_failed.isChecked(),
        )

    def _execute(self, code, side, quantity, **options):
        try:
            with self.controller.database.new_session() as session:
                order = execute_reference_order(
                    session,
                    self.controller.workspace,
                    code,
                    side,
                    quantity,
                    max_fill_quantity=self.fill_limit.value() or None,
                    **options,
                )
                session.commit()
            self.controller.refresh()
            self.refresh()
            self.feedback.setText(
                f"模拟订单 {order['id']} / {order['status']}：{order['reason']}"
            )
        except Exception as exc:
            self.feedback.setText("模拟失败，事务未完成：" + str(exc))

    def selected_order(self):
        row = self.orders.currentRow()
        return (
            self.controller.paper_history["orders"][row]
            if 0 <= row < len(self.controller.paper_history["orders"])
            else None
        )

    def retry_order(self):
        order = self.selected_order()
        if not order:
            return
        r = order["request"]
        if r["execution_model"] != "cache-reference-simulation-v1":
            return
        self._execute(
            r["code"],
            r["side"],
            r["quantity"],
            fee_rate=r["fee_rate"],
            slippage=r["slippage"],
            allow_intraday=r["allow_intraday"],
            allow_failed_cache=r.get("allow_failed_cache", False),
            order_id=order["id"],
            attempt_id=uuid.uuid4().hex,
        )

    def cancel_selected(self):
        order = self.selected_order()
        if not order:
            return
        with self.controller.database.new_session() as session:
            result = cancel_order(session, order["id"])
            session.commit()
        self.controller.refresh()
        self.refresh()
        self.feedback.setText(
            "当前模拟订单状态：" + result["status"] + "；已成交部分没有回滚"
        )

    def mark(self):
        try:
            with self.controller.database.new_session() as session:
                mark_equity(session, self.controller.workspace)
                session.commit()
            self.controller.refresh()
            self.refresh()
        except Exception as exc:
            self.feedback.setText(str(exc))

    def adopt_legacy(self):
        try:
            with self.controller.database.new_session() as s:
                adopt_legacy_account(s)
                s.commit()
            self.feedback.setText(
                "已确认当前状态为可知起点；历史资金、持仓和交易没有重置"
            )
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
        self.market_buy.setEnabled(ready)
        self.market_sell.setEnabled(ready)
        self.save_mark.setEnabled(ready)
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
                        "price",
                        "value",
                        "pnl",
                        "quote_date",
                        "source",
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
        records = self.controller.paper_history["orders"]
        fill(
            self.orders,
            [
                [
                    o["id"],
                    o["status"],
                    o["request"]["code"] + " / " + o["request"]["side"],
                    f"{o['request']['quantity']} / {o['filled_quantity']}",
                    str((o["receipt"] or {}).get("quote", {}).get("date"))
                    + " / "
                    + str(
                        (o["receipt"] or {}).get("quote", {}).get("source", "UNKNOWN")
                    ),
                    (o["receipt"] or {}).get("model_price"),
                    str((o["receipt"] or {}).get("fee"))
                    + " / "
                    + str((o["receipt"] or {}).get("slippage_cost")),
                    o["reason"],
                ]
                for o in records
            ],
        )
        fill(
            self.fills,
            [
                [
                    r["fill_id"],
                    o["id"],
                    r["model_time"],
                    r["code"] + " / " + r["side"],
                    r["filled_quantity"],
                    str(r.get("reference_price")) + " / " + str(r["model_price"]),
                    str(r["quote"].get("date")) + " / " + str(r["quote"].get("source")),
                    str(r["fee"]) + " / " + str(r.get("slippage_cost")),
                ]
                for o in records
                for r in o["receipts"]
            ],
        )
        marks = self.controller.paper_history["marks"]
        curve = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp(m["as_of"])
                    .tz_convert("Asia/Shanghai")
                    .tz_localize(None),
                    "equity": m["equity"],
                }
                for m in marks
            ]
        )
        self.equity_chart.draw(
            curve,
            title="模拟账户原始缓存估值记录（非回测/实盘收益）",
            lines=("equity",),
            max_points=None,
        )
        if marks:
            m = marks[-1]
            ret = (
                (m["equity"] / a["initial"] - 1) * 100
                if m["equity"] is not None
                else None
            )
            self.execution_summary.setText(
                f"已实现盈亏 {display(m['realized_pnl'])} / 费用 {display(m['fees'])} / 模型滑点 {display(m['slippage_cost'])} / 累计收益率 {display(ret)}% · 估值质量 {m['quality']}，见各持仓行情日期"
            )
