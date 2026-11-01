"""日志配置：控制台 + 文件轮转，异常必记录。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..config import settings

_configured = False


def get_logger(name: str = "spear_shield") -> logging.Logger:
    """返回应用日志器（首次调用时完成全局配置）。"""
    global _configured
    logger = logging.getLogger(name)
    if not _configured:
        _configure_root(name)
        _configured = True
    return logger


def _configure_root(name: str) -> None:
    root = logging.getLogger(name)
    root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    try:
        log_dir = Path(settings.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "spear_shield.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:  # 日志目录不可写时降级为仅控制台，不影响主流程
        pass

    root.propagate = False
