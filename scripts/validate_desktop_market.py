"""Bounded real-data verification in an isolated profile; never modifies user data."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from spear_shield.database.engine import Database
from spear_shield.services.workspace import Workspace
from spear_shield.services.research_dataset import ResearchSnapshots, price_index
from spear_shield.config.symbols import CORE_SYMBOLS

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "cache/usability-20261109/desktop"


def main():
    PROFILE.mkdir(parents=True, exist_ok=True)
    database = PROFILE / "spear_shield.db"
    if not database.exists():
        with sqlite3.connect(
            ROOT / "cache/phase5-preview/spear_shield.db"
        ) as src, sqlite3.connect(database) as dst:
            src.backup(dst)
    db = Database(f"sqlite:///{database.as_posix()}")
    workspace = Workspace(db)
    # Load a verified real historical snapshot when GUI cache has no H30269.
    # This is explicitly an archive import, not a successful live refresh.
    if workspace.history("H30269").empty:
        frame, meta = ResearchSnapshots().read("index_H30269")
        if len(frame):
            workspace.store(
                "H30269", "qfq", price_index(frame), "archive-eastmoney-csi"
            )
            (PROFILE / "archive_source.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf8"
            )
    end = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def fetch(symbol):
        provider = "sina" if symbol.code == "399006" else "akshare"
        args = [
            sys.executable,
            "-m",
            "spear_shield.data.fetch_worker",
            symbol.code,
            "2026-10-01",
            end,
            "qfq",
            provider,
        ]
        try:
            process = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf8",
                env=env,
                timeout=35,
            )
            payload = json.loads(process.stdout)
            if process.returncode or "error" in payload:
                return symbol.code, {
                    "status": "FAILED",
                    "error": payload.get("error", "provider error"),
                }
            return symbol.code, {"status": "FETCHED", "payload": payload}
        except subprocess.TimeoutExpired:
            return symbol.code, {
                "status": "TIMEOUT",
                "error": "35秒预算内未返回，保留真实缓存",
            }
        except (ValueError, OSError) as exc:
            return symbol.code, {"status": "FAILED", "error": type(exc).__name__}

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(fetch, s) for s in CORE_SYMBOLS]):
            code, result = future.result()
            if result["status"] == "FETCHED":
                payload = result.pop("payload")
                try:
                    result["rows"] = workspace.store(
                        code, "qfq", pd.DataFrame(payload["data"]), payload["source"]
                    )
                    result["status"] = "UPDATED"
                    result["source"] = payload["source"]
                except ValueError as exc:
                    result = {"status": "INVALID_DATA", "error": str(exc)}
            if result["status"] != "UPDATED":
                workspace.failure(code, "akshare", "failed")
            result["code"] = code
            cached = workspace.history(code)
            result["cache_rows"] = len(cached)
            result["cache_latest"] = str(cached.date.max()) if len(cached) else None
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    (PROFILE / "real_fetch_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    db.close()


if __name__ == "__main__":
    main()
