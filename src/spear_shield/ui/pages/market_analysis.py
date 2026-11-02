"""真实行情图表、指标与缓存样本统计。"""

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton
from .base import BasePage, PlaceholderCard, make_card_grid
from ..charts import MarketChart
from ..widgets import note, display
from ...services.workspace import SYMBOLS
from ...data.resample import resample_weekly, resample_monthly
from ...indicators.engine import IndicatorEngine


class MarketAnalysisPage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__(
            "进攻与防守资产分析",
            "MARKETS / K线 · 均线 · MACD · RSI · BOLL · ATR",
            parent,
        )
        self.controller = controller
        controls = QHBoxLayout()
        self.symbol = QComboBox()
        self.symbol.addItems([s.code + " " + s.name for s in SYMBOLS.values()])
        self.period = QComboBox()
        self.period.addItems(["日线", "周线", "月线"])
        self.indicator = QComboBox()
        self.indicator.addItems(["MACD", "RSI14", "ATR14", "成交量"])
        for w in (self.symbol, self.period, self.indicator):
            controls.addWidget(w)
        self.reset = QPushButton("重置缩放")
        controls.addWidget(self.reset)
        self.content_layout.addLayout(controls)
        self.cards = [
            PlaceholderCard(n)
            for n in ("区间涨跌", "样本波动", "样本最大回撤", "建议 / 实际权重")
        ]
        self.content_layout.addWidget(make_card_grid(self.cards, 4))
        self.provenance = note("")
        self.content_layout.addWidget(self.provenance)
        self.price = MarketChart(height=330)
        self.oscillator = MarketChart(height=220)
        self.content_layout.addWidget(self.price)
        self.content_layout.addWidget(self.oscillator)
        self.content_layout.addWidget(
            note(
                "最近180根可缩放；指标预热不足保留空白。统计仅针对所选缓存样本，不是策略回测收益；末根周/月K可能未完结。"
            )
        )
        for w in (self.symbol, self.period, self.indicator):
            w.currentIndexChanged.connect(self.refresh)
        self.reset.clicked.connect(self.refresh)
        self.refresh()

    def refresh(self):
        if not self.controller:
            return
        code = self.symbol.currentText().split()[0]
        df = self.controller.history(code)
        if df.empty:
            self.provenance.setText("数据缺失：前往数据管理更新或导入真实历史行情")
            for card in self.cards:
                card.update_value("—", "真实数据未接入", "数据缺失")
            self.price.draw(df, title="暂无真实缓存")
            self.oscillator.draw(df, title="指标不可计算")
            return
        period = ("day", "week", "month")[self.period.currentIndex()]
        bars = (
            df
            if period == "day"
            else resample_weekly(df) if period == "week" else resample_monthly(df)
        )
        out = IndicatorEngine(period).compute(bars).data
        first, last = out.iloc[0].close, out.iloc[-1].close
        change = (last / first - 1) * 100 if first > 0 else None
        ret = out.close.pct_change(fill_method=None)
        volatility = ret.std(ddof=1) * 100 if ret.notna().sum() >= 2 else None
        dd = (out.close / out.close.cummax() - 1).min() * 100
        self.cards[0].update_value(display(change) + "%", "首末已知收盘", "样本观察")
        self.cards[1].update_value(
            display(volatility) + "%", "单周期标准差，未年化", "样本观察"
        )
        self.cards[2].update_value(display(dd) + "%", "收盘累计峰值回撤", "样本观察")
        account = self.controller.account
        actual = "缺原始估值"
        if account.get("equity"):
            holding = next((h for h in account["holdings"] if h["code"] == code), None)
            actual = (
                display((holding["value"] if holding else 0) / account["equity"] * 100)
                + "%"
            )
        self.cards[3].update_value(
            "建议待确认", f"模拟实际：{actual}", "策略受阻", "warn"
        )
        self.provenance.setText(
            f"{code} · 前复权缓存 / 指数为点位 · {df.iloc[0].date} — {df.iloc[-1].date} · 来源：{', '.join(sorted(set(df.source)))} · 写入：{df.updated_at.max()} UTC"
        )
        self.price.draw(
            out,
            title=f"{self.symbol.currentText()} · {self.period.currentText()}",
            candles=True,
            lines=("ma10", "ma60", "boll_up", "boll_low"),
        )
        lines = {
            "MACD": ("dif", "dea", "macd_hist"),
            "RSI14": ("rsi14",),
            "ATR14": ("atr14",),
            "成交量": ("volume",),
        }[self.indicator.currentText()]
        self.oscillator.draw(
            out,
            title=self.indicator.currentText()
            + " / "
            + self.period.currentText()
            + "口径",
            lines=lines,
        )
