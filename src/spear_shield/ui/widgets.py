"""统一表格、状态文本和说明组件。"""

from __future__ import annotations

import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QLabel,
)


def display(value):
    if value is None or isinstance(value, float) and not math.isfinite(value):
        return "—"
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def table(headers, height=250):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().setVisible(False)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    widget.setMinimumHeight(height)
    widget.setMaximumHeight(height + 120)
    return widget


def fill(widget, rows):
    widget.setSortingEnabled(False)
    widget.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem(display(value))
            item.setToolTip(display(value))
            widget.setItem(i, j, item)


def note(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setObjectName("PageHeaderSubtitle")
    widget.setTextFormat(Qt.PlainText)
    return widget
