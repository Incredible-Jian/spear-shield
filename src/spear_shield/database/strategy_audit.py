"""内容寻址的策略审计日志。保留全部条件，不只保存最终买卖文字。"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
import json
from math import isfinite

from sqlalchemy import Text, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .models import Base
from ..strategy.engine import RULE_VERSION
from ..strategy.types import Decision, Policy, Position, Snapshot, utc_time


class StrategyAudit(Base):
    __tablename__ = "strategy_audit"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of: Mapped[str] = mapped_column(String(40), index=True)
    rule_version: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)


def _plain(value):
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not isfinite(value):
        return {"invalid_numeric": str(value)}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"不可序列化的审计值:{type(value).__name__}")


def save_decision(session: Session, snapshot: Snapshot, position: Position,
                  policy: Policy, decision: Decision, *, analysis: dict | None = None) -> str:
    data = {"snapshot": snapshot, "position": position, "policy": policy,
            "decision": decision, "rule_version": RULE_VERSION, "analysis": analysis}
    payload = json.dumps(_plain(data), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    digest = sha256(payload.encode("utf-8")).hexdigest()
    if session.get(StrategyAudit, digest) is None:
        session.add(StrategyAudit(digest=digest, as_of=utc_time(snapshot.as_of).isoformat(),
                                  rule_version=RULE_VERSION, payload=payload))
        session.flush()
    # 事务由调用者管理：可把证据与其他业务记录一起提交/回滚。
    return digest


def load_history(session: Session, limit: int = 100) -> list[dict]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit须为正整数")
    rows = session.scalars(select(StrategyAudit).order_by(
        StrategyAudit.as_of.desc(), StrategyAudit.digest).limit(limit)).all()
    return [json.loads(row.payload) for row in rows]
