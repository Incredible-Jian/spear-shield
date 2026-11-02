"""抓取真实数据用于本机视觉验证。数据库/抓取产物留在gitignored cache中。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parents[1]
data_dir = root / "cache" / "phase5-preview"
data_dir.mkdir(parents=True, exist_ok=True)
os.environ["SPEAR_SHIELD_DATA_DIR"] = str(data_dir)

from spear_shield.database.engine import Database
from spear_shield.services.workspace import Workspace
import pandas as pd


def main():
    db = Database(f"sqlite:///{(data_dir/'spear_shield.db').as_posix()}")
    db.init()
    workspace = Workspace(db)
    end = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    results = []
    for code, adjust, provider in (
        ("159915", "qfq", "akshare"),
        ("399006", "qfq", "sina"),
        ("159915", "none", "akshare"),
    ):
        try:
            cached = workspace.history(code, adjust)
            if len(cached):
                result = {
                    "code": code,
                    "adjust": adjust,
                    "status": "existing_cache",
                    "rows": len(cached),
                    "latest": str(cached.iloc[-1].date),
                }
                results.append(result)
                print(json.dumps(result), flush=True)
                continue
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "spear_shield.data.fetch_worker",
                    code,
                    "2015-01-01",
                    end,
                    adjust,
                    provider,
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=50,
            )
            payload = json.loads(r.stdout)
            if r.returncode or "error" in payload:
                raise ValueError(payload.get("error", "request failed"))
            count = workspace.store(
                code, adjust, pd.DataFrame(payload["data"]), payload["source"]
            )
            latest = str(workspace.history(code, adjust).iloc[-1].date)
            result = {
                "code": code,
                "adjust": adjust,
                "source": payload["source"],
                "rows": count,
                "latest": latest,
            }
        except Exception as exc:
            result = {
                "code": code,
                "adjust": adjust,
                "status": "unavailable",
                "reason": type(exc).__name__,
            }
        results.append(result)
        print(json.dumps(result), flush=True)
    (data_dir / "fetch_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    db.close()


if __name__ == "__main__":
    main()
