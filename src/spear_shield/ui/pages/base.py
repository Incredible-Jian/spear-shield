"""页面基础组件：统一页面骨架、空状态与占位卡片。

设计规范约定：
- 每个页面 = BasePage（头部 + 内容区）。
- 未接入真实数据的模块一律使用 EmptyState / PlaceholderCard，
  明确标注「待接入」，绝不展示虚构行情或信号。
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS


def _set_label_style(label: QLabel, obj_name: str) -> None:
    label.setObjectName(obj_name)
    label.setWordWrap(True)


class BasePage(QWidget):
    """统一页面骨架：标题头部 + 可滚动内容区。"""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # 头部
        header = QVBoxLayout()
        header.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("PageHeaderTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageHeaderSubtitle")
        header.addWidget(title_label)
        header.addWidget(subtitle_label)
        root.addLayout(header)

        # 内容区（可滚动）
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.content)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)

    def add_stretch(self) -> None:
        self.content_layout.addStretch(1)


class EmptyState(QFrame):
    """模块空状态卡片：明确标注「待接入 / 数据缺失」。"""

    def __init__(
        self,
        title: str,
        description: str,
        badge_text: str = "待接入",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(8)

        badge = Badge(badge_text, variant="neutral")
        badge_row = QHBoxLayout()
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)

        title_label = QLabel(title)
        _set_label_style(title_label, "EmptyStateTitle")
        layout.addWidget(title_label)

        desc_label = QLabel(description)
        _set_label_style(desc_label, "EmptyStateDesc")
        layout.addWidget(desc_label)


class PlaceholderCard(QFrame):
    """数据占位卡片：标题 + 占位值 + 状态徽章。

    用于 Dashboard 等页面在真实数据接入前展示稳定的布局骨架。
    """

    def __init__(
        self,
        title: str,
        value: str = "—",
        hint: str = "待接入真实数据",
        badge_text: str = "待接入",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        top = QHBoxLayout()
        title_label = QLabel(title)
        _set_label_style(title_label, "CardTitle")
        top.addWidget(title_label)
        top.addStretch(1)
        top.addWidget(Badge(badge_text, variant="neutral"))
        layout.addLayout(top)

        value_label = QLabel(value)
        _set_label_style(value_label, "CardValue")
        layout.addWidget(value_label)

        hint_label = QLabel(hint)
        _set_label_style(hint_label, "CardHint")
        layout.addWidget(hint_label)


class Badge(QLabel):
    """状态徽章。variant: neutral / up / down / warn / accent。"""

    _COLOR_MAP = {
        "neutral": (COLORS["neutral"], "#131a22"),
        "up": (COLORS["up"], "#2a1514"),
        "down": (COLORS["down"], "#122420"),
        "warn": (COLORS["warn"], "#2a2112"),
        "accent": (COLORS["accent"], "#12203a"),
    }

    def __init__(
        self, text: str, variant: str = "neutral", parent: QWidget | None = None
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        fg, bg = self._COLOR_MAP.get(variant, self._COLOR_MAP["neutral"])
        self.setStyleSheet(
            f"QLabel#Badge {{ color: {fg}; background-color: {bg};"
            " border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; }"
        )


def make_card_grid(
    cards: Iterable[QWidget], columns: int = 4, parent: QWidget | None = None
) -> QWidget:
    """将一组卡片排成响应式网格容器。"""
    container = QWidget(parent)
    grid = QGridLayout(container)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(12)
    grid.setAlignment(Qt.AlignTop)
    for i, card in enumerate(cards):
        grid.addWidget(card, i // columns, i % columns)
    return container
