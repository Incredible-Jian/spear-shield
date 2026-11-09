"""真实缓存周报，支持PDF/Excel。"""

from pathlib import Path
from PySide6.QtCore import QDate
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QDateEdit,
    QPushButton,
    QHBoxLayout,
    QTextBrowser,
    QFileDialog,
    QComboBox,
)
from .base import BasePage
from ..widgets import note
from ...services.reporting import weekly_report, export_report_excel


class WeeklyReportPage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__(
            "每周策略报告", "REPORT / 市场覆盖 · 宏观缺口 · 裁决 · 下周观察", parent
        )
        self.controller = controller
        bar = QHBoxLayout()
        self.end = QDateEdit(QDate.currentDate())
        self.end.setCalendarPopup(True)
        self.generate = QPushButton("生成/刷新周报")
        self.pdf = QPushButton("导出 PDF")
        self.excel = QPushButton("导出 Excel")
        for widget in (self.end, self.generate, self.pdf, self.excel):
            bar.addWidget(widget)
        self.content_layout.addLayout(bar)
        historybar = QHBoxLayout()
        self.history = QComboBox()
        self.archive = QPushButton("基于最近确认裁决生成周报")
        self.markdown = QPushButton("导出 Markdown")
        self.csv = QPushButton("导出 CSV 数据包")
        for w in (self.history, self.archive, self.markdown, self.csv):
            historybar.addWidget(w)
        self.content_layout.addLayout(historybar)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setMinimumHeight(500)
        self.content_layout.addWidget(self.preview)
        self.feedback = note("报告基于本地缓存与审计；空缺不会自动补为市场判断。")
        self.content_layout.addWidget(self.feedback)
        self.generate.clicked.connect(self.refresh)
        self.pdf.clicked.connect(lambda: self.export("pdf"))
        self.excel.clicked.connect(lambda: self.export("xlsx"))
        self.history.currentIndexChanged.connect(self.refresh)
        self.archive.clicked.connect(self.archive_report)
        self.markdown.clicked.connect(lambda: self.export_snapshot("md"))
        self.csv.clicked.connect(lambda: self.export_snapshot("csv"))
        self.refresh()

    def refresh(self):
        if not self.controller:
            return
        selected = self.history.currentData()
        self.history.blockSignals(True)
        self.history.clear()
        self.history.addItem("缓存观察报告（未选历史周报）", None)
        for record in self.controller.weekly_documents:
            self.history.addItem(
                record["title"] + " · " + record["id"][:8], record["id"]
            )
        index = self.history.findData(selected)
        self.history.setCurrentIndex(max(0, index))
        self.history.blockSignals(False)
        self.document = next(
            (r for r in self.controller.weekly_documents if r["id"] == selected), None
        )
        if self.document:
            self.preview.setHtml(self.document["html"])
            self.feedback.setText(
                "不可变历史周报 · 快照 "
                + self.document["snapshot_id"]
                + " · 数据截止 "
                + self.document["as_of"]
            )
            return
        self.report = weekly_report(
            self.controller.workspace,
            self.end.date().toPython(),
            self.controller.audits,
        )
        self.preview.setHtml(self.report["html"])

    def archive_report(self):
        from ...services.weekly_documents import make_weekly_document

        if not self.controller.weekly_snapshots:
            self.feedback.setText("请先在策略信号页生成并确认本周裁决快照")
            return
        try:
            with self.controller.database.new_session() as s:
                doc = make_weekly_document(s, self.controller.weekly_snapshots[0]["id"])
                s.commit()
            self.controller.refresh()
            self.refresh()
            self.history.setCurrentIndex(self.history.findData(doc["id"]))
        except Exception as exc:
            self.feedback.setText("生成失败：" + str(exc))

    def export_snapshot(self, kind):
        from ...services.weekly_documents import export_document

        if not getattr(self, "document", None):
            self.feedback.setText("请选择已生成的历史周报；不以当前新行情覆盖旧周报")
            return
        if kind == "csv":
            folder = QFileDialog.getExistingDirectory(self, "选择CSV数据包上级目录")
            if not folder:
                return
            path = Path(folder) / ("weekly_" + self.document["id"][:8])
        else:
            name, _ = QFileDialog.getSaveFileName(
                self,
                "导出历史周报",
                "weekly." + kind,
                kind.upper() + " (*." + kind + ")",
            )
            if not name:
                return
            path = Path(name)
        try:
            export_document(self.document, path, kind)
            self.feedback.setText("已导出不可变快照周报：" + str(path))
        except Exception as exc:
            self.feedback.setText("导出失败：" + str(exc))

    def export(self, kind):
        self.refresh()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出周报", f"weekly_report.{kind}", f"{kind.upper()} (*.{kind})"
        )
        if not path:
            return
        try:
            if kind == "xlsx":
                if self.document:
                    from ...services.weekly_documents import export_document

                    export_document(self.document, Path(path), "xlsx")
                else:
                    export_report_excel(self.report, Path(path))
            else:
                printer = QPrinter(QPrinter.HighResolution)
                printer.setOutputFormat(QPrinter.PdfFormat)
                printer.setOutputFileName(path)
                doc = QTextDocument()
                doc.setDefaultFont(self.font())
                doc.setHtml(
                    self.document["html"] if self.document else self.report["html"]
                )
                doc.print_(printer)
            self.feedback.setText(f"已导出：{path}")
        except Exception as exc:
            self.feedback.setText(f"导出失败：{exc}")
