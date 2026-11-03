"""真实行情验收：限时补充缺失ETF缓存，运行基准研究与桌面事件循环截图。

所有原始行情/研究报告保存在被忽略的cache目录；仓库只保存验收摘要与截图。
"""

import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "cache" / "phase5-preview"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["SPEAR_SHIELD_DATA_DIR"] = str(DATA)


def main():
    from spear_shield.database.engine import Database
    from spear_shield.services.workspace import Workspace
    from spear_shield.backtest.models import BacktestConfig
    from spear_shield.backtest.research import run_benchmarks, result_payload
    from spear_shield.backtest.reporting import persist_report
    from PySide6.QtCore import QTimer, QDate
    from PySide6.QtWidgets import QApplication
    from spear_shield.ui.main_window import MainWindow
    from spear_shield.ui.theme import apply_theme

    DATA.mkdir(parents=True, exist_ok=True)
    db = Database(f"sqlite:///{(DATA/'spear_shield.db').as_posix()}")
    db.init()
    workspace = Workspace(db)
    fetches = []
    for code in ("159915", "563020", "511360", "511990"):
        cached = workspace.history(code)
        if (
            not cached.empty
            and cached.date.min().date() <= date(2024, 1, 2)
            and cached.date.max().date() >= date(2026, 10, 30)
        ):
            fetches.append(
                {"symbol": code, "status": "existing_real_cache", "rows": len(cached)}
            )
            continue
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "spear_shield.data.fetch_worker",
                    code,
                    "2024-01-01",
                    "2026-10-30",
                    "qfq",
                    "akshare",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=55,
            )
            payload = json.loads(result.stdout)
            if result.returncode or "error" in payload:
                raise ValueError(payload.get("error", "fetch failed"))
            count = workspace.store(
                code,
                "qfq",
                __import__("pandas").DataFrame(payload["data"]),
                payload["source"],
            )
            fetches.append(
                {"symbol": code, "status": "real_fetch_saved", "rows": count}
            )
        except Exception as exc:
            fetches.append(
                {"symbol": code, "status": "unavailable", "reason": str(exc)}
            )
        print(json.dumps(fetches[-1], ensure_ascii=False), flush=True)
    config = BacktestConfig(date(2024, 1, 2), date(2026, 10, 30))
    runs = run_benchmarks(workspace, config)
    summary = {
        "fetches": fetches,
        "runs": [
            {
                "name": r["name"],
                "status": r["status"],
                "blockers": r["blockers"],
                "metrics": r["result"].metrics if r["result"] else None,
                "sessions": len(r["result"].curve) if r["result"] else None,
            }
            for r in runs
        ],
    }
    (DATA / "phase6_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    db.close()

    app = QApplication([])
    apply_theme(app)
    window = MainWindow(data_dir=DATA)
    window.resize(1560, 1160)
    window.show()
    window.nav_list.setCurrentRow(5)
    page = window.stack.widget(5)
    page.start.setDate(QDate(2024, 1, 2))
    page.end.setDate(QDate(2026, 10, 30))
    page.fee.setValue(0.03)
    page.slippage.setValue(0.05)
    page.benchmark.setCurrentIndex(3)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(50)

    def done(response):
        def capture():
            output = ROOT / "assets" / "phase6"
            output.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(output / "backtest.png"))
            from PySide6.QtWidgets import QScrollArea

            scroll = page.findChild(QScrollArea)
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())

            def capture_details():
                window.grab().save(str(output / "backtest_details.png"))
                window.close()
                app.quit()

            summary["gui"] = {
                "timer_ticks_50ms": len(ticks),
                "report_saved": Path(page.report_dir, "report.json").is_file(),
            }
            (DATA / "phase6_validation.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(summary["gui"]), flush=True)
            QTimer.singleShot(250, capture_details)

        QTimer.singleShot(400, capture)

    page.job.succeeded.connect(done)
    page.job.failed.connect(
        lambda reason: (print(reason, flush=True), window.close(), app.quit())
    )
    QTimer.singleShot(250, page.execute)
    QTimer.singleShot(125000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
