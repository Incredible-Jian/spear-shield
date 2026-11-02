"""GUI 启动测试：验证主窗口可构建、导航可切换页面。"""

from __future__ import annotations

from spear_shield.ui.main_window import MainWindow
from spear_shield.database.engine import Database


def test_main_window_builds(qapp, tmp_path) -> None:
    window = MainWindow(
        database=Database(f"sqlite:///{(tmp_path/'app.db').as_posix()}"),
        data_dir=tmp_path,
    )
    assert window.nav_list.count() == len(MainWindow.NAV_ITEMS)
    assert window.stack.count() == len(MainWindow.NAV_ITEMS)
    window.close()


def test_nav_switches_pages(qapp, tmp_path) -> None:
    window = MainWindow(
        database=Database(f"sqlite:///{(tmp_path/'app.db').as_posix()}"),
        data_dir=tmp_path,
    )
    for i in range(window.nav_list.count()):
        window.nav_list.setCurrentRow(i)
        assert window.stack.currentIndex() == i
    window.close()
