"""主窗口：左侧导航栏 + 右侧工作区。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QSettings
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
    QPushButton,
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
from .pages.weekly_report import WeeklyReportPage
from .controller import Controller
from ..config.settings import get_data_dir
from ..database.engine import Database


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
        ("每周报告", WeeklyReportPage),
    ]

    def __init__(
        self, parent: QWidget | None = None, *, database=None, data_dir=None
    ) -> None:
        super().__init__(parent)
        self.data_dir = data_dir or get_data_dir()
        from pathlib import Path

        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database = database or Database(
            f"sqlite:///{(self.data_dir/'spear_shield.db').as_posix()}"
        )
        self.database.init()
        self.controller = Controller(self.database, self.data_dir, self)
        self.settings = QSettings(
            str(self.data_dir / "desktop.ini"), QSettings.IniFormat
        )
        self.setWindowTitle(f"{__app_name__} · V{__version__}")
        self.resize(1440, 960)
        self.setMinimumSize(1024, 680)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_nav())
        layout.addWidget(self._build_workspace(), 1)
        self.setCentralWidget(central)

        self._build_status_bar()
        self.controller.changed.connect(self._refresh_visible)
        self.controller.message.connect(self.statusBar().showMessage)
        self.nav_list.setCurrentRow(0)
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        for key, combo in self._preferences():
            try:
                value = int(self.settings.value(key, combo.currentIndex()))
            except (TypeError, ValueError):
                continue
            if 0 <= value < combo.count():
                combo.setCurrentIndex(value)

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
        refresh = QPushButton("重新读取本地缓存")
        refresh.clicked.connect(self.controller.refresh)
        layout.addWidget(refresh)

        version = QLabel(f"V{__version__}")
        version.setObjectName("AppTitleEn")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        return nav

    def _build_workspace(self) -> QWidget:
        self.stack = QStackedWidget()
        for _, page_cls in self.NAV_ITEMS:
            self.stack.addWidget(page_cls(controller=self.controller))
        return self.stack

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        bar.showMessage("本地缓存观察 / 非实时  |  五维不完整  |  模拟研究工作区")

    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)
            self._refresh_visible()

    def _refresh_visible(self):
        page = self.stack.currentWidget()
        if page and hasattr(page, "refresh"):
            page.refresh()

    def closeEvent(self, event):
        self.controller.job.shutdown()
        self.settings.setValue("geometry", self.saveGeometry())
        for key, combo in self._preferences():
            self.settings.setValue(key, combo.currentIndex())
        self.settings.sync()
        self.database.close()
        super().closeEvent(event)

    def _preferences(self):
        market = self.stack.widget(4)
        data = self.stack.widget(7)
        return [
            ("market/symbol", market.symbol),
            ("market/period", market.period),
            ("market/indicator", market.indicator),
            ("data/provider", data.provider),
            ("data/symbol", data.symbol),
            ("data/adjust", data.adjust),
        ]
