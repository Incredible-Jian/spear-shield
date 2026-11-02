"""策略数据契约：百分率使用 1=1%，权重使用 1=100%。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any, Mapping


def utc_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("策略时间必须包含时区")
    from datetime import timezone
    return value.astimezone(timezone.utc)


class Status(str, Enum):
    TRIGGERED = "触发"
    CLEAR = "未触发"
    MISSING = "数据缺失"
    PENDING = "待确认"
    UNDEFINED = "未定义"


@dataclass(frozen=True)
class Evidence:
    value: Any
    source: str
    observed_at: datetime
    available_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        times = [utc_time(t) for t in
                 (self.observed_at, self.available_at, self.valid_until)]
        if not self.source.strip() or not times[0] <= times[1] <= times[2]:
            raise ValueError("证据须含来源，且 observed<=available<=valid_until")


@dataclass(frozen=True)
class Snapshot:
    as_of: datetime
    facts: Mapping[str, Evidence] = field(default_factory=dict)
    weekly_final: bool = False

    def __post_init__(self) -> None:
        utc_time(self.as_of)
        if not isinstance(self.weekly_final, bool):
            raise ValueError("weekly_final须为布尔值")

    def get(self, key: str) -> Any | None:
        item = self.facts.get(key)
        if item is None:
            return None
        now = utc_time(self.as_of)
        if not utc_time(item.available_at) <= now <= utc_time(item.valid_until):
            return None
        value = item.value
        if isinstance(value, float) and not isfinite(value):
            return None
        return value


@dataclass(frozen=True)
class Policy:
    """仅传入负责人已确认的定义；不得以建议参数自动构建。"""
    approvals: Mapping[str, str] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def approved(self, key: str) -> bool:
        return bool(self.approvals.get(key, "").strip())


@dataclass(frozen=True)
class Action:
    kind: str                         # entry / reduce / clear / restore
    fraction: float                   # entry: 总资产增量; reduce: 当前持仓比例
    timing: str = "next_trading_day_open"
    scope: str = "attack"
    stages: tuple[int, ...] = ()


@dataclass(frozen=True)
class Condition:
    name: str
    value: bool | None
    expression: str
    inputs: tuple[str, ...] = ()
    pending_definition: str | None = None


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    priority: int                    # 0..3 exits; 4 entries
    status: Status
    conditions: tuple[Condition, ...]
    action: Action | None
    explanation: str
    advisory: bool = False


@dataclass(frozen=True)
class Decision:
    status: str
    selected: RuleResult | None
    results: tuple[RuleResult, ...]
    explanation: str
    position: Position | None = None
    as_of: datetime | None = None


@dataclass(frozen=True)
class Position:
    attack_weight: float = 0.0
    stages: tuple[int, ...] = ()
    nuclear: bool = False
    third_disabled: bool = False
    restore_count: int = 0
    pending_restore_weight: float = 0.0
    restore_due: str | None = None     # 下一个已确认周结算日期 ISO；调用者提供日历
    receipts: tuple[str, ...] = ()
    entry_mode: str | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.attack_weight) or not 0 <= self.attack_weight <= 1:
            raise ValueError("权益权重必须在 [0,1]")
        if (not 0 <= self.pending_restore_weight <= 1 or
                not 0 <= self.restore_count <= 2 or
                len(set(self.stages)) != len(self.stages) or
                any(s not in (1, 2, 3) for s in self.stages)):
            raise ValueError("非法阶梯/补回状态")
        if self.entry_mode not in (None, "normal", "bear", "fast", "nuclear", "catchup"):
            raise ValueError("未知建仓路径")
