"""真实缓存驱动的隔离模拟买卖→周快照→报告→重启演练，不操作用户账户。"""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "cache/usability-round3/desktop"
OUT = ROOT / "assets/usability-round3"
EXPORT = ROOT / "releases/research-round3"
os.environ["SPEAR_SHIELD_DATA_DIR"] = str(DATA)


def prepare():
    import pandas as pd
    from spear_shield.database.engine import Database
    from spear_shield.services.workspace import Workspace

    DATA.mkdir(parents=True, exist_ok=True)
    target = DATA / "spear_shield.db"
    if not target.exists():
        with sqlite3.connect(
            ROOT / "cache/usability-20261109/desktop/spear_shield.db"
        ) as a, sqlite3.connect(target) as b:
            a.backup(b)
    db = Database(f"sqlite:///{target.as_posix()}")
    db.init()
    workspace = Workspace(db)
    results = []
    for code in ("511990", "511360"):
        try:
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "spear_shield.data.fetch_worker",
                    code,
                    "2025-01-01",
                    datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                    "none",
                    "akshare",
                ],
                capture_output=True,
                text=True,
                encoding="utf8",
                timeout=40,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            payload = json.loads(process.stdout)
            if process.returncode or "error" in payload:
                raise ValueError(payload.get("error", "source failed"))
            rows = workspace.store(
                code, "none", pd.DataFrame(payload["data"]), payload["source"]
            )
            result = {
                "code": code,
                "status": "UPDATED",
                "rows": rows,
                "source": payload["source"],
            }
            results.append(result)
            print(json.dumps(result), flush=True)
            (DATA / "demo_symbol.txt").write_text(code, encoding="ascii")
            break
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            results.append({"code": code, "status": "FAILED", "error": str(exc)[:250]})
    (DATA / "real_fetch.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    db.close()
    if not any(r["status"] == "UPDATED" for r in results):
        raise RuntimeError("真实原始价不可用，禁止合成行情代替演练")


def run():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from spear_shield.ui.main_window import MainWindow
    from spear_shield.ui.theme import apply_theme
    from spear_shield.services.weekly_documents import export_document

    OUT.mkdir(parents=True, exist_ok=True)
    EXPORT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow(data_dir=DATA)
    window.resize(1680, 1150)
    window.show()
    state = {"simulated": True, "real_fund_trades": False, "stages": []}
    code = (DATA / "demo_symbol.txt").read_text().strip()

    def fail(exc):
        import traceback

        state["traceback"] = traceback.format_exc()
        state["error"] = repr(exc)
        (DATA / "gui_evidence.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf8"
        )
        print("VALIDATION_FAILED", repr(exc), flush=True)
        window.close()
        app.exit(1)

    def account():
        try:
            if "--resume-verification" in sys.argv:
                state.update(
                    json.loads((DATA / "gui_evidence.json").read_text(encoding="utf8"))
                )
                state.pop("error", None)
                assert window.controller.account == state["account_before_restart"]
                assert (
                    window.controller.paper_history["orders"]
                    == state["execution_before_restart"]["orders"]
                )
                assert (
                    window.controller.paper_history["marks"]
                    == state["execution_before_restart"]["marks"]
                )
                window.nav_list.setCurrentRow(6)
                QTimer.singleShot(500, capture_account)
                return
            page = window.stack.widget(6)
            window.nav_list.setCurrentRow(6)
            if window.controller.account["initialized"]:
                raise ValueError(
                    "验证账户已有记录，拒绝重置或重复运行交易；请使用新的隔离目录"
                )
            page.create.click()
            page.symbol.setCurrentIndex(3 if code == "511990" else 2)
            page.qty.setValue(100)
            page.allow_intraday.setChecked(True)
            page.fill_limit.setValue(40)
            page.market_buy.click()
            order = window.controller.paper_history["orders"][-1]
            assert order["status"] == "PARTIAL", page.feedback.text()
            state["partial_buy"] = order
            page.orders.selectRow(len(window.controller.paper_history["orders"]) - 1)
            page.fill_limit.setValue(0)
            page.retry.click()
            assert window.controller.paper_history["orders"][-1]["status"] == "FILLED"
            page.market_sell.click()
            assert (
                window.controller.paper_history["orders"][-1]["status"] == "FILLED"
            ), page.feedback.text()
            assert not window.controller.account["holdings"]
            state["account_before_restart"] = window.controller.account
            state["execution_before_restart"] = window.controller.paper_history
            state["stages"].append("GUI_PARTIAL_BUY_RETRY_SELL_OK")
            QTimer.singleShot(500, capture_account)
        except Exception as exc:
            fail(exc)

    def capture_account():
        window.grab().save(str(OUT / "account.png"))
        page = window.stack.widget(6)
        # Capture the order/fill area after scrolling the actual page.
        from PySide6.QtWidgets import QScrollArea

        scroll = page.findChild(QScrollArea)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        QTimer.singleShot(500, existing_history if '--resume-verification' in sys.argv and '--new-snapshot' not in sys.argv else decide)

    def existing_history():
        window.grab().save(str(OUT/'orders_fills_equity.png'))
        window.nav_list.setCurrentRow(3)
        def report_history():
            window.grab().save(str(OUT/'weekly_decision.png'))
            window.nav_list.setCurrentRow(8)
            page=window.stack.widget(8)
            page.history.setCurrentIndex(page.history.findData(state['report_id']))
            QTimer.singleShot(500,reopen)
        QTimer.singleShot(500,report_history)

    def decide():
        try:
            window.grab().save(str(OUT / "orders_fills_equity.png"))
            page = window.stack.widget(3)
            window.nav_list.setCurrentRow(3)
            page.prepare.click()
            assert page.confirm.isEnabled(), page.status.text()
            page.confirm.click()
            assert window.controller.weekly_snapshots
            state["snapshot"] = window.controller.weekly_snapshots[0]
            state["stages"].append("WEEKLY_DRAFT_USER_CONFIRM_SNAPSHOT_OK")
            QTimer.singleShot(500, report)
        except Exception as exc:
            fail(exc)

    def report():
        try:
            window.grab().save(str(OUT / "weekly_decision.png"))
            page = window.stack.widget(8)
            window.nav_list.setCurrentRow(8)
            page.archive.click()
            assert page.document is not None, page.feedback.text()
            document = page.document
            folder = EXPORT / document["id"]
            folder.mkdir(exist_ok=False)
            export_document(document, folder / "weekly_report.md", "md")
            export_document(document, folder / "weekly_report.xlsx", "xlsx")
            export_document(document, folder / "csv", "csv")
            state["report_id"] = document["id"]
            state["export_directory"] = folder.relative_to(ROOT).as_posix()
            state["stages"].append("IMMUTABLE_REPORT_MD_CSV_XLSX_OK")
            QTimer.singleShot(500, reopen)
        except Exception as exc:
            fail(exc)

    def reopen():
        try:
            # Confirmation appends a research risk observation, not a trade.
            # Compare the restart at a single checkpoint after that append.
            assert (
                window.controller.paper_history["orders"]
                == state["execution_before_restart"]["orders"]
            )
            assert (
                window.controller.paper_history["marks"]
                == state["execution_before_restart"]["marks"]
            )
            state["execution_after_trade_before_confirmation"] = state[
                "execution_before_restart"
            ]
            state["execution_before_restart"] = window.controller.paper_history
            window.grab().save(str(OUT / "weekly_report.png"))
            app.setQuitOnLastWindowClosed(False)
            window.close()
            reopened = MainWindow(data_dir=DATA)
            reopened.resize(1680, 1150)
            reopened.show()
            assert reopened.controller.account == state["account_before_restart"]
            assert (
                reopened.controller.paper_history == state["execution_before_restart"]
            )
            assert reopened.controller.weekly_snapshots[0] == state["snapshot"]
            assert reopened.controller.weekly_documents[0]["id"] == state["report_id"]
            state["account_after_restart"] = reopened.controller.account
            state["stages"].append(
                "RESTART_ACCOUNT_ORDERS_FILLS_SNAPSHOT_REPORT_IDENTICAL"
            )

            def finish():
                reopened.nav_list.setCurrentRow(6)
                reopened.grab().save(str(OUT / "reopened_account.png"))
                reopened.close()
                (DATA / "gui_evidence.json").write_text(
                    json.dumps(state, ensure_ascii=False, indent=2, default=str),
                    encoding="utf8",
                )
                print(
                    "ROUND3_DESKTOP_VERIFIED " + state["export_directory"], flush=True
                )
                app.quit()

            QTimer.singleShot(600, finish)
        except Exception as exc:
            fail(exc)

    QTimer.singleShot(600, account)
    return app.exec()


if __name__ == "__main__":
    if "--prepare" in sys.argv:
        prepare()
    else:
        raise SystemExit(run())
