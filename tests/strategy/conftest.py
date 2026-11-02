"""仅测试用可复核数据；此处的确认记录是夹具，不是正式策略授权。"""
from datetime import datetime, timedelta, timezone
import pytest

from spear_shield.strategy import Evidence, Policy, Snapshot

NOW = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)


@pytest.fixture
def snapshot():
    def make(**values):
        return Snapshot(NOW, {k: Evidence(v, "synthetic-test-only", NOW-timedelta(hours=1),
                                         NOW, NOW+timedelta(days=1))
                              for k, v in values.items()}, weekly_final=True)
    return make


@pytest.fixture
def approved():
    def make(*keys):
        return Policy({k: "TEST FIXTURE ONLY, not developer approval" for k in keys})
    return make
