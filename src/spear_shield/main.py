"""应用启动入口。

启动方式（任一）：
- spear-shield（控制台入口，安装后）
- python -m spear_shield
"""

from __future__ import annotations

import sys
import argparse
import os

from PySide6.QtWidgets import QApplication

from . import __app_name__, __version__


def main() -> int:
    parser = argparse.ArgumentParser(description=__app_name__)
    parser.add_argument(
        "--data-dir", help="本地数据与配置目录，默认LocalAppData/SpearShield"
    )
    parser.add_argument(
        "--smoke-test", action="store_true", help="启动事件循环后自动退出"
    )
    args = parser.parse_args()
    if args.data_dir:
        os.environ["SPEAR_SHIELD_DATA_DIR"] = args.data_dir
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme
    from .utils.logger import get_logger
    from PySide6.QtCore import QTimer

    logger = get_logger("spear_shield.main")

    def log_exception(exc_type, value, traceback):
        logger.error("未处理的界面异常", exc_info=(exc_type, value, traceback))

    sys.excepthook = log_exception
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    apply_theme(app)

    window = MainWindow()
    window.show()
    logger.info("应用启动：%s V%s", __app_name__, __version__)
    if args.smoke_test:
        QTimer.singleShot(1200, window.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
