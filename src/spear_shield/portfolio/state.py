"""策略持仓状态机；仅在调用者明确确认模拟成交后更新。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from zoneinfo import ZoneInfo

from ..strategy.types import Decision, Position


def observe_month(position: Position, month_slope: float) -> Position:
    """负月斜率关闭三档，之后转正不自动复位；零斜率不自创永久关闭语义。"""
    from math import isfinite
    if not isfinite(month_slope):
        raise ValueError("月斜率须为有限数")
    return replace(position, third_disabled=True) if month_slope < 0 else position


def confirm_execution(position: Position, decision: Decision, receipt_id: str, *,
                      next_week_close: date | None = None) -> Position:
    """按计划完整成交的模拟回执。部分成交、价格重估由未来账户层处理。

    周期结算日由交易日历提供，绝不使用“+7天”猜测节假日。
    """
    if not receipt_id.strip():
        raise ValueError("须提供唯一回执ID")
    if receipt_id in position.receipts:
        return position
    if decision.status != "actionable" or decision.selected is None:
        raise ValueError("无可执行裁决")
    if decision.position != position or decision.as_of is None:
        raise ValueError("裁决缺少持仓绑定或持仓已改变，须重新裁决")
    rule = decision.selected
    action = rule.action
    if action is None or not 0 < action.fraction <= 1:
        raise ValueError("无有效动作")
    updates = {"receipts": (*position.receipts, receipt_id)}
    if action.kind in ("entry", "restore"):
        weight = position.attack_weight + action.fraction
        if weight > 1 + 1e-12:
            raise ValueError("禁止超过100%权益")
        updates.update(attack_weight=min(weight, 1),
                       stages=tuple(sorted(set(position.stages + action.stages))))
        modes = {"ENTRY_FIRST": "normal", "ENTRY_BEAR": "bear", "ENTRY_FAST": "fast",
                 "ENTRY_NUCLEAR": "nuclear", "ENTRY_CATCHUP": "catchup"}
        if rule.rule_id in modes:
            updates["entry_mode"] = modes[rule.rule_id]
        if action.kind == "restore":
            if position.restore_count >= 2 or abs(action.fraction-position.pending_restore_weight) > 1e-12:
                raise ValueError("非法补回")
            updates.update(restore_count=position.restore_count + 1,
                           pending_restore_weight=0.0, restore_due=None)
        if rule.rule_id == "ENTRY_NUCLEAR":
            updates["nuclear"] = True
    elif action.kind in ("reduce", "clear"):
        reduction = position.attack_weight * (1 if action.kind == "clear" else action.fraction)
        updates["attack_weight"] = max(0.0, position.attack_weight - reduction)
        # 任何新的减仓使此前补回计划失效；仅MA10本次减仓创建新的计划。
        updates.update(pending_restore_weight=0.0, restore_due=None)
        if rule.rule_id == "P3_MA10":
            if next_week_close is None or next_week_close <= decision.as_of.astimezone(ZoneInfo("Asia/Shanghai")).date():
                raise ValueError("MA10减仓回执须指定交易日历的次周结算日")
            updates.update(pending_restore_weight=reduction,
                           restore_due=next_week_close.isoformat())
        if updates["attack_weight"] == 0:
            updates.update(stages=(), nuclear=False, entry_mode=None)
    else:
        raise ValueError(f"未知动作:{action.kind}")
    return replace(position, **updates)
