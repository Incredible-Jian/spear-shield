import sys
from PySide6.QtCore import Qt, QTimer, QProcess
from PySide6.QtWidgets import QLabel, QFileDialog
import pandas as pd
import pytest

from spear_shield.database.engine import Database
from spear_shield.ui.main_window import MainWindow
from spear_shield.ui.jobs import ProcessJob
from spear_shield.services.workspace import Workspace


@pytest.fixture
def window(qtbot, tmp_path):
    db = Database(f"sqlite:///{(tmp_path/'ui.db').as_posix()}")
    db.init()
    dates = pd.bdate_range("2024-01-01", periods=80)
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": 2.0,
            "high": 2.2,
            "low": 1.9,
            "close": 2.1,
            "volume": 100.0,
        }
    )
    Workspace(db).store("159915", "qfq", frame, "synthetic-test-only")
    widget = MainWindow(database=db, data_dir=tmp_path)
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def test_chinese_titles_and_real_cache_chart_widgets(window, qtbot):
    expected = [
        "系统总览",
        "五维宏观温度计",
        "双周期共振",
        "策略信号中心",
        "进攻与防守资产分析",
        "历史回测中心",
        "模拟交易账户",
        "数据管理中心",
        "每周策略报告",
    ]
    assert window.stack.count() == 9
    for i, title in enumerate(expected):
        window.nav_list.setCurrentRow(i)
        assert (
            window.stack.widget(i).findChild(QLabel, "PageHeaderTitle").text() == title
        )
    window.nav_list.setCurrentRow(4)
    page = window.stack.widget(4)
    assert "synthetic-test-only" in page.provenance.text()
    assert len(page.price.chart().series()) >= 2
    for period in (1, 2, 0):
        page.period.setCurrentIndex(period)
    assert window.stack.widget(5).run.isEnabled()


def test_diagnostic_is_labelled_and_no_orders_are_created(window, qtbot):
    window.nav_list.setCurrentRow(3)
    page = window.stack.widget(3)
    qtbot.mouseClick(page.diagnose, Qt.LeftButton)
    assert page.rules.rowCount() == 22
    assert "空仓可用性诊断" in page.history.currentText()
    assert window.controller.audits[0]["decision"]["status"] == "blocked"
    assert window.controller.account["initialized"] is False


def test_account_actions_persist_and_do_not_use_qfq_for_valuation(window, qtbot):
    window.nav_list.setCurrentRow(6)
    page = window.stack.widget(6)
    qtbot.mouseClick(page.create, Qt.LeftButton)
    page.price.setValue(2.5)
    qtbot.mouseClick(page.buy, Qt.LeftButton)
    assert page.positions.rowCount() == 1 and page.trades.rowCount() == 1
    assert window.controller.account["equity"] is None
    assert not page.create.isEnabled()


def test_pdf_export_contains_actual_report_not_placeholder(
    window, qtbot, tmp_path, monkeypatch
):
    page = window.stack.widget(8)
    path = tmp_path / "report.pdf"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), "PDF")
    )
    page.export("pdf")
    assert path.read_bytes().startswith(b"%PDF") and path.stat().st_size > 1000


def test_background_timeout_is_bounded_and_gui_timer_keeps_running(qtbot):
    job = ProcessJob()
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    with qtbot.waitSignal(job.failed, timeout=5000) as signal:
        job.start(sys.executable, ["-c", "import time; time.sleep(20)"], timeout_ms=180)
    timer.stop()
    assert "超时" in signal.args[0]
    assert len(ticks) >= 3 and not job.busy
    assert job.process.state() == QProcess.NotRunning


def test_background_success_and_invalid_json(qtbot):
    job = ProcessJob()
    with qtbot.waitSignal(job.succeeded, timeout=5000) as signal:
        job.start(
            sys.executable,
            ["-c", 'print(\'{"data":[],"source":"test-only"}\')'],
            timeout_ms=3000,
        )
    assert signal.args[0]["source"] == "test-only"
    with qtbot.waitSignal(job.failed, timeout=5000):
        job.start(sys.executable, ["-c", "print('not-json')"], timeout_ms=3000)
    assert not job.busy


def test_immediate_cancel_and_failed_start_do_not_leak_process(qtbot, tmp_path):
    job = ProcessJob()
    with qtbot.waitSignal(job.failed, timeout=5000):
        job.start(sys.executable, ["-c", "import time;time.sleep(20)"], timeout_ms=3000)
        job.cancel()
    assert job.process.state() == QProcess.NotRunning
    with qtbot.waitSignal(job.failed, timeout=5000):
        job.start(str(tmp_path / "missing-program.exe"), [], timeout_ms=3000)
    assert not job.busy


def test_background_wrong_shape_is_reported_without_qt_exception(qtbot):
    job = ProcessJob()
    with qtbot.waitSignal(job.failed, timeout=5000):
        job.start(sys.executable, ["-c", "print('[]')"], timeout_ms=3000)
    assert not job.busy
