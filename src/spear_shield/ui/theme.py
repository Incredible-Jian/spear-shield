"""深色专业量化交易终端主题。

统一的设计规范：深蓝灰背景、红涨绿跌行情色、清晰的数据卡片。
所有页面共享本主题，禁止页面内各自定义颜色。
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ===== 配色规范（唯一颜色来源）=====
COLORS = {
    "bg": "#0b0f14",           # 窗口主背景（深蓝灰）
    "panel": "#0e141b",        # 导航/侧栏背景
    "card": "#131a22",         # 数据卡片背景
    "card_hover": "#16202c",   # 卡片悬浮
    "border": "#232c38",       # 边框
    "text": "#dce4ee",         # 主文字
    "text_muted": "#8b98a9",   # 次级文字
    "text_faint": "#5c6b7d",   # 弱化文字
    "accent": "#3b82f6",       # 强调蓝
    "accent_hover": "#4f8ef7",
    "up": "#ef5350",           # 涨（红，A股约定）
    "down": "#26a69a",         # 跌（绿，A股约定）
    "warn": "#f59e0b",         # 预警（琥珀）
    "neutral": "#64748b",      # 中性/未知
}

_STYLESHEET = """
QWidget {
    background-color: %(bg)s;
    color: %(text)s;
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog { background-color: %(bg)s; }

/* ===== 左侧导航栏 ===== */
#NavBar { background-color: %(panel)s; border-right: 1px solid %(border)s; }
#AppTitle { color: %(text)s; font-size: 16px; font-weight: 700; }
#AppTitleEn { color: %(text_faint)s; font-size: 10px; }
#NavSectionLabel { color: %(text_faint)s; font-size: 11px; font-weight: 600; }

QListWidget#NavList { background: transparent; border: none; outline: 0; }
QListWidget#NavList::item {
    color: %(text_muted)s;
    padding: 11px 18px;
    border-left: 3px solid transparent;
}
QListWidget#NavList::item:hover { background: %(card_hover)s; color: %(text)s; }
QListWidget#NavList::item:selected {
    background: #16283a;
    color: %(text)s;
    border-left: 3px solid %(accent)s;
}

/* ===== 页面头部 ===== */
#PageHeaderTitle { font-size: 21px; font-weight: 700; color: %(text)s; }
#PageHeaderSubtitle { color: %(text_muted)s; font-size: 12px; }

/* ===== 数据卡片 ===== */
QFrame#Card {
    background-color: %(card)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
}
QFrame#Card:hover { border: 1px solid #2f3c4b; }
#CardTitle { color: %(text_muted)s; font-size: 12px; }
#CardValue { color: %(text)s; font-size: 22px; font-weight: 700; }
#CardHint { color: %(text_faint)s; font-size: 11px; }

/* ===== 空状态 ===== */
#EmptyStateTitle { color: %(text_muted)s; font-size: 15px; font-weight: 600; }
#EmptyStateDesc { color: %(text_faint)s; font-size: 12px; }

/* ===== 状态徽章 ===== */
QLabel#Badge {
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}

/* ===== 通用控件 ===== */
QPushButton {
    background-color: %(card)s;
    border: 1px solid %(border)s;
    border-radius: 5px;
    padding: 6px 14px;
    color: %(text)s;
}
QPushButton:hover { background-color: %(card_hover)s; border-color: %(accent)s; }
QPushButton:pressed { background-color: #1b2735; }
QPushButton#PrimaryButton {
    background-color: %(accent)s;
    border: none;
    color: #0b0f14;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover { background-color: %(accent_hover)s; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #2f3c4b; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(border)s; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QStatusBar { background: %(panel)s; color: %(text_muted)s; border-top: 1px solid %(border)s; }
QStatusBar QLabel { color: %(text_muted)s; }
QToolTip {
    background-color: %(card)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    padding: 4px;
}
QScrollArea { border: none; background: transparent; }
"""


def get_stylesheet() -> str:
    """返回全局 QSS 样式表。"""
    return _STYLESHEET % COLORS


def apply_theme(app: QApplication) -> None:
    """应用深色主题到 QApplication。"""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["card"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["panel"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["card"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#0b0f14"))
    app.setPalette(palette)
    app.setStyleSheet(get_stylesheet())
