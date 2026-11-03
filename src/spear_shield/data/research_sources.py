"""Free research snapshots, isolated from the trading database.

Each task runs in a disposable subprocess (at most 45 seconds). AkShare
tables are stored without renaming/filtering as CSV; QVIX's upstream CSV is
also retained byte for byte. Neither cumulative dividends nor QVIX should
be interpreted as payment events or official implied volatility.
"""

from __future__ import annotations

import base64
import contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from uuid import uuid4


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "cache" / "research-sources"
QVIX_URL = "http://1.optbbs.com/d/csv/d/k.csv"
ETF_CODES = ("159915", "563020", "511360", "511990")


@dataclass(frozen=True)
class ResearchTask:
    key: str
    api: str
    kwargs: dict
    source_url: str
    date_columns: tuple[str, ...]
    notes: str
    is_official: bool = False


def research_tasks(*, include_market: bool = False) -> tuple[ResearchTask, ...]:
    """Public catalogue. Raw ETF prices are opt-in; no Workspace writes."""
    tasks = [
        ResearchTask(
            "trade_calendar_sina",
            "tool_trade_date_hist_sina",
            {},
            "https://finance.sina.com.cn/realstock/company/klc_td_sh.txt",
            ("trade_date",),
            "Sina calendar, not an exchange publication.",
        ),
        ResearchTask(
            "qvix",
            "optbbs_csv",
            {},
            QVIX_URL,
            ("date",),
            "Non-official QVIX research proxy; not official IV. "
            "CYB columns 0,71:75; CSI300 index columns 0,17:21, "
            "following akshare.index.index_option_qvix.",
        ),
    ]
    for code in ETF_CODES:
        for kind, indicator in (("dividends", "分红送配详情"), ("splits", "拆分详情")):
            tasks.append(
                ResearchTask(
                    f"etf_{code}_{kind}",
                    "fund_open_fund_info_em",
                    {"symbol": code, "indicator": indicator},
                    f"https://fundf10.eastmoney.com/fhsp_{code}.html",
                    ("除息日", "权益登记日", "分红发放日", "拆分折算日", "拆分日期"),
                    "Third-party event table; dates/units retained as supplied. "
                    "Empty response is not proof of no historical events.",
                )
            )
        sina = ("sz" if code.startswith("15") else "sh") + code
        tasks.append(
            ResearchTask(
                f"etf_{code}_cumulative_dividends",
                "fund_etf_dividend_sina",
                {"symbol": sina},
                f"https://finance.sina.com.cn/realstock/company/{sina}/hfq.js",
                ("日期",),
                "Cumulative dividend observations only; observation dates "
                "are NOT payment dates. No event differencing or payment-date inference.",
            )
        )
        if include_market:
            tasks.append(
                ResearchTask(
                    f"etf_{code}_daily_unadjusted",
                    "fund_etf_hist_em",
                    {
                        "symbol": code,
                        "period": "daily",
                        "start_date": "19900101",
                        "end_date": "20500101",
                        "adjust": "",
                    },
                    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                    ("日期",),
                    "Unadjusted ETF prices; source columns and units retained.",
                )
            )
    for code in ("H30269", "H00300"):
        tasks.append(
            ResearchTask(
                f"index_{code}",
                "stock_zh_index_daily_em",
                {"symbol": f"csi{code}"},
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                ("date",),
                "CSI index redistributed by Eastmoney; not an official CSI download.",
            )
        )
    tasks.extend(
        (
            ResearchTask(
                "margin_market_statistics",
                "eastmoney_margin_statistics",
                {},
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                ("TRADE_DATE",),
                "Publisher Eastmoney RPT_MARGIN_DATASTATISTICS. MARGIN_A_RATIO is margin balance / A-share circulating market value percent; MARGIN_A_TRADE is margin trading / A-share turnover percent. MARKET/BOARD_CODE and history scope retained; not exchange-official.",
            ),
            ResearchTask(
                "index_399006_em",
                "stock_zh_index_daily_em",
                {"symbol": "sz399006"},
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                ("date",),
                "Independent Eastmoney CYB index series for same-date cross-check against Sina.",
            ),
            ResearchTask(
                "index_930897_csindex",
                "stock_zh_index_hist_csindex",
                {
                    "symbol": "930897",
                    "start_date": "20071231",
                    "end_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
                },
                "https://www.csindex.com.cn/csindex-home/perf/index-perf",
                ("日期",),
                "Official CSI non-pure-bond fund category candidate, not asserted to be the original strategy denominator or normalized ratio.",
                True,
            ),
            ResearchTask(
                "index_399006_sina",
                "stock_zh_index_daily",
                {"symbol": "sz399006"},
                "https://finance.sina.com.cn/realstock/company/sz399006/hisdata/klc_kl.js",
                ("date",),
                "Sina full available CYB price history for comparison; third-party data.",
            ),
            ResearchTask(
                "index_H00300_csindex",
                "stock_zh_index_hist_csindex",
                {
                    "symbol": "H00300",
                    "start_date": "19900101",
                    "end_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
                },
                "https://www.csindex.com.cn/csindex-home/perf/index-perf",
                ("日期",),
                "Official CSI endpoint via AkShare; raw supplied columns retained. "
                "Endpoint may prepend a request-start anchor (1990-01-01=1000); "
                "raw date bounds do not imply continuous tradable history.",
                True,
            ),
            ResearchTask(
                "margin_account_info",
                "stock_margin_account_info",
                {},
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                ("日期",),
                "Recent margin account observations. Preserve any supplied ratio fields and "
                "source units verbatim; do not infer their denominator or reconstruct ratios.",
            ),
        )
    )
    return tuple(tasks)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coverage(frame, columns) -> dict:
    import pandas as pd

    coverage = {}
    for column in columns:
        if column in frame.columns:
            values = pd.to_datetime(frame[column], errors="coerce").dropna()
            if not values.empty:
                coverage[column] = {
                    "start": values.min().date().isoformat(),
                    "end": values.max().date().isoformat(),
                    "dated_rows": len(values),
                }
    return coverage


def _artifact(name: str, data: bytes, frame, columns, *, representation: str) -> dict:
    return {
        "name": name,
        "content_base64": base64.b64encode(data).decode("ascii"),
        "rows": len(frame),
        "columns": [str(c) for c in frame.columns],
        "coverage": _coverage(frame, columns),
        "representation": representation,
    }


def _fetch_task(task: ResearchTask) -> dict:
    """Worker only. Parent owns publication and hashing of exact saved bytes."""
    import pandas as pd

    if task.api == "optbbs_csv":
        error = None
        for url in (task.source_url, task.source_url.replace("http://", "https://", 1)):
            try:
                request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(request, timeout=12) as response:
                    raw = response.read()
                break
            except (OSError, TimeoutError) as exc:
                error = exc
        else:
            raise error
        frame = pd.read_csv(io.BytesIO(raw), encoding="gbk")
        if frame.empty or len(frame.columns) < 75:
            raise ValueError("Unexpected QVIX schema")
        artifacts = [
            _artifact(
                "qvix_upstream.csv", raw, frame, (), representation="upstream_bytes"
            )
        ]
        for name, positions in (
            ("qvix_cyb", [0, 71, 72, 73, 74]),
            ("qvix_300index", [0, 17, 18, 19, 20]),
        ):
            series = frame.iloc[:, positions].copy()
            series.columns = ["date", "open", "high", "low", "close"]
            series["date"] = pd.to_datetime(series["date"], errors="coerce")
            for col in ("open", "high", "low", "close"):
                series[col] = pd.to_numeric(series[col], errors="coerce")
            # Pre-inception blanks are not part of the series' observed coverage.
            series = series.dropna(subset=["date"])
            valid = series.close.notna()
            series = (
                series.loc[valid[valid].index.min() : valid[valid].index.max()]
                if valid.any()
                else series.iloc[:0]
            )
            artifacts.append(
                _artifact(
                    name + ".csv",
                    series.to_csv(index=False).encode("utf-8"),
                    series,
                    ("date",),
                    representation="derived_from_qvix_upstream.csv",
                )
            )
    elif task.api == "eastmoney_margin_statistics":
        import urllib.parse

        rows = []
        for page in range(1, 12):
            params = {
                "reportName": "RPT_MARGIN_DATASTATISTICS",
                "columns": "ALL",
                "pageSize": 5000,
                "pageNumber": page,
                "sortColumns": "TRADE_DATE",
                "sortTypes": -1,
            }
            url = task.source_url + "?" + urllib.parse.urlencode(params)
            with urlopen(
                Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=12
            ) as response:
                payload = json.load(response)
            result = payload.get("result")
            if not payload.get("success") or not isinstance(result, dict):
                raise ValueError("Unexpected margin statistics response")
            rows.extend(result["data"])
            if page >= result["pages"]:
                break
        else:
            raise ValueError("Margin pagination incomplete")
        frame = pd.DataFrame(rows)
        if not {"TRADE_DATE", "MARKET", "MARGIN_A_RATIO", "MARGIN_A_TRADE"} <= set(
            frame
        ):
            raise ValueError("Margin fields incomplete")
        artifacts = [
            _artifact(
                task.key + ".csv",
                frame.to_csv(index=False).encode("utf-8"),
                frame,
                task.date_columns,
                representation="publisher_json_table_csv",
            )
        ]
    else:
        import akshare as ak

        frame = getattr(ak, task.api)(**task.kwargs)
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Expected DataFrame")
        artifacts = [
            _artifact(
                task.key + ".csv",
                frame.to_csv(index=False).encode("utf-8"),
                frame,
                task.date_columns,
                representation="akshare_table_csv",
            )
        ]
    return {
        "status": "ok" if all(a["rows"] for a in artifacts) else "empty",
        "retrieved_at": _utc_now(),
        "artifacts": artifacts,
    }


def _run_task(task: ResearchTask, timeout: float) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "spear_shield.data.research_sources",
                "--worker",
                task.key,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=timeout,
            check=False,
        )
        # Do not retain stderr, stdout errors, exception strings or proxy URLs:
        # these can contain local credentials. Only controlled error codes leave workers.
        if result.returncode:
            return {
                "status": "failed",
                "error": "worker_failed",
                "artifacts": [],
                "retrieved_at": _utc_now(),
            }
        payload = json.loads(result.stdout)
        if (
            not isinstance(payload, dict)
            or payload.get("status") not in {"ok", "empty", "failed"}
            or not isinstance(payload.get("artifacts"), list)
            or not isinstance(payload.get("retrieved_at"), str)
        ):
            raise ValueError("Invalid worker response")
        return payload
    except subprocess.TimeoutExpired:
        error = "timeout"
    except (ValueError, OSError):
        error = "worker_protocol_or_launch_error"
    return {
        "status": "failed",
        "error": error,
        "artifacts": [],
        "retrieved_at": _utc_now(),
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def collect_research_sources(
    output_dir: str | Path = DEFAULT_OUTPUT,
    *,
    tasks: tuple[ResearchTask, ...] | None = None,
    timeout: float = 45,
    workers: int = 4,
    include_market: bool = False,
) -> dict:
    """Append an auditable run; failed refreshes never replace prior snapshots.

    Return the manifest (schema_version/runs). Each run contains task records,
    including failures and empty tables. File paths are relative to output_dir.
    Coverage describes observations, not guaranteed completeness. One collector
    should own an output directory at a time.
    """
    if not math.isfinite(timeout) or not 0 < timeout <= 45:
        raise ValueError("timeout must be in (0, 45] seconds")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be in [1, 8]")
    selected = research_tasks(include_market=include_market) if tasks is None else tasks
    known = {t.key: t for t in research_tasks(include_market=True)}
    if any(known.get(t.key) != t for t in selected) or len(
        {t.key for t in selected}
    ) != len(selected):
        raise ValueError("Tasks must be unique members of research_tasks()")
    root = Path(output_dir)
    manifest_path = root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"schema_version": 1, "runs": []}
    )
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("runs"), list
    ):
        raise ValueError("Unsupported manifest")
    run = {
        "id": uuid4().hex,
        "started_at": _utc_now(),
        "timeout_seconds": timeout,
        "tasks": [],
    }
    manifest["runs"].append(run)

    def save_manifest():
        _atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    save_manifest()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_task, t, timeout): t for t in selected}
        for future in as_completed(futures):
            task = futures[future]
            payload = future.result()
            record = {**asdict(task), **payload}
            record["date_columns"] = list(task.date_columns)
            for artifact in record["artifacts"]:
                name = artifact.pop("name")
                if Path(name).name != name or not name.endswith(".csv"):
                    raise ValueError("Invalid artifact name")
                data = base64.b64decode(artifact.pop("content_base64"), validate=True)
                relative = Path(run["id"]) / name
                _atomic_write(root / relative, data)
                artifact.update(
                    path=relative.as_posix(),
                    sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data),
                    retrieved_at=record["retrieved_at"],
                    source_url=task.source_url,
                    is_official=task.is_official,
                )
            run["tasks"].append(record)
            save_manifest()
    run["finished_at"] = _utc_now()
    save_manifest()
    return manifest


def _worker_main(key: str) -> int:
    task = next(t for t in research_tasks(include_market=True) if t.key == key)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            payload = _fetch_task(task)
    except Exception as exc:
        payload = {
            "status": "failed",
            "error": type(exc).__name__,
            "retrieved_at": _utc_now(),
            "artifacts": [],
        }
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--worker":
        raise SystemExit("Use scripts/collect_research_sources.py")
    raise SystemExit(_worker_main(sys.argv[2]))
