"""包元数据与版本号基础测试。"""
from __future__ import annotations

import spear_shield


def test_version_is_semver() -> None:
    parts = spear_shield.__version__.split(".")
    assert len(parts) == 3, "版本号应为语义化版本 (major.minor.patch)"
    assert all(p.isdigit() for p in parts)


def test_app_name_present() -> None:
    assert "矛与盾" in spear_shield.__app_name__
    assert "Spear" in spear_shield.__app_name_en__
