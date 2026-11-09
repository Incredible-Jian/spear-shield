"""Run the real desktop event loop, update through GUI controller, capture and reopen."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "cache/usability-20261109/desktop"
OUT = ROOT / "assets/usability-20261109"
os.environ["SPEAR_SHIELD_DATA_DIR"] = str(DATA)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from spear_shield.ui.main_window import MainWindow
from spear_shield.ui.theme import apply_theme


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow(data_dir=DATA)
    window.resize(1600, 1120)
    window.show()
    state = {"ticks": 0, "updating": False, "messages": []}
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: state.update(ticks=state["ticks"] + 1))
    heartbeat.start(25)

    def message(text):
        state["messages"].append(text)
        print(text, flush=True)

    window.controller.message.connect(message)

    def capture():
        if state["updating"] and (
            window.controller.batch_active or window.controller.job.busy
        ):
            QTimer.singleShot(250, capture)
            return
        state["batch_results"] = window.controller.batch_results
        state["six_rows"] = window.stack.widget(0).quotes.rowCount()
        window.nav_list.setCurrentRow(0)
        window.grab().save(str(OUT / "dashboard.png"))
        window.nav_list.setCurrentRow(4)
        market = window.stack.widget(4)
        market.indicator.setCurrentText("ATR14")
        market.refresh()

        def charts():
            window.grab().save(str(OUT / "daily_chart.png"))
            market.period.setCurrentIndex(1)
            QTimer.singleShot(350, weekly)

        def weekly():
            window.grab().save(str(OUT / "weekly_chart.png"))
            state["daily_indicators"] = ["ma5", "ma10", "ma20", "ma60", "atr14"]
            state["ticks_before_close"] = state["ticks"]
            app.setQuitOnLastWindowClosed(False)
            window.close()
            reopened = MainWindow(data_dir=DATA)
            reopened.resize(1600, 1120)
            reopened.show()

            def finish():
                state["reopened_six_rows"] = reopened.stack.widget(0).quotes.rowCount()
                state["reopened_history_rows"] = len(
                    reopened.controller.history("159915")
                )
                reopened.grab().save(str(OUT / "reopened.png"))
                reopened.close()
                heartbeat.stop()
                (
                    DATA
                    / (
                        "gui_validation.json"
                        if "--update" in sys.argv
                        else "gui_reopen_validation.json"
                    )
                ).write_text(
                    json.dumps(state, ensure_ascii=False, indent=2), encoding="utf8"
                )
                print("GUI_REOPEN_VERIFIED", flush=True)
                app.quit()

            QTimer.singleShot(700, finish)

        QTimer.singleShot(700, charts)

    def begin():
        state["visible"] = window.isVisible()
        if "--update" in sys.argv:
            state["updating"] = True
            window.stack.widget(0).update.click()
        QTimer.singleShot(700, capture)

    def deadline():
        window.controller.cancel_updates()
        state["deadline_exceeded"] = True

    QTimer.singleShot(280000, deadline)
    QTimer.singleShot(800, begin)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
