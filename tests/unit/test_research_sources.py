"""Offline research collection tests: provenance, deadlines and failure isolation."""

import base64
import hashlib
import io
import json
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from spear_shield.data import research_sources as rs


def _payload(data=b"trade_date\r\n2024-01-02\r\n"):
    frame = pd.read_csv(io.BytesIO(data))
    return {
        "status": "ok",
        "retrieved_at": "2026-11-03T00:00:00+00:00",
        "artifacts": [
            rs._artifact(
                "calendar.csv",
                data,
                frame,
                ("trade_date",),
                representation="akshare_table_csv",
            )
        ],
    }


def test_exact_bytes_hash_coverage_and_failed_refresh(tmp_path, monkeypatch):
    task = rs.research_tasks()[0]
    raw = b"trade_date\r\n2024-01-02\r\n2024-01-03\r\n"
    monkeypatch.setattr(rs, "_run_task", lambda *a: _payload(raw))
    first = rs.collect_research_sources(tmp_path, tasks=(task,))
    record = first["runs"][0]["tasks"][0]
    artifact = record["artifacts"][0]
    path = tmp_path / artifact["path"]
    assert path.read_bytes() == raw
    assert artifact["sha256"] == hashlib.sha256(raw).hexdigest()
    assert artifact["coverage"]["trade_date"] == {
        "start": "2024-01-02",
        "end": "2024-01-03",
        "dated_rows": 2,
    }
    assert artifact["source_url"] == task.source_url
    assert artifact["retrieved_at"] == record["retrieved_at"]
    assert artifact["is_official"] is False
    monkeypatch.setattr(
        rs,
        "_run_task",
        lambda *a: {
            "status": "failed",
            "error": "timeout",
            "retrieved_at": rs._utc_now(),
            "artifacts": [],
        },
    )
    second = rs.collect_research_sources(tmp_path, tasks=(task,))
    assert second["runs"][0] == first["runs"][0]
    assert second["runs"][1]["tasks"][0]["error"] == "timeout"
    assert path.read_bytes() == raw
    assert json.loads((tmp_path / "manifest.json").read_text("utf-8")) == second


def test_timeout_is_bounded_and_secrets_are_not_recorded(monkeypatch):
    def run(command, **kwargs):
        assert kwargs["timeout"] == 45
        assert "--worker" in command
        raise subprocess.TimeoutExpired(command, 45, stderr="secret-token")

    monkeypatch.setattr(rs.subprocess, "run", run)
    result = rs._run_task(rs.research_tasks()[0], 45)
    assert result["status"] == "failed" and result["error"] == "timeout"
    assert "secret-token" not in json.dumps(result)


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout="secret-token", stderr="secret-token"),
        SimpleNamespace(
            returncode=0, stdout="not-json secret-token", stderr="secret-token"
        ),
    ],
)
def test_worker_errors_do_not_expose_output(monkeypatch, result):
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **k: result)
    record = rs._run_task(rs.research_tasks()[0], 45)
    assert record["status"] == "failed"
    assert "secret-token" not in json.dumps(record)


def test_failure_does_not_stop_other_tasks(tmp_path, monkeypatch):
    tasks = rs.research_tasks()[:2]

    def run(task, timeout):
        if task.key == "qvix":
            return {
                "status": "failed",
                "error": "HTTPError",
                "artifacts": [],
                "retrieved_at": rs._utc_now(),
            }
        return _payload()

    monkeypatch.setattr(rs, "_run_task", run)
    result = rs.collect_research_sources(tmp_path, tasks=tasks)
    records = {r["key"]: r for r in result["runs"][-1]["tasks"]}
    assert records["qvix"]["status"] == "failed"
    artifact = records["trade_calendar_sina"]["artifacts"][0]
    assert (tmp_path / artifact["path"]).exists()


def test_qvix_raw_bytes_and_correct_index_columns(monkeypatch):
    frame = pd.DataFrame(
        [
            ["2024-01-02"] + list(range(1, 75)),
            ["2024-01-03"] + list(range(1, 71)) + [None] * 4,
        ]
    )
    raw = frame.to_csv(index=False).encode("gbk")

    def fetch(request, timeout):
        assert request.full_url == rs.QVIX_URL and timeout == 12
        return io.BytesIO(raw)

    monkeypatch.setattr(rs, "urlopen", fetch)
    payload = rs._fetch_task(rs.research_tasks()[1])
    upstream, cyb, index = payload["artifacts"]
    assert base64.b64decode(upstream["content_base64"]) == raw
    cyb_frame = pd.read_csv(io.BytesIO(base64.b64decode(cyb["content_base64"])))
    index_frame = pd.read_csv(io.BytesIO(base64.b64decode(index["content_base64"])))
    assert cyb_frame.close.tolist() == [74]
    assert index_frame.close.tolist() == [20, 20]
    assert cyb["coverage"]["date"]["end"] == "2024-01-02"
    assert index["coverage"]["date"]["end"] == "2024-01-03"


def test_akshare_retains_cumulative_observations_and_empty_is_not_no_events(
    monkeypatch,
):
    calls = []
    frame = pd.DataFrame({"日期": ["2024-01-02"], "累计分红": [0.5]})

    def fetch(**kwargs):
        calls.append(kwargs)
        return frame

    monkeypatch.setitem(
        sys.modules, "akshare", SimpleNamespace(fund_etf_dividend_sina=fetch)
    )
    task = next(
        t for t in rs.research_tasks() if t.key == "etf_159915_cumulative_dividends"
    )
    payload = rs._fetch_task(task)
    assert calls == [{"symbol": "sz159915"}]
    artifact = payload["artifacts"][0]
    assert artifact["columns"] == ["日期", "累计分红"]
    assert "NOT payment dates" in task.notes
    frame = pd.DataFrame()
    assert rs._fetch_task(task)["status"] == "empty"


def test_catalogue_covers_requested_symbols_and_unadjusted_prices():
    tasks = rs.research_tasks(include_market=True)
    for code in rs.ETF_CODES:
        assert {
            f"etf_{code}_{kind}"
            for kind in (
                "dividends",
                "splits",
                "cumulative_dividends",
                "daily_unadjusted",
            )
        } <= {t.key for t in tasks}
    assert {
        t.kwargs["symbol"] for t in tasks if t.api == "stock_zh_index_daily_em"
    } == {"csiH30269", "csiH00300", "sz399006"}
    assert all(t.kwargs["adjust"] == "" for t in tasks if t.api == "fund_etf_hist_em")
    assert {t.key for t in tasks if t.is_official} == {
        "index_H00300_csindex",
        "index_930897_csindex",
    }
    assert next(t for t in tasks if t.key == "index_399006_sina").kwargs == {
        "symbol": "sz399006"
    }


def test_margin_keeps_source_ratio_without_inventing_denominator(monkeypatch):
    frame = pd.DataFrame(
        {"日期": ["2026-11-02"], "融资余额占流通市值比例": [2.3], "融资买入额": [100.0]}
    )
    monkeypatch.setitem(
        sys.modules, "akshare", SimpleNamespace(stock_margin_account_info=lambda: frame)
    )
    task = next(t for t in rs.research_tasks() if t.key == "margin_account_info")
    payload = rs._fetch_task(task)
    artifact = payload["artifacts"][0]
    assert artifact["columns"] == list(frame.columns)
    assert base64.b64decode(artifact["content_base64"]) == frame.to_csv(
        index=False
    ).encode("utf-8")
    assert "denominator" in task.notes


def test_publisher_margin_report_retains_percent_units_and_scope(monkeypatch):
    record = {
        "TRADE_DATE": "2024-01-02 00:00:00",
        "BOARD_CODE": "008",
        "MARKET": "三市",
        "MARGIN_A_RATIO": 2.31,
        "MARGIN_A_TRADE": 10.5,
    }
    body = json.dumps(
        {"success": True, "result": {"pages": 1, "data": [record]}}, ensure_ascii=False
    ).encode("utf-8")
    monkeypatch.setattr(rs, "urlopen", lambda *args, **kwargs: io.BytesIO(body))
    task = next(t for t in rs.research_tasks() if t.key == "margin_market_statistics")
    result = rs._fetch_task(task)
    frame = pd.read_csv(
        io.BytesIO(base64.b64decode(result["artifacts"][0]["content_base64"])),
        dtype={"BOARD_CODE": str},
    )
    assert frame.iloc[0].MARGIN_A_RATIO == 2.31 and frame.iloc[0].BOARD_CODE == "008"
    assert "MARGIN_A_TRADE" in frame and task.is_official is False


@pytest.mark.parametrize("timeout", [0, 46, float("nan"), float("inf")])
def test_rejects_unbounded_deadline(tmp_path, timeout):
    with pytest.raises(ValueError):
        rs.collect_research_sources(tmp_path, timeout=timeout)
    assert not (tmp_path / "manifest.json").exists()
