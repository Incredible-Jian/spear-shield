from datetime import date
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import pandas as pd
import pytest

from spear_shield.database.engine import Database
from spear_shield.services.workspace import Workspace, normalize_history
from spear_shield.services.reporting import (
    export_table,
    weekly_report,
    export_report_excel,
)
from spear_shield.portfolio.paper_account import initialize, trade, account_view, units
from spear_shield.data.akshare_provider import AkShareProvider
from spear_shield.config.symbols import CORE_ETFS


@pytest.fixture
def workspace(tmp_path):
    db = Database(f"sqlite:///{(tmp_path/'phase5.db').as_posix()}")
    db.init()
    yield Workspace(db)
    db.close()


@pytest.fixture
def bars():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-12"]),
            "open": [2.0, 2.0, 2.1],
            "high": [2.2, 2.2, 2.3],
            "low": [1.9, 1.9, 2.0],
            "close": [2.0, 2.1, 2.2],
            "volume": [100, 200, 300],
            "amount": [200, 420, 660],
        }
    )


def test_qfq_and_raw_cache_are_separate_and_provenance_preserved(workspace, bars):
    original = bars.copy(deep=True)
    workspace.store("159915", "qfq", bars, "test-qfq")
    raw = bars.copy()
    raw["close"] = [2.05, 2.15, 2.25]
    workspace.store("159915", "none", raw, "test-raw")
    assert workspace.history("159915").iloc[-1].close == 2.2
    assert workspace.history("159915", "none").iloc[-1].close == 2.25
    assert workspace.history("159915", "none").iloc[-1].source == "test-raw"
    pd.testing.assert_frame_equal(bars, original)
    assert workspace.summary()[0]["rows"] == 3


@pytest.mark.parametrize(
    "bad", ["duplicate", "inf", "negative_volume", "bad_high", "bad_date"]
)
def test_bad_import_rejected_without_poisoning_cache(workspace, bars, bad):
    workspace.store("159915", "qfq", bars, "test")
    broken = bars.copy()
    if bad == "duplicate":
        broken.loc[1, "date"] = broken.loc[0, "date"]
    if bad == "inf":
        broken.loc[0, "close"] = float("inf")
    if bad == "negative_volume":
        broken.loc[0, "volume"] = -1
    if bad == "bad_high":
        broken.loc[0, "high"] = 1
    if bad == "bad_date":
        broken["date"] = broken.date.dt.tz_localize("UTC")
    with pytest.raises(ValueError):
        workspace.store("159915", "qfq", broken, "invalid-test")
    assert workspace.history("159915").iloc[0].close == 2


def test_snapshot_backup_is_readable(workspace, bars, tmp_path):
    workspace.store("159915", "qfq", bars, "test")
    backup = workspace.backup(tmp_path / "backups")
    with sqlite3.connect(backup) as connection:
        assert (
            connection.execute("select count(*) from market_daily").fetchone()[0] == 3
        )


def test_manual_account_average_cost_sell_and_missing_raw_quote(workspace):
    with workspace.db.new_session() as session:
        initialize(session, 1000)
        trade(session, "159915", "buy", 100, 2.5, 1)
        session.commit()
    with workspace.db.new_session() as session:
        trade(session, "159915", "sell", 40, 3, 0.5)
        session.commit()
        missing = account_view(session, {})
        assert missing["cash"] == 868.5 and missing["equity"] is None
        view = account_view(session, {"159915": {"price": 3.2, "date": "2024-01-12"}})
        assert view["market_value"] == 192 and view["equity"] == 1060.5
        assert view["holdings"][0]["average"] == pytest.approx(2.51)
        assert view["trades"][0]["realized"] == 19.1
        with pytest.raises(ValueError):
            initialize(session, 2000)
    # 重新读取，交易和现金未丢失。
    with workspace.db.new_session() as session:
        assert len(account_view(session, {})["trades"]) == 2


@pytest.mark.parametrize(
    "code,side,qty,price,fee",
    [
        ("000001", "buy", 100, 1, 0),
        ("159915", "buy", 0, 1, 0),
        ("159915", "buy", 100, 0, 0),
        ("159915", "buy", 100, 1, -1),
        ("159915", "sell", 100, 1, 0),
        ("159915", "buy", 10000, 100, 0),
    ],
)
def test_paper_trade_constraints(workspace, code, side, qty, price, fee):
    with workspace.db.new_session() as session:
        initialize(session, 1000)
        session.commit()
    with workspace.db.new_session() as session:
        with pytest.raises(ValueError):
            trade(session, code, side, qty, price, fee)
        session.rollback()
        assert account_view(session, {})["cash"] == 1000


@pytest.mark.parametrize("value", ["nan", "inf", "1.00001"])
def test_integer_money_rejects_non_finite_and_excess_precision(value):
    with pytest.raises(ValueError):
        units(value)


@pytest.mark.parametrize(
    "adjust,provider_arg", [("qfq", "qfq"), ("none", ""), ("hfq", "hfq")]
)
def test_akshare_adjust_is_not_silently_ignored(
    monkeypatch, bars, adjust, provider_arg
):
    captured = {}

    def fetch(**kwargs):
        captured.update(kwargs)
        return bars

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(fund_etf_hist_em=fetch))
    AkShareProvider().fetch_daily(CORE_ETFS[0], "2024-01-01", "2024-01-12", adjust)
    assert captured["adjust"] == provider_arg


def test_weekly_report_uses_week_coverage_not_old_quotes(workspace, bars, tmp_path):
    workspace.store("159915", "qfq", bars, "test-only")
    report = weekly_report(workspace, date(2024, 1, 12), [])
    row = report["data"].iloc[0]
    assert row["区间涨跌%"] == pytest.approx(10)
    later = weekly_report(workspace, date(2024, 2, 2), [])
    assert later["data"].iloc[0]["状态"] == "本周无缓存"
    path = tmp_path / "report.xlsx"
    export_report_excel(report, path)
    assert pd.ExcelFile(path).sheet_names == [
        "市场观察",
        "策略与风险",
        "五维变化",
        "信号记录",
        "防守建议",
    ]


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_exports_neutralize_formulas_and_keep_provenance(
    workspace, bars, tmp_path, suffix
):
    workspace.store("159915", "qfq", bars, "=untrusted-source")
    path = tmp_path / f"history.{suffix}"
    export_table(workspace.history("159915"), path)
    frame = pd.read_csv(path) if suffix == "csv" else pd.read_excel(path)
    assert frame.iloc[0]["source"].startswith("'=")
    assert frame.iloc[0]["adjust"] == "qfq"


def test_fetch_worker_protocol_is_not_polluted_by_provider_prints(tmp_path):
    import json, os, subprocess

    script = """
import sys,types,pandas as pd
def fetch(**kwargs):
    print('provider debug noise')
    from spear_shield.data.akshare_provider import logger
    logger.warning('provider warning noise')
    return pd.DataFrame({'date':['2024-01-05'],'open':[1.0],'high':[2.0],'low':[.5],'close':[1.5],'volume':[100.]})
sys.modules['akshare']=types.SimpleNamespace(fund_etf_hist_em=fetch)
sys.argv=['worker','159915','2024-01-01','2024-01-10','qfq','akshare']
from spear_shield.data.fetch_worker import main
raise SystemExit(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "SPEAR_SHIELD_DATA_DIR": str(tmp_path),
        },
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["data"][0]["close"] == 1.5
    assert "provider warning noise" in result.stderr


def test_all_application_modules_share_file_logger(tmp_path):
    import os, subprocess

    code = "from spear_shield.utils.logger import get_logger; get_logger('spear_shield.first').info('first-module'); get_logger('spear_shield.second').error('second-module')"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        timeout=10,
        env={**os.environ, "SPEAR_SHIELD_DATA_DIR": str(tmp_path)},
    )
    assert result.returncode == 0
    log = (tmp_path / "logs" / "spear_shield.log").read_text(encoding="utf-8")
    assert "first-module" in log and "second-module" in log


def test_weekly_report_macro_delta_and_signals_ignore_future_audit(workspace):
    def audit(when, value, trigger=False):
        rule = {
            "rule_id": "P0_TREND",
            "status": "触发" if trigger else "未触发",
            "explanation": "test-only",
        }
        return {
            "snapshot": {"as_of": when},
            "decision": {
                "explanation": "test-only",
                "results": [rule],
                "selected": rule if trigger else None,
            },
            "analysis": {
                "macro": {
                    "status": "五维不完整",
                    "dimensions": [
                        {
                            "value": [value],
                            "status": "test-only",
                            "sources": ["test-only"],
                        }
                    ],
                },
                "cycle": {"status": "test-cycle"},
                "defense": {
                    "weights": {"563020": 0.6, "511360": 0.3, "511990": 0.1},
                    "status": "test-only",
                },
            },
        }

    records = [
        audit("2024-01-19T08:00:00+00:00", 99, True),
        audit("2024-01-05T08:00:00+00:00", 1),
        audit("2024-01-12T08:00:00+00:00", 1.2, True),
    ]
    report = weekly_report(workspace, date(2024, 1, 12), records)
    assert report["macro"].iloc[0]["较上周最后审计变化"] == "0.2000"
    assert len(report["signals"]) == 1
    assert report["allocation"]["端内建议%"].sum() == 100
