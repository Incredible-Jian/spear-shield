"""生成 GUI 截图（用于开发汇报与文档）。

用法：python scripts/capture_screenshot.py [输出目录]
在无显示环境（CI）下使用 offscreen 平台，渲染后抓取窗口像素。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from spear_shield.ui.main_window import MainWindow
from spear_shield.ui.theme import apply_theme


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent.parent / "assets"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    apply_theme(app)

    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    app.processEvents()

    pages = [
        ("dashboard", 0),
        ("thermometer", 1),
        ("cycle_resonance", 2),
    ]
    for name, row in pages:
        window.nav_list.setCurrentRow(row)
        app.processEvents()
        path = out_dir / f"screenshot_{name}.png"
        window.grab().save(str(path))
        print("saved", path)

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
