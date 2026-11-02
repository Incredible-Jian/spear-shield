"""三值逻辑：缺失不等同于条件为假。"""
from __future__ import annotations

from math import isfinite
from numbers import Real
from typing import Callable

from .types import Action, Condition, Policy, RuleResult, Snapshot, Status


def check(snapshot: Snapshot, name: str, keys: tuple[str, ...],
          predicate: Callable, expression: str, *, policy: Policy | None = None,
          definition: str | None = None) -> Condition:
    if definition and (policy is None or not policy.approved(definition)):
        return Condition(name, None, expression, keys, definition)
    values = [snapshot.get(key) for key in keys]
    if any(v is None for v in values):
        return Condition(name, None, expression, keys)
    result = predicate(*values)
    if result is not None and not isinstance(result, bool):
        raise ValueError(f"{name} 必须返回 bool 或 None")
    return Condition(name, result, expression, keys)


def number(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)


def compare(predicate: Callable) -> Callable:
    def wrapped(*values):
        return bool(predicate(*values)) if all(number(v) for v in values) else None
    return wrapped


def flag(snapshot: Snapshot, key: str, policy: Policy, definition: str) -> Condition:
    return check(snapshot, key, (key,), lambda v: v if isinstance(v, bool) else None,
                 f"{key}=True（按负责人确认的定义）", policy=policy, definition=definition)


def fixed(name: str, value: bool | None, expression: str,
          pending: str | None = None) -> Condition:
    return Condition(name, value, expression, pending_definition=pending)


def all_of(name: str, conditions: tuple[Condition, ...]) -> Condition:
    value = False if any(c.value is False for c in conditions) else (
        True if all(c.value is True for c in conditions) else None)
    return Condition(name, value, " AND ".join(c.expression for c in conditions),
                     tuple(k for c in conditions for k in c.inputs),
                     next((c.pending_definition for c in conditions
                           if c.value is None and c.pending_definition), None))


def any_of(name: str, conditions: tuple[Condition, ...]) -> Condition:
    value = True if any(c.value is True for c in conditions) else (
        False if all(c.value is False for c in conditions) else None)
    return Condition(name, value, " OR ".join(c.expression for c in conditions),
                     tuple(k for c in conditions for k in c.inputs),
                     next((c.pending_definition for c in conditions
                           if c.value is None and c.pending_definition), None))


def result(rule_id: str, priority: int, conditions: tuple[Condition, ...],
           action: Action | None, explanation: str) -> RuleResult:
    combined = all_of(rule_id, conditions)
    status = (Status.TRIGGERED if combined.value is True else
              Status.CLEAR if combined.value is False else
              Status.PENDING if combined.pending_definition else Status.MISSING)
    return RuleResult(rule_id, priority, status, conditions,
                      action if status is Status.TRIGGERED else None, explanation,
                      advisory=action is None)


def consecutive(snapshot: Snapshot, key: str, predicate: Callable,
                expression: str) -> Condition:
    def evaluate(values):
        if not isinstance(values, (list, tuple)) or len(values) != 2:
            return None
        if not all(number(v) for v in values):
            return None
        return all(predicate(v) for v in values)
    return check(snapshot, key, (key,), evaluate, expression)
