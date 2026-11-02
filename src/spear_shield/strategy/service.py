"""策略研究服务：裁决、宏观与防守分析、原子保存历史；不依赖GUI/供应商。"""
from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy.orm import Session

from .defense import defense_plan
from .engine import StrategyEngine
from .evaluation import number
from .macro import resonance, thermometer
from .types import Decision, Policy, Position, Snapshot


@dataclass(frozen=True)
class ResearchResult:
    decision: Decision
    macro: dict
    cycle: dict
    defense: dict
    audit_id: str
    observed_position: Position


def run_research(session: Session, snapshot: Snapshot, position: Position,
                 policy: Policy | None = None, *, current_defense_weights=None) -> ResearchResult:
    # 局部导入，避免 ORM -> 引擎 -> 服务 -> ORM 的循环依赖。
    from ..database.strategy_audit import save_decision
    from ..portfolio.state import observe_month
    policy = policy or Policy()
    month = snapshot.get("month_slope")
    if number(month):
        position = observe_month(position, month)
    decision = StrategyEngine(policy).evaluate(snapshot, position)
    macro = thermometer(snapshot, policy)
    week_up = snapshot.get("week_direction_up") if policy.approved("week_direction_definition") else None
    cycle = resonance(month > 0 if number(month) else None, week_up)
    p0 = snapshot.weekly_final and decision.results[0].status.value == "触发"
    defense = defense_plan(snapshot, policy, active=position.attack_weight == 0 or p0,
                           current_weights=current_defense_weights)
    digest = save_decision(session, snapshot, position, policy, decision,
                           analysis={"macro": macro, "cycle": cycle, "defense": defense})
    return ResearchResult(decision, macro, cycle, defense, digest, position)
