"""应用启动入口。

启动方式（任一）：
- spear-shield（控制台入口，安装后）
- python -m spear_shield
- python src/spear_shield/main.py
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import __app_name__, __version__
from .ui.main_window import MainWindow
from .ui.theme import apply_theme
from .utils.logger import get_logger


def main() -> int:
    logger = get_logger("spear_shield.main")
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    apply_theme(app)

    window = MainWindow()
    window.show()
    logger.info("应用启动：%s V%s", __app_name__, __version__)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
