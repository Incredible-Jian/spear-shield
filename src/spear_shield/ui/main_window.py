"""主窗口：左侧导航栏 + 右侧工作区。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from .pages.account import AccountPage
from .pages.backtest_center import BacktestCenterPage
from .pages.cycle_resonance import CycleResonancePage
from .pages.dashboard import DashboardPage
from .pages.data_management import DataManagementPage
from .pages.market_analysis import MarketAnalysisPage
from .pages.signal_center import SignalCenterPage
from .pages.thermometer import ThermometerPage


class MainWindow(QMainWindow):
    """应用主窗口。"""

    NAV_ITEMS = [
        ("系统总览", DashboardPage),
        ("五维温度计", ThermometerPage),
        ("周期共振", CycleResonancePage),
        ("策略信号", SignalCenterPage),
        ("资产分析", MarketAnalysisPage),
        ("历史回测", BacktestCenterPage),
        ("模拟账户", AccountPage),
        ("数据管理", DataManagementPage),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{__app_name__} · V{__version__}")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 680)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_nav())
        layout.addWidget(self._build_workspace(), 1)
        self.setCentralWidget(central)

        self._build_status_bar()
        self.nav_list.setCurrentRow(0)

    def _build_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("NavBar")
        nav.setFixedWidth(208)

        layout = QVBoxLayout(nav)
        layout.setContentsMargins(0, 20, 0, 16)
        layout.setSpacing(0)

        title = QLabel("矛与盾")
        title.setObjectName("AppTitle")
        title.setMargin(0)
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(20, 0, 20, 0)
        title_layout.addWidget(title)
        layout.addLayout(title_layout)

        en = QLabel("SPEAR & SHIELD")
        en.setObjectName("AppTitleEn")
        en_layout = QHBoxLayout()
        en_layout.setContentsMargins(20, 0, 20, 0)
        en_layout.addWidget(en)
        layout.addLayout(en_layout)

        section = QLabel("全天候周期共振系统")
        section.setObjectName("NavSectionLabel")
        section_layout = QHBoxLayout()
        section_layout.setContentsMargins(20, 8, 20, 14)
        section_layout.addWidget(section)
        layout.addLayout(section_layout)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("NavList")
        for name, _ in self.NAV_ITEMS:
            item = QListWidgetItem(name)
            item.setSizeHint(item.sizeHint())
            self.nav_list.addItem(item)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav_list, 1)

        version = QLabel(f"V{__version__}")
        version.setObjectName("AppTitleEn")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        return nav

    def _build_workspace(self) -> QWidget:
        self.stack = QStackedWidget()
        for _, page_cls in self.NAV_ITEMS:
            self.stack.addWidget(page_cls())
        return self.stack

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        bar.showMessage("数据源：待接入  |  数据更新时间：—  |  仅供研究参考，不构成投资建议")

    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)
