"""应用配置。

数据目录与数据库路径可被环境变量覆盖，便于测试与部署隔离：
- 环境变量 SPEAR_SHIELD_DATA_DIR 可指定数据根目录。
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import __app_name__, __version__

APP_NAME = "spear-shield"
APP_TITLE = __app_name__
APP_VERSION = __version__

# 数据根目录（默认 Windows 下 %LOCALAPPDATA%\\SpearShield，可被环境变量覆盖）
_DATA_DIR_ENV = "SPEAR_SHIELD_DATA_DIR"


def get_data_dir() -> Path:
    """返回数据根目录（惰性解析，不自动创建）。"""
    env = os.environ.get(_DATA_DIR_ENV)
    if env:
        return Path(env)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SpearShield"
    return Path.home() / ".spear_shield"


DATA_DIR = get_data_dir()
DB_PATH = DATA_DIR / "spear_shield.db"
LOG_DIR = DATA_DIR / "logs"

# 数据库连接（默认 SQLite；测试可用 sqlite:///:memory: 覆盖）
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# 数据源与更新时间展示相关（Phase 2 起生效）
DEFAULT_DATA_SOURCE = "AkShare"
DATA_UNAVAILABLE = "数据缺失"
DATA_PENDING = "待接入"
