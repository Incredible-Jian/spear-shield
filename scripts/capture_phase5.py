"""使用真实缓存（或明确空状态）运行事件循环并截图；不注入测试行情。"""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "cache" / "phase5-preview"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SPEAR_SHIELD_DATA_DIR"] = str(DATA)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from spear_shield.ui.main_window import MainWindow
from spear_shield.ui.theme import apply_theme
from spear_shield.database.engine import Database


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    db = Database(f"sqlite:///{(DATA/'spear_shield.db').as_posix()}")
    window = MainWindow(database=db, data_dir=DATA)
    window.resize(1440, 1000)
    window.show()
    output = ROOT / "assets" / "phase5"
    output.mkdir(parents=True, exist_ok=True)
    pages = [
        ("dashboard", 0),
        ("market", 4),
        ("cycle", 2),
        ("signals", 3),
        ("data", 7),
        ("report", 8),
    ]

    def capture(index=0):
        if index >= len(pages):
            window.close()
            app.quit()
            return
        name, row = pages[index]
        window.nav_list.setCurrentRow(row)
        if name == "signals" and not window.controller.audits:
            # 真实调用可用性诊断，明确空仓、无正式行情输入，不制造市场信号。
            window.controller.diagnose()

        def save():
            path = output / f"{name}.png"
            window.grab().save(str(path))
            print(str(path), flush=True)
            QTimer.singleShot(80, lambda: capture(index + 1))

        QTimer.singleShot(250, save)

    QTimer.singleShot(400, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
