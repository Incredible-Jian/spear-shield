"""当前时点研究→用户确认→不可覆盖快照；不创建或执行账户订单。"""

from dataclasses import replace
from datetime import datetime, time, timezone, timedelta
import hashlib
import json
import uuid
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database.models import Base
from ..database.strategy_audit import _plain
from ..strategy.types import Snapshot, Position
from ..strategy.evaluation import result as evaluate_conditions
from ..strategy.operational import operational_policy, DEFINITION_VERSION
from ..strategy.engine import StrategyEngine, RULE_VERSION
from ..strategy.macro import thermometer, resonance
from ..strategy.defense import defense_plan
from ..strategy.features import build_operational_snapshot
from ..portfolio.paper_account import PaperAccount
from ..portfolio.paper_execution import (
    mark_equity,
    execution_history,
    PaperRiskEvent,
    plain,
)
from ..config.symbols import CORE_SYMBOLS
from .market_view import quote_view
from .research_dataset import load_operational_dataset
from .workspace import normalize_history

SH = ZoneInfo("Asia/Shanghai")


class WeeklyDecision(Base):
    __tablename__ = "weekly_decision"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of: Mapped[str] = mapped_column(String(40), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)


def content_digest(body):
    return hashlib.sha256(plain(body).encode("utf8")).hexdigest()


def prepare_weekly(session, workspace, *, as_of=None, sources_root=None):
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("研究时点须有时区")
    today = now.astimezone(SH).date()
    policy = operational_policy()
    frames = {}
    market = []
    for symbol in CORE_SYMBOLS:
        choices = {}
        for adjust in ("none", "qfq"):
            df = workspace.history(symbol.code, adjust)
            if len(df):
                df = df.loc[
                    (pd.to_datetime(df.updated_at, utc=True, errors="coerce") <= now)
                    & (df.date.dt.date <= today)
                ].copy()
            choices[adjust] = df
        frames[symbol.code] = choices["qfq"]
        market.append(quote_view(symbol, choices["none"], choices["qfq"], now=now))
    limits = []
    calendar = None
    macros = {}
    provenance = {}
    try:
        dataset = load_operational_dataset(
            workspace, **({"root": sources_root} if sources_root is not None else {})
        )
        calendar = dataset.calendar
        retrieved_calendar = pd.to_datetime(
            dataset.provenance.get("calendar", {}).get("retrieved_at"),
            utc=True,
            errors="coerce",
        )
        if pd.isna(retrieved_calendar) or retrieved_calendar > now:
            calendar = None
            limits.append("日历可知时点缺失或晚于研究截止：完成性UNKNOWN")
        # Historical inferred publish dates are NOT used as actual availability.
        # Only series retrieved before now qualify; conservatively use retrieval
        # time as availability for this current-time research snapshot.
        provenance = dataset.provenance
        limits.extend(dataset.limitations)
        for key, df in dataset.macros.items():
            meta = (
                provenance.get("margin_market_statistics", {})
                if key.startswith("margin_")
                else provenance.get(key, {})
            )
            retrieved = pd.to_datetime(
                meta.get("retrieved_at"), utc=True, errors="coerce"
            )
            if pd.isna(retrieved) or retrieved > now:
                continue
            data = df.copy()
            data["available_at"] = pd.to_datetime(data.available_at, utc=True).map(
                lambda value: max(value, retrieved)
            )
            macros[key] = data
    except (ValueError, OSError, KeyError) as exc:
        limits.append("独立日历/研究源不可用：" + str(exc))
    account_known = session.get(PaperAccount, 1) is not None and as_of is None
    account = {
        "initialized": False,
        "quality": "UNKNOWN",
        "equity": None,
        "holdings": [],
    }
    if account_known:
        try:
            account = mark_equity(session, workspace, as_of=now, persist=False)
        except ValueError as exc:
            account_known = False
            limits.append(str(exc))
    account_known = (
        account_known
        and account.get("equity") is not None
        and account.get("quality") == "TRUE"
    )
    weight = 0.0
    if account_known and account["equity"] > 0:
        weight = (
            sum((h["value"] or 0) for h in account["holdings"] if h["code"] == "159915")
            / account["equity"]
        )
    position = Position(attack_weight=weight)
    week_complete = None
    month_complete = None
    weekly = pd.DataFrame()
    monthly = pd.DataFrame()
    snapshot = Snapshot(now)
    if calendar is not None:
        snapshot, weekly, monthly = build_operational_snapshot(
            frames["399006"],
            frames["H30269"],
            calendar,
            as_of=now,
            policy=policy,
            macros=macros,
            context={},
            historical_time_assumption=False,
        )

        def completed_period(freq):
            period = pd.Timestamp(today).to_period(freq)
            sessions = [
                d
                for d in calendar.sessions
                if pd.Timestamp(d).to_period(freq) == period
            ]
            if not sessions or not calendar.complete:
                return None
            if today < sessions[-1] or now < datetime.combine(
                sessions[-1], time(15, 30), SH
            ):
                return False
            for code in ("399006", "H30269"):
                df = frames[code]
                rows = df.loc[df.date.dt.date.isin(sessions)]
                if set(rows.date.dt.date) != set(sessions):
                    return None
                try:
                    normalize_history(rows)
                except ValueError:
                    return None
                if not all(
                    (
                        pd.Timestamp(r.updated_at).tz_localize("UTC")
                        >= datetime.combine(r.date.date(), time(15, 30), SH)
                        if pd.Timestamp(r.updated_at).tzinfo is None
                        else pd.Timestamp(r.updated_at)
                        >= datetime.combine(r.date.date(), time(15, 30), SH)
                    )
                    for r in rows.itertuples()
                ):
                    return None
            return True

        week_complete = completed_period("W-SUN")
        month_complete = completed_period("M")
        snapshot = replace(
            snapshot,
            weekly_final=bool(
                snapshot.weekly_final and week_complete is True and account_known
            ),
        )
    if not account_known:
        limits.append(
            "账户未初始化或原始估值缺失：不把示例空仓视为已观测账户，正式周线动作关闭"
        )
    if weight > 0:
        limits.append(
            "持有进攻份额，但策略档位/峰值/补回等生命周期未由手工账户推断；相关条件UNKNOWN"
        )
    decision = StrategyEngine(policy).evaluate(snapshot, position)
    unknown_position_fields = (
        {"holding", "无底仓", "买入后该笔仓位"} if not account_known else set()
    )
    if not account_known or weight > 0:
        unknown_position_fields |= {
            "阶梯未锁",
            "常规阶梯底仓",
            "二档未执行",
            "三档未执行且未永久关闭",
            "可补回",
        }
    corrected = []
    for rule in decision.results:
        conditions = tuple(
            (
                replace(
                    c,
                    value=None,
                    expression="账户状态或策略生命周期UNKNOWN；不从手工持仓推测",
                )
                if c.name in unknown_position_fields
                else c
            )
            for c in rule.conditions
        )
        corrected.append(
            replace(
                evaluate_conditions(
                    rule.rule_id,
                    rule.priority,
                    conditions,
                    rule.action,
                    rule.explanation,
                ),
                advisory=rule.advisory,
            )
            if conditions != rule.conditions
            else rule
        )
    decision = replace(decision, results=tuple(corrected))
    macro = thermometer(snapshot, policy)
    month = snapshot.get("month_slope")
    cycle = resonance(
        month > 0 if isinstance(month, (int, float)) else None,
        snapshot.get("week_direction_up"),
    )
    defense = defense_plan(snapshot, policy, active=account_known and weight == 0)
    audit = _plain(
        {
            "snapshot": snapshot,
            "position": position,
            "policy": policy,
            "decision": decision,
            "rule_version": RULE_VERSION,
            "analysis": {"macro": macro, "cycle": cycle, "defense": defense},
        }
    )
    observation_dates = {
        "60月线斜率": str(monthly.iloc[-1].date.date()) if len(monthly) else "UNKNOWN",
        "风格Z-Score": str(weekly.iloc[-1].date.date()) if len(weekly) else "UNKNOWN",
    }
    for name, keys in (
        ("股债性价比", ("equity_bond_ratio",)),
        ("期权IV", ("iv_short_pct", "iv_long_pct")),
        ("两融水位", ("margin_pct", "margin_turnover_pct")),
    ):
        observation_dates[name] = " / ".join(
            (
                str(snapshot.facts[k].observed_at.astimezone(SH).date())
                if k in snapshot.facts
                else "UNKNOWN"
            )
            for k in keys
        )
    audit["analysis"]["macro_observation_dates"] = observation_dates
    if not account_known:
        audit["position"] = {k: None for k in audit["position"]}
        audit["position"]["scope"] = "UNKNOWN：当前账户不能回填研究时点"
    unknown = []
    for rule in audit["decision"]["results"]:
        for c in rule["conditions"]:
            if c["value"] is None:
                unknown.append(
                    {
                        "rule": rule["rule_id"],
                        "condition": c["name"],
                        "inputs": c["inputs"],
                        "reason": c["pending_definition"]
                        or "输入缺失、过期或账户生命周期未确认",
                    }
                )
    proposal_id = uuid.uuid4().hex if decision.selected is not None else None
    context = execution_history(session)
    context["orders"] = [
        {
            **o,
            "receipts": [
                r
                for r in o["receipts"]
                if datetime.fromisoformat(r["model_time"]) <= now
            ],
        }
        for o in context["orders"]
        if datetime.fromisoformat(o["request"]["submitted_at"]) <= now
    ]
    context["marks"] = [
        m for m in context["marks"] if datetime.fromisoformat(m["as_of"]) <= now
    ]
    if as_of is not None:
        context = {"orders": [], "marks": []}
        limits.append("显式研究时点不回填当前账户状态；历史账户须查询当时已保存的快照")
    body = {
        "id": uuid.uuid4().hex,
        "as_of": now.isoformat(),
        "data_cutoff": now.isoformat(),
        "definition_version": DEFINITION_VERSION,
        "rule_version": RULE_VERSION,
        "market": market,
        "week_complete": week_complete,
        "month_complete": month_complete,
        "last_observation_week": str(weekly.iloc[-1].date) if len(weekly) else None,
        "last_observation_month": str(monthly.iloc[-1].date) if len(monthly) else None,
        "audit": audit,
        "unknown": unknown,
        "account": account,
        "account_position_known": bool(account_known),
        "orders": context["orders"],
        "equity_history": context["marks"],
        "data_provenance": provenance,
        "input_sha256": {
            code: content_digest(df.to_json(orient="records", date_format="iso"))
            for code, df in frames.items()
        },
        "atr_risk": [
            r for r in audit["decision"]["results"] if r["rule_id"] == "P1_ATR"
        ],
        "proposal_target_id": proposal_id,
        "recommended_position": {
            "status": "暂不可确认" if decision.selected is None else "研究动作，未下单",
            "attack_weight": None,
            "attack_action": (
                _plain(decision.selected.action) if decision.selected else None
            ),
            "defense_internal_weights": (
                defense.get("weights") if defense.get("executable") else None
            ),
            "scope": "防守比例仅端内建议；进攻动作需执行层重新核验，不能把拟仓位当实际持仓",
        },
        "execution": "研究快照不下单；需用户另行发出模拟订单，不能复活旧目标",
        "limits": limits
        + [
            "部分裁决允许UNKNOWN；暂不可确认的条件不当作已通过。",
            "净值/交易为独立模拟账户，未混用回测账户或真实交易。",
        ],
    }
    return {"body": body, "digest": content_digest(body)}


def confirm_weekly(session, draft):
    body = draft["body"]
    digest = content_digest(body)
    if digest != draft["digest"]:
        raise ValueError("裁决草稿已改变，请重新生成并审阅")
    existing = session.get(WeeklyDecision, body["id"])
    if existing:
        if existing.digest != digest:
            raise ValueError("禁止覆盖历史裁决快照")
        return body["id"]
    session.add(
        WeeklyDecision(
            id=body["id"], as_of=body["as_of"], digest=digest, payload=plain(body)
        )
    )
    for event in body["atr_risk"]:
        key = content_digest([body["id"], event["rule_id"]])
        session.add(
            PaperRiskEvent(
                id=key,
                payload=plain(
                    {
                        "snapshot_id": body["id"],
                        "as_of": body["as_of"],
                        "kind": "RESEARCH_OBSERVATION_NOT_EXECUTED",
                        "rule": event,
                    }
                ),
            )
        )
    session.flush()
    return body["id"]


def weekly_history(session):
    return [
        json.loads(row.payload)
        for row in session.query(WeeklyDecision)
        .order_by(WeeklyDecision.as_of.desc())
        .all()
    ]
