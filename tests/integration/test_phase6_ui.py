"""真实事件循环、独立回测进程和报告保存测试；测试行情明确标识。"""

import json
from pathlib import Path

import pandas as pd
import pytest
from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import QFileDialog

from spear_shield.database.engine import Database
from spear_shield.services.workspace import Workspace
from spear_shield.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    db.init()
    dates = pd.bdate_range("2023-01-02", "2024-02-01")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1000.0,
        }
    )
    Workspace(db).store("159915", "qfq", df, "synthetic-test-only")
    widget = MainWindow(database=db, data_dir=tmp_path)
    qtbot.addWidget(widget)
    widget.stack.widget(5).start.setDate(QDate(2023, 1, 2))
    widget.stack.widget(5).end.setDate(QDate(2024, 2, 1))
    yield widget
    widget.close()


def test_backtest_background_comparison_report_and_gui_heartbeat(
    window, qtbot, tmp_path, monkeypatch
):
    page = window.stack.widget(5)
    page.benchmark.setCurrentIndex(3)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    with qtbot.waitSignal(page.job.succeeded, timeout=45000):
        page.execute()
    timer.stop()
    assert len(ticks) >= 5
    assert page.comparison.rowCount() == 3
    assert len(page.chart.chart().series()) >= 1
    assert page.payload["runs"][0]["result"] is None
    assert page.payload["runs"][1]["result"]["metrics"]["trade_count"] == 1
    assert page.payload["runs"][2]["status"] == "blocked"
    assert "IV" in page.feedback.text()
    assert Path(page.report_dir, "report.json").is_file()
    assert window.controller.account["initialized"] is False
    path = tmp_path / "export.zip"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), "ZIP")
    )
    page.export_report()
    assert path.read_bytes()[:2] == b"PK"


def test_invalid_dates_and_weights_do_not_start_worker(window):
    page = window.stack.widget(5)
    page.defense[0].setValue(90)
    page.execute()
    assert "合计100%" in page.feedback.text() and not page.job.busy
    page.defense[0].setValue(60)
    page.start.setDate(QDate(2025, 1, 1))
    page.execute()
    assert "日期" in page.feedback.text() and not page.job.busy


def test_full_strategy_only_returns_blockers_not_zero_performance(window, qtbot):
    page = window.stack.widget(5)
    with qtbot.waitSignal(page.job.succeeded, timeout=45000):
        page.execute()
    assert page.comparison.rowCount() == 1
    assert page.comparison.item(0, 2).text() == "—"
    assert page.trades.rowCount() == 0
    assert page.cards[0].value_label.text() == "—"
