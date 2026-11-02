"""真实缓存报价与策略状态。"""

from .base import BasePage, PlaceholderCard, make_card_grid
from ..widgets import table, fill, note, display
from ..charts import MarketChart
from ...config.symbols import CORE_ETFS


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
        self.quotes = table(["核心ETF", "前复权缓存价", "行情日期", "来源"], 150)
        self.content_layout.addWidget(self.quotes)
        self.chart = MarketChart(height=280)
        self.content_layout.addWidget(self.chart)
        self.content_layout.addWidget(
            note(
                "本地缓存不是实时订阅；正式裁决读取可追溯审计，缺失数据不视为风险已经排除。"
            )
        )
        self.refresh()

    def refresh(self):
        if not self.controller:
            return
        c = self.controller
        latest = c.audits[0] if c.audits else None
        self.cards[0].update_value(
            "待裁决", "周期观察不等于已确认交易方向", "待确认", "warn"
        )
        self.cards[1].update_value(
            "不完整", "IV缺失 · 股债与其他定义待确认", "数据缺失", "warn"
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
        for symbol in CORE_ETFS:
            df = c.history(symbol.code)
            rows.append(
                [
                    symbol.name + " " + symbol.code,
                    display(df.iloc[-1].close) if len(df) else "数据缺失",
                    str(df.iloc[-1].date) if len(df) else "—",
                    df.iloc[-1].source if len(df) else "—",
                ]
            )
        fill(self.quotes, rows)
        available = sum(bool(len(c.history(s.code))) for s in CORE_ETFS)
        self.summary.setText(
            f"核心ETF缓存 {available}/4 · 正式策略受确认项阻塞 · 模拟账户："
            + ("已初始化" if c.account["initialized"] else "未初始化")
        )
        self.chart.draw(
            c.history("159915"),
            title="159915 创业板ETF · 前复权缓存 / 最近180根",
            lines=("close",),
        )
