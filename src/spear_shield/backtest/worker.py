"""独立回测进程：只读工作区行情，完整成功后保存独立报告，不改行情/账户。"""

import contextlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4


def main():
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(sys.stderr):
            from ..database.engine import Database
            from ..services.workspace import Workspace
            from .models import BacktestConfig
            from .research import run_benchmarks, result_payload
            from .reporting import persist_report

            config = BacktestConfig(
                date.fromisoformat(request["start"]),
                date.fromisoformat(request["end"]),
                request["initial_cash"],
                request["fee_rate"],
                request["slippage"],
            )
            database_path = Path(request["database"])
            if not database_path.is_file():
                raise ValueError("行情数据库不存在")
            db = Database(f"sqlite:///{database_path.as_posix()}")
            try:
                with db.engine.connect() as connection:
                    connection.exec_driver_sql("PRAGMA query_only=ON")
                runs = run_benchmarks(
                    Workspace(db),
                    config,
                    selection=request["selection"],
                    defense_weights=request["defense_weights"],
                    sources_root=request.get("research_sources"),
                    journal_path=str(
                        Path(sys.argv[1]).with_suffix(".execution.sqlite")
                    ),
                )
                payload = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "request": request,
                    "runs": [
                        {
                            **r,
                            "result": (
                                result_payload(r["result"]) if r["result"] else None
                            ),
                        }
                        for r in runs
                    ],
                }
            finally:
                db.close()
            folder = Path(request["output_dir"]) / uuid4().hex
            persist_report(payload, folder)
        print(
            json.dumps(
                {
                    "data": payload,
                    "source": "local-cache-backtest",
                    "report_dir": str(folder),
                },
                ensure_ascii=False,
                default=str,
                allow_nan=False,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
