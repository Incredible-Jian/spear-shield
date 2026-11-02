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
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setMinimumHeight(500)
        self.content_layout.addWidget(self.preview)
        self.feedback = note("报告基于本地缓存与审计；空缺不会自动补为市场判断。")
        self.content_layout.addWidget(self.feedback)
        self.generate.clicked.connect(self.refresh)
        self.pdf.clicked.connect(lambda: self.export("pdf"))
        self.excel.clicked.connect(lambda: self.export("xlsx"))
        self.refresh()

    def refresh(self):
        if not self.controller:
            return
        self.report = weekly_report(
            self.controller.workspace,
            self.end.date().toPython(),
            self.controller.audits,
        )
        self.preview.setHtml(self.report["html"])

    def export(self, kind):
        self.refresh()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出周报", f"weekly_report.{kind}", f"{kind.upper()} (*.{kind})"
        )
        if not path:
            return
        try:
            if kind == "xlsx":
                export_report_excel(self.report, Path(path))
            else:
                printer = QPrinter(QPrinter.HighResolution)
                printer.setOutputFormat(QPrinter.PdfFormat)
                printer.setOutputFileName(path)
                doc = QTextDocument()
                doc.setDefaultFont(self.font())
                doc.setHtml(self.report["html"])
                doc.print_(printer)
            self.feedback.setText(f"已导出：{path}")
        except Exception as exc:
            self.feedback.setText(f"导出失败：{exc}")
