"""pytest 全局配置：无显示环境下运行 Qt 应用。"""
from __future__ import annotations

import os

# 必须在导入 PySide6 前设置，确保 CI / 无头环境可运行 GUI 测试
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
