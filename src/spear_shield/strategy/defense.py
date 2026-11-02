"""动态防守建议。权重是防守端内部比例；未定义的转移不擅自分配。"""
from __future__ import annotations

from .evaluation import number
from .types import Policy, Snapshot

ASSETS = ("563020", "511360", "511990")


def defense_plan(snapshot: Snapshot, policy: Policy, *, active: bool,
                 current_weights: dict[str, float] | None = None) -> dict:
    if not active:
        return {"status": "未激活", "weights": None, "deviations": None}
    z = snapshot.get("zscore")
    if not policy.approved("zscore_definition") or not number(z):
        return {"status": "待确认" if not policy.approved("zscore_definition") else "数据缺失",
                "weights": None, "deviations": None}
    base = (.2, .7, .1) if z < -2 else (.6, .3, .1) if z <= 1.5 else (.8, .1, .1)
    weights = dict(zip(ASSETS, base))
    fuse = snapshot.get("defense_fuse") if policy.approved("defense_fuse_definition") else None
    status = "完整" if isinstance(fuse, bool) else "熔断检查待确认或数据缺失"
    unallocated = 0.0
    if fuse is True:
        unallocated = weights["563020"] / 2
        weights["563020"] /= 2
        status = "熔断触发，转入短债/货币的分配待确认"
    deviations = None
    if current_weights is not None:
        if set(current_weights) != set(ASSETS) or any(
                not number(v) or not 0 <= v <= 1 for v in current_weights.values()):
            raise ValueError("实际防守权重须包含且仅包含三个防守标的")
        if abs(sum(current_weights.values()) - 1) > 1e-9:
            raise ValueError("实际防守端内部权重之和须为1")
        deviations = {k: weights[k] - current_weights[k] for k in ASSETS}
    return {"status": status, "weights": weights, "deviations": deviations,
            "unallocated": unallocated, "scope": "defensive_sleeve",
            "executable": isinstance(fuse, bool) and not fuse}
