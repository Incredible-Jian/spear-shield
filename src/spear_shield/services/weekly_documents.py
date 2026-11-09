"""只从确认后的不可变快照生成周报与导出，不重新查询后来行情。"""

from datetime import datetime, timedelta
from html import escape
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database.models import Base
from .weekly_workflow import WeeklyDecision, content_digest
from .reporting import export_table, safe_cell
from ..portfolio.paper_execution import plain


class WeeklyReportRecord(Base):
    __tablename__ = "weekly_report_record"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


def make_weekly_document(session, snapshot_id):
    record = session.get(WeeklyReportRecord, snapshot_id)
    if record:
        return json.loads(record.payload)
    snapshot = session.get(WeeklyDecision, snapshot_id)
    if snapshot is None:
        raise ValueError("先确认并保存本周裁决快照")
    body = json.loads(snapshot.payload)
    if content_digest(body) != snapshot.digest:
        raise ValueError("快照内容哈希不匹配")
    now = datetime.fromisoformat(body["as_of"])
    from zoneinfo import ZoneInfo

    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    start = local.date() - timedelta(days=local.weekday())
    fills = [
        r
        for o in body["orders"]
        for r in o["receipts"]
        if start
        <= datetime.fromisoformat(r["model_time"])
        .astimezone(ZoneInfo("Asia/Shanghai"))
        .date()
        <= local.date()
        and datetime.fromisoformat(r["model_time"]) <= now
    ]
    tables = {
        "market": pd.DataFrame(body["market"]),
        "macro": pd.DataFrame(body["audit"]["analysis"]["macro"]["dimensions"]),
        "holdings": pd.DataFrame(body["account"].get("holdings", [])),
        "orders": pd.DataFrame(
            [
                {
                    "order_id": o["id"],
                    "status": o["status"],
                    "reason": o["reason"],
                    **o["request"],
                    "filled_quantity": o["filled_quantity"],
                }
                for o in body["orders"]
            ]
        ),
        "fills": pd.DataFrame(fills),
        "equity": pd.DataFrame(body["equity_history"]),
        "unknown": pd.DataFrame(body["unknown"]),
        "risk": pd.DataFrame(body["atr_risk"]),
        "conditions": pd.DataFrame(
            [
                {
                    "rule": r["rule_id"],
                    "priority": r["priority"],
                    "rule_status": r["status"],
                    "condition": c["name"],
                    "state": (
                        "UNKNOWN" if c["value"] is None else str(c["value"]).upper()
                    ),
                    "expression": c["expression"],
                    "inputs": c["inputs"],
                }
                for r in body["audit"]["decision"]["results"]
                for c in r["conditions"]
            ]
        ),
    }
    tables["macro"]["data_date"] = [
        body["audit"]["analysis"].get("macro_observation_dates", {}).get(n, "UNKNOWN")
        for n in tables["macro"]["name"]
    ]
    title = f"每周研究报告 · {start}—{local.date()}"
    notes = [
        f"裁决快照ID：{snapshot_id}",
        f"策略参数版本：{body['definition_version']}",
        f"数据截止：{body['data_cutoff']}",
        f"本周完成性：{'UNKNOWN' if body['week_complete'] is None else str(body['week_complete']).upper()}；本月完成性：{'UNKNOWN' if body['month_complete'] is None else str(body['month_complete']).upper()}",
        f"最近完整周期观测：周 {body['last_observation_week']} / 月 {body['last_observation_month']}（不是正在进行的周期）",
        f"策略状态：{body['audit']['decision']['status']} / {body['audit']['decision']['explanation']}",
        "仅模拟交易/缓存研究；风险表中的ATR是裁决观测，未自动执行止损。",
        "TRUE/FALSE/UNKNOWN分别表示条件成立、不成立、暂不可确认；空值/null不代表零或条件不满足。",
        "下周关注：原始价新鲜度、完整周/月线、未知宏观数据、未成交订单及账户生命周期。",
        *body["limits"],
    ]
    heading = {
        "market": "六标的最新行情（日涨跌幅，非周收益）",
        "macro": "五维指标状态",
        "holdings": "模拟持仓",
        "orders": "模拟订单",
        "fills": "本周模拟成交",
        "equity": "账户资产记录",
        "unknown": "UNKNOWN项及原因",
        "risk": "ATR与风险观测（非成交）",
        "conditions": "入场与出场条件三态",
    }
    md = [
        "# " + title,
        *["- " + str(n) for n in notes],
        "",
        "## 当前模拟账户",
        "```json",
        json.dumps(body["account"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 建议状态（非订单）",
        "```json",
        json.dumps(body.get("recommended_position", {}), ensure_ascii=False, indent=2),
        "```",
    ]
    html = (
        "<h1>"
        + escape(title)
        + "</h1><ul>"
        + "".join("<li>" + escape(str(n)) + "</li>" for n in notes)
        + "</ul>"
        + "<h2>当前模拟账户</h2><pre>"
        + escape(json.dumps(body["account"], ensure_ascii=False, indent=2))
        + "</pre>"
        + "<h2>建议状态（非订单）</h2><pre>"
        + escape(
            json.dumps(
                body.get("recommended_position", {}), ensure_ascii=False, indent=2
            )
        )
        + "</pre>"
    )
    serial = {}
    for key, frame in tables.items():
        # Nested provenance stays JSON in a cell; no HTML injection or formula execution.
        frame = (
            frame.copy().map(
                lambda v: plain(v) if isinstance(v, (dict, list, tuple)) else v
            )
            if hasattr(frame, "map")
            else frame.copy().apply(
                lambda c: c.map(
                    lambda v: plain(v) if isinstance(v, (dict, list, tuple)) else v
                )
            )
        )
        serial[key] = json.loads(frame.to_json(orient="records", date_format="iso"))
        md += ["", "## " + heading[key]]
        if frame.empty:
            md += ["无记录 / 暂不可确认。"]
        else:

            def cell(v):
                return str(v).replace("|", "\\|").replace("\n", " ")

            md += [
                "| " + " | ".join(map(cell, frame.columns)) + " |",
                "| " + " | ".join(["---"] * len(frame.columns)) + " |",
            ]
            md += [
                "| " + " | ".join(cell(v) for v in row) + " |"
                for row in frame.fillna("—").itertuples(index=False, name=None)
            ]
        html += (
            "<h2>"
            + escape(heading[key])
            + "</h2>"
            + (
                frame.to_html(index=False, escape=True, na_rep="UNKNOWN")
                if len(frame)
                else "<p>无记录 / 暂不可确认。</p>"
            )
        )
    document = {
        "id": snapshot_id,
        "title": title,
        "snapshot_digest": snapshot.digest,
        "snapshot_id": snapshot_id,
        "as_of": body["as_of"],
        "notes": notes,
        "markdown": "\n".join(md) + "\n",
        "html": html,
        "tables": serial,
    }
    session.add(WeeklyReportRecord(id=snapshot_id, payload=plain(document)))
    session.flush()
    return document


def document_history(session):
    return [json.loads(r.payload) for r in session.query(WeeklyReportRecord).all()][
        ::-1
    ]


def export_document(document, path, kind):
    path = Path(path)
    if kind == "md":
        path.write_text(document["markdown"], encoding="utf8")
    elif kind == "xlsx":
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame({"说明": document["notes"]}).apply(
                lambda c: c.map(safe_cell)
            ).to_excel(writer, sheet_name="说明", index=False)
            for key, rows in document["tables"].items():
                pd.DataFrame(rows).apply(lambda c: c.map(safe_cell)).to_excel(
                    writer, sheet_name=key, index=False
                )
    elif kind == "csv":
        path.mkdir(parents=True, exist_ok=False)
        for key, rows in document["tables"].items():
            export_table(pd.DataFrame(rows), path / (key + ".csv"))
        (path / "report.md").write_text(document["markdown"], encoding="utf8")
        (path / "snapshot_identity.json").write_text(
            plain(
                {k: document[k] for k in ("snapshot_id", "snapshot_digest", "as_of")}
            ),
            encoding="utf8",
        )
    else:
        raise ValueError("支持md/xlsx/csv；PDF由Qt打印真实报告")
