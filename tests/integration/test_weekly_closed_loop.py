from datetime import datetime,timedelta
import json
import pandas as pd
import pytest
from PySide6.QtWidgets import QFileDialog
from spear_shield.database.engine import Database
from spear_shield.ui.main_window import MainWindow
from spear_shield.services.weekly_workflow import WeeklyDecision


@pytest.fixture
def window(qtbot,tmp_path,monkeypatch):
    def no_sources(*a,**k):raise FileNotFoundError('synthetic-test-only missing research sources')
    monkeypatch.setattr('spear_shield.services.weekly_workflow.load_operational_dataset',no_sources)
    w=MainWindow(database=Database(f"sqlite:///{(tmp_path/'loop.db').as_posix()}"),data_dir=tmp_path)
    qtbot.addWidget(w)
    yield w
    w.close()


def test_real_price_model_gui_roundtrip_partial_and_receipts(window):
    c=window.controller
    day=pd.Timestamp(datetime.now().date()-timedelta(days=2))
    frame=pd.DataFrame(dict(date=[day],open=[10.],high=[11.],low=[9.],close=[10.],volume=[100.]))
    c.workspace.store('511990','none',frame,'synthetic-test-only');c.refresh()
    page=window.stack.widget(6);page.create.click()
    page.symbol.setCurrentIndex(3);page.qty.setValue(10);page.fill_limit.setValue(4)
    page.market_buy.click()
    assert c.paper_history['orders'][0]['status']=='PARTIAL'
    page.orders.selectRow(0);page.fill_limit.setValue(0);page.retry.click()
    assert c.paper_history['orders'][0]['status']=='FILLED'
    page.market_sell.click()
    assert len(c.paper_history['orders'])==2 and page.fills.rowCount()==3
    assert not c.account['holdings'] and c.account['cash']<100000


def test_user_confirms_snapshot_before_report_and_exports(window,tmp_path,monkeypatch):
    signal=window.stack.widget(3)
    signal.prepare.click()
    assert signal.confirm.isEnabled()
    with window.database.new_session() as s: assert s.query(WeeklyDecision).count()==0
    signal.confirm.click()
    assert len(window.controller.weekly_snapshots)==1
    assert '本周缓存裁决' in signal.history.currentText()
    body=window.controller.weekly_snapshots[0]
    assert body['unknown'] and not body['audit']['snapshot']['weekly_final']
    reports=window.stack.widget(8);reports.archive.click()
    assert reports.document['snapshot_id']==body['id']
    target=tmp_path/'weekly.md'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(target),'MD'))
    reports.export_snapshot('md')
    assert body['id'] in target.read_text(encoding='utf8')
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a,**k:str(tmp_path))
    reports.export_snapshot('csv')
    package=tmp_path/('weekly_'+body['id'][:8])
    identity=json.loads((package/'snapshot_identity.json').read_text(encoding='utf8'))
    assert identity['snapshot_digest']==reports.document['snapshot_digest']
