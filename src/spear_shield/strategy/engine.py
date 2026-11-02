"""无交易副作用的策略裁决；不自行确定同级规则的执行顺序。"""
from __future__ import annotations

from .rules import entry_rules, exit_rules
from .types import Decision, Policy, Position, Snapshot, Status

RULE_VERSION = "v7.3-phase4.1"


class StrategyEngine:
    def __init__(self, policy: Policy | None = None):
        self.policy = policy or Policy()

    def evaluate(self, snapshot: Snapshot, position: Position) -> Decision:
        def decide(status, selected, results, explanation):
            return Decision(status, selected, results, explanation, position, snapshot.as_of)

        results = (*exit_rules(snapshot, position, self.policy),
                   *entry_rules(snapshot, position, self.policy))
        if not snapshot.weekly_final:
            return decide("blocked", None, results,
                            "周线尚未确认；本入口不发布周线动作，盘中风控须使用独立入口")
        if results[0].status is Status.TRIGGERED and position.attack_weight == 0:
            return decide("defense", None, results, "P0触发且无权益，维持防守并禁止建仓")
        exits = [r for r in results if r.priority < 4 and r.action is not None]
        if exits:
            level = min(r.priority for r in exits)
            candidates = [r for r in exits if r.priority == level]
            # 未知的更高优先级不可被当成“未触发”。
            if any(not r.advisory and r.priority < level and r.status in (Status.MISSING, Status.PENDING)
                   for r in results):
                return decide("blocked", None, results, "更高优先级风险不可判定；保留候选，禁止假定风险检查通过")
            if len(candidates) > 1:
                return decide("conflict", None, results, "同级多个规则触发，原文未定同级顺序；不叠加减仓")
            return decide("actionable", candidates[0], results, candidates[0].explanation)
        if any(not r.advisory and r.priority < 4 and r.status in (Status.MISSING, Status.PENDING)
               for r in results):
            return decide("blocked", None, results, "风险检查不完整，禁止新增权益")
        entries = [r for r in results if r.priority == 4 and r.action is not None]
        # 原文明确：核弹第一档替代常规第一档，后续阶梯关闭。
        nuclear = next((r for r in entries if r.rule_id == "ENTRY_NUCLEAR"), None)
        if nuclear:
            entries = [r for r in entries if r.rule_id != "ENTRY_FIRST"]
        if len(entries) > 1:
            return decide("conflict", None, results, "多个入场路径同时成立；优先关系待确认")
        if entries:
            action = entries[0].action
            if position.attack_weight + action.fraction > 1 + 1e-12:
                return decide("blocked", None, results, "建议超过100%权益上限，不裁剪或杠杆建仓")
            return decide("actionable", entries[0], results, entries[0].explanation)
        incomplete = any(r.status in (Status.MISSING, Status.PENDING) for r in results)
        return decide("blocked" if incomplete else "no_action", None, results,
                        "部分规则待确认/数据缺失" if incomplete else "所有可计算规则未触发")

    def evaluate_intraday(self, snapshot: Snapshot, position: Position) -> Decision:
        """仅P1 ATR盘中路径；不将盘中价格视为周收盘，也不以未知P0判正常。"""
        if snapshot.weekly_final:
            weekly = self.evaluate(snapshot, position)
            if weekly.status == "defense" or (weekly.selected and weekly.selected.priority == 0):
                return weekly
        rule = next(r for r in exit_rules(snapshot, position, self.policy)
                    if r.rule_id == "P1_ATR")
        return Decision("actionable" if rule.action else "blocked", rule if rule.action else None,
                        (rule,), rule.explanation, position, snapshot.as_of)
