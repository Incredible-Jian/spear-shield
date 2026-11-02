"""真实缓存更新、导入导出与备份。"""

from pathlib import Path
import pandas as pd
from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QPushButton,
    QHBoxLayout,
    QFileDialog,
    QMessageBox,
    QCheckBox,
)
from .base import BasePage
from ..widgets import table, fill, note
from ...services.workspace import SYMBOLS, normalize_history
from ...services.reporting import export_table


class DataManagementPage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__(
            "数据管理中心", "DATA / 来源清晰 · 复权分离 · 限时可取消", parent
        )
        self.controller = controller
        row = QHBoxLayout()
        self.symbol = QComboBox()
        self.symbol.addItems([s.code + " " + s.name for s in SYMBOLS.values()])
        self.adjust = QComboBox()
        self.adjust.addItems(["前复权 qfq", "原始行情 none"])
        self.provider = QComboBox()
        self.provider.addItems(["AkShare / 东方财富", "Sina / 指数备援"])
        for w in (self.symbol, self.adjust, self.provider):
            row.addWidget(w)
        self.content_layout.addLayout(row)
        dates = QHBoxLayout()
        self.start = QDateEdit(QDate(2010, 1, 1))
        self.end = QDateEdit(QDate.currentDate())
        self.start.setCalendarPopup(True)
        self.end.setCalendarPopup(True)
        dates.addWidget(self.start)
        dates.addWidget(self.end)
        self.update = QPushButton("更新所选")
        self.cancel = QPushButton("取消更新")
        self.cancel.setEnabled(False)
        dates.addWidget(self.update)
        dates.addWidget(self.cancel)
        self.content_layout.addLayout(dates)
        operations = QHBoxLayout()
        self.import_button = QPushButton("导入 CSV / Excel")
        self.export_button = QPushButton("导出缓存")
        self.backup = QPushButton("备份 SQLite")
        for w in (self.import_button, self.export_button, self.backup):
            operations.addWidget(w)
        self.content_layout.addLayout(operations)
        auto = QHBoxLayout()
        self.auto = QCheckBox("定时更新所选标的（默认关闭）")
        self.interval = QComboBox()
        self.interval.addItems(["15分钟", "30分钟", "60分钟"])
        auto.addWidget(self.auto)
        auto.addWidget(self.interval)
        auto.addStretch()
        self.content_layout.addLayout(auto)
        self.feedback = note("联网更新最长45秒，期间可切换页面。没有实时订阅。")
        self.content_layout.addWidget(self.feedback)
        self.cache = table(
            ["标的", "口径", "条数", "行情日期", "来源", "写入时间 UTC"], 280
        )
        self.quality = note("")
        self.content_layout.addWidget(self.quality)
        self.content_layout.addWidget(self.cache)
        self.logs = table(["标的", "来源", "结果", "行数", "完成 UTC"], 150)
        self.content_layout.addWidget(self.logs)
        self.content_layout.addWidget(
            note(
                "导入列：date,open,high,low,close,volume；amount可缺失。OHLCV不填补。缺失交易日检查尚待完整日历；覆盖导入前确认并备份，备份保留在本地。"
            )
        )
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fetch)
        self.update.clicked.connect(self.fetch)
        if controller:
            self.cancel.clicked.connect(lambda: controller.job.cancel())
            controller.job.busy_changed.connect(self.busy_changed)
            controller.message.connect(self.feedback.setText)
        self.import_button.clicked.connect(self.import_file)
        self.export_button.clicked.connect(self.export_file)
        self.backup.clicked.connect(self.backup_db)
        self.auto.toggled.connect(self.auto_changed)
        self.interval.currentIndexChanged.connect(self.auto_changed)
        self.refresh()

    def selection(self):
        return (
            self.symbol.currentText().split()[0],
            ("qfq", "none")[self.adjust.currentIndex()],
        )

    def busy_changed(self, busy):
        self.update.setEnabled(not busy)
        self.cancel.setEnabled(busy)
        self.import_button.setEnabled(not busy)

    def auto_changed(self, *args):
        self.timer.stop()
        if self.auto.isChecked():
            self.timer.start((15, 30, 60)[self.interval.currentIndex()] * 60000)

    def fetch(self):
        if not self.controller:
            return
        if self.start.date() > self.end.date():
            self.feedback.setText("日期范围不合法")
            return
        code, adjust = self.selection()
        provider = ("akshare", "sina")[self.provider.currentIndex()]
        if provider == "sina" and not (
            SYMBOLS[code].asset_type == "index"
            and SYMBOLS[code].exchange in ("SZ", "SH")
        ):
            self.feedback.setText("Sina只支持沪深指数，请为ETF选择AkShare")
            return
        self.controller.fetch(
            code,
            self.start.date().toString("yyyy-MM-dd"),
            self.end.date().toString("yyyy-MM-dd"),
            adjust,
            provider,
        )

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入真实历史行情", "", "行情 (*.csv *.xlsx)"
        )
        if not path:
            return
        try:
            file = Path(path)
            if file.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("请拆分为20MB以内后导入")
            frame = (
                pd.read_excel(file, nrows=100001)
                if file.suffix.lower() == ".xlsx"
                else pd.read_csv(file, nrows=100001)
            )
            if len(frame) > 100000:
                raise ValueError("单次最多100000行")
            df = normalize_history(frame)
            code, adjust = self.selection()
            if (
                QMessageBox.question(
                    self,
                    "确认导入",
                    f"将{len(df)}行导入{code} / {adjust}，同日缓存将被更新。继续？",
                )
                != QMessageBox.Yes
            ):
                return
            self.controller.workspace.backup(self.controller.data_dir / "backups")
            count = self.controller.workspace.store(
                code, adjust, df, "import:" + file.name
            )
            self.controller.refresh()
            self.refresh()
            self.feedback.setText(f"已导入{count}行，来源为用户文件，未认证为官方数据")
        except Exception as exc:
            self.feedback.setText(f"导入失败：{exc}")

    def export_file(self):
        code, adjust = self.selection()
        df = self.controller.history(code, adjust)
        if df.empty:
            self.feedback.setText("所选标的暂无缓存")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出真实缓存", f"{code}_{adjust}.csv", "CSV (*.csv);;Excel (*.xlsx)"
        )
        if path:
            try:
                export_table(df, Path(path))
                self.feedback.setText("已导出缓存，包含来源/更新时间/复权口径")
            except Exception as exc:
                self.feedback.setText(f"导出失败：{exc}")

    def backup_db(self):
        try:
            path = self.controller.workspace.backup(
                self.controller.data_dir / "backups"
            )
            self.feedback.setText(f"已备份：{path}")
        except Exception as exc:
            self.feedback.setText(f"备份失败：{exc}")

    def refresh(self):
        if not self.controller:
            return
        invalid = []
        for (code, adjust), frame in self.controller.frames.items():
            if len(frame):
                try:
                    normalize_history(frame)
                except ValueError:
                    invalid.append(code + "/" + adjust)
        empty = sum(r["rows"] == 0 for r in self.controller.summaries)
        self.quality.setText(
            f"空缓存 {empty}/12 · 异常缓存：{', '.join(invalid) if invalid else '未发现OHLCV异常'} · 缺失交易日：待日历接入"
        )
        fill(
            self.cache,
            [
                [
                    r["code"] + " " + r["name"],
                    r["adjust"],
                    r["rows"],
                    r["latest"],
                    r["source"],
                    r["updated"],
                ]
                for r in self.controller.summaries
            ],
        )
        fill(
            self.logs,
            [
                [r[k] for k in ("symbol", "source", "status", "rows", "time")]
                for r in self.controller.workspace.updates()
            ],
        )
