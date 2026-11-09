import pandas as pd
import pytest
from spear_shield.database.engine import Database
from spear_shield.ui.main_window import MainWindow
from spear_shield.indicators.engine import IndicatorEngine


@pytest.fixture
def window(qtbot, tmp_path):
    w = MainWindow(
        database=Database(f"sqlite:///{(tmp_path/'ui.db').as_posix()}"),
        data_dir=tmp_path,
    )
    qtbot.addWidget(w)
    yield w
    w.close()


def test_dashboard_lists_six_symbols_including_missing_without_fake_prices(window):
    page = window.stack.widget(0)
    assert page.quotes.rowCount() == 6
    texts = [page.quotes.item(i, 0).text() for i in range(6)]
    assert any("399006" in t for t in texts) and any("H30269" in t for t in texts)
    assert all("数据缺失" in page.quotes.item(i, 5).text() for i in range(6))


def test_batch_failure_retains_cache_continues_and_cancel_stops_queue(
    window, qtbot, monkeypatch
):
    c = window.controller
    df = pd.DataFrame(
        dict(
            date=pd.to_datetime(["2026-11-06"]),
            open=[10.0],
            high=[11.0],
            low=[9.0],
            close=[10.0],
            volume=[100.0],
        )
    )
    c.workspace.store("159915", "qfq", df, "synthetic-test-only")
    c.refresh()
    calls = []
    monkeypatch.setattr(c.job, "fetch", lambda *args: calls.append(args))
    c.fetch_core()
    assert len(calls) == 1
    c._failed("synthetic-test-only network unavailable")
    qtbot.waitUntil(lambda: len(calls) == 2)
    assert c.history("159915").iloc[-1].close == 10.0
    c.cancel_updates()
    assert not c.batch_active and c.batch_queue == []
    qtbot.wait(20)
    assert len(calls) == 2


def test_market_chart_uses_shared_engine_ma5_10_20_60(window):
    c = window.controller
    dates = pd.bdate_range("2025-01-01", periods=85)
    df = pd.DataFrame(
        dict(date=dates, open=10.0, high=11.0, low=9.0, close=10.0, volume=100.0)
    )
    c.workspace.store("159915", "qfq", df, "synthetic-test-only")
    c.refresh()
    page = window.stack.widget(4)
    page.refresh()
    names = {series.name() for series in page.price.chart().series()}
    assert {"ma5", "ma10", "ma20", "ma60"} <= names
    result = IndicatorEngine().compute(df).data
    assert result.ma20.iloc[-1] == 10.0
