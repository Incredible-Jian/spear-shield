"""真实缓存数据周报及安全表格导出；不生成投资判断或回测收益。"""

from __future__ import annotations

from datetime import date, timedelta
from html import escape
from pathlib import Path
import pandas as pd
from math import isfinite
from numbers import Real


def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_table(frame: pd.DataFrame, path: Path):
    out = frame.copy().apply(lambda column: column.map(safe_cell))
    if path.suffix.lower() == ".xlsx":
        out.to_excel(path, index=False, engine="openpyxl")
    elif path.suffix.lower() == ".csv":
        out.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        raise ValueError("仅支持.csv或.xlsx")


def weekly_report(workspace, end: date, audits: list[dict]) -> dict:
    start = end - timedelta(days=end.weekday())
    rows = []
    for code, symbol in workspace_symbols().items():
        df = workspace.history(code)
        if df.empty:
            rows.append(
                {
                    "标的": f"{symbol.name} {code}",
                    "状态": "数据缺失",
                    "区间涨跌%": None,
                    "最后行情日": "—",
                    "来源": "—",
                }
            )
            continue
        dates = pd.to_datetime(df.date).dt.date
        week = df.loc[(dates >= start) & (dates <= end)]
        prior = df.loc[dates < start]
        change = None
        if len(week) and len(prior) and prior.iloc[-1].close > 0:
            change = (week.iloc[-1].close / prior.iloc[-1].close - 1) * 100
        rows.append(
            {
                "标的": f"{symbol.name} {code}",
                "状态": "缓存前复权观察" if len(week) else "本周无缓存",
                "区间涨跌%": change,
                "最后行情日": str(week.iloc[-1].date) if len(week) else "—",
                "来源": ", ".join(sorted(set(week.source))) if len(week) else "—",
            }
        )
    # 审计时间包含日期范围；报告不从未来审计推导历史判断。
    relevant = [
        a
        for a in audits
        if start
        <= pd.Timestamp(a["snapshot"]["as_of"]).tz_convert("Asia/Shanghai").date()
        <= end
    ]
    relevant.sort(key=lambda a: pd.Timestamp(a["snapshot"]["as_of"]), reverse=True)
    latest = relevant[0] if relevant else None
    previous = [
        a
        for a in audits
        if pd.Timestamp(a["snapshot"]["as_of"]).tz_convert("Asia/Shanghai").date()
        < start
    ]
    previous.sort(key=lambda a: pd.Timestamp(a["snapshot"]["as_of"]), reverse=True)
    analysis = (latest.get("analysis") or {}) if latest else {}
    old_analysis = (previous[0].get("analysis") or {}) if previous else {}
    macro = analysis.get("macro") or {}
    dimensions = macro.get("dimensions", [])
    old_dimensions = (old_analysis.get("macro") or {}).get("dimensions", [])

    def values(item):
        v = item.get("value", [])
        return list(v) if isinstance(v, (list, tuple)) else [v]

    def show(v):
        return (
            " / ".join(
                (
                    f"{x:.4f}"
                    if isinstance(x, Real) and not isinstance(x, bool) and isfinite(x)
                    else "—"
                )
                for x in v
            )
            or "—"
        )

    macro_rows = []
    names = ("60月线斜率", "股债性价比", "风格Z-Score", "期权IV", "两融水位")
    for i, name in enumerate(names):
        d = dimensions[i] if len(dimensions) > i else {}
        old = old_dimensions[i] if len(old_dimensions) > i else {}
        a, b = values(d), values(old)
        delta = []
        if len(a) == len(b) and all(
            isinstance(v, Real) and not isinstance(v, bool) and isfinite(v)
            for v in (*a, *b)
        ):
            delta = [x - y for x, y in zip(a, b)]
        macro_rows.append(
            {
                "维度": name,
                "本周最近审计": show(a),
                "较上周最后审计变化": show(delta),
                "状态": d.get("status", "数据缺失" if i == 3 else "待确认"),
                "来源": ", ".join(d.get("sources", [])) or "未接入",
            }
        )
    macro_frame = pd.DataFrame(macro_rows)
    signals = []
    for audit in relevant:
        selected = audit["decision"].get("selected")
        for rule in audit["decision"]["results"]:
            if rule["status"] != "触发":
                continue
            signals.append(
                {
                    "审计时间": audit["snapshot"]["as_of"],
                    "规则": rule["rule_id"],
                    "处理": (
                        "选中研究建议（未执行）"
                        if selected and selected["rule_id"] == rule["rule_id"]
                        else "候选/预警（未执行）"
                    ),
                    "依据": rule["explanation"],
                }
            )
    signal_frame = pd.DataFrame(signals, columns=["审计时间", "规则", "处理", "依据"])
    defense = analysis.get("defense") or {}
    allocation_rows = [
        {
            "防守资产": code,
            "端内建议%": weight * 100,
            "状态": defense.get("status", "待确认"),
        }
        for code, weight in (defense.get("weights") or {}).items()
    ]
    if defense.get("unallocated"):
        allocation_rows.append(
            {
                "防守资产": "待分配",
                "端内建议%": defense["unallocated"] * 100,
                "状态": "转移比例待确认",
            }
        )
    allocation = pd.DataFrame(
        allocation_rows, columns=["防守资产", "端内建议%", "状态"]
    )
    cycle = (analysis.get("cycle") or {}).get("status", "未生成正式共振裁决")
    title = f"每周研究报告 · {start} — {end}"
    text = (
        "本周无策略审计记录。" if latest is None else latest["decision"]["explanation"]
    )
    frame = pd.DataFrame(rows)
    notes = [
        "最近审计五维状态："
        + macro.get("status", "五维不完整；IV缺失，股债和其他定义待确认"),
        "缓存覆盖不等于完整交易周；区间涨跌仅为已有记录间观察，不是策略收益。",
        "信号来自当前载入的审计历史，不是全量绩效统计；防守权重为防守端内部比例。",
        "下周观察：数据新鲜度、已结算周/月线、缺失宏观数据与规则确认进度。",
    ]

    def html_table(df):
        return df.to_html(
            index=False,
            na_rep="—",
            escape=True,
            float_format=lambda v: f"{v:.4f}",
            border=0,
        ).replace("<table ", '<table cellpadding="6" cellspacing="0" width="100%" ')

    html = f"<h1>{escape(title)}</h1><h2>本周市场观察</h2>{html_table(frame)}<h2>五维指标与变化</h2>{html_table(macro_frame)}<h2>周期与策略裁决</h2><p>{escape(cycle)}；{escape(text)}</p>"
    html += "<h2>触发信号（未执行）</h2>" + (
        html_table(signal_frame)
        if len(signal_frame)
        else "<p>所载入的本周审计中无触发记录。</p>"
    )
    html += "<h2>防守端建议配置</h2>" + (
        html_table(allocation)
        if len(allocation)
        else "<p>配置不可计算或待确认，未生成建议权重。</p>"
    )
    html += (
        "<h2>风险与下周观察</h2><ul>"
        + "".join(f"<li>{escape(n)}</li>" for n in notes)
        + "</ul>"
    )
    return {
        "title": title,
        "data": frame,
        "html": html,
        "notes": notes,
        "decision": text,
        "macro": macro_frame,
        "signals": signal_frame,
        "allocation": allocation,
        "cycle": cycle,
    }


def workspace_symbols():
    from .workspace import SYMBOLS

    return SYMBOLS


def export_report_excel(report, path):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        report["data"].apply(lambda column: column.map(safe_cell)).to_excel(
            writer, sheet_name="市场观察", index=False
        )
        pd.DataFrame(
            {
                "说明": [
                    report["title"],
                    report["cycle"],
                    report["decision"],
                    *report["notes"],
                ]
            }
        ).apply(lambda column: column.map(safe_cell)).to_excel(
            writer, sheet_name="策略与风险", index=False
        )
        for key, sheet in (
            ("macro", "五维变化"),
            ("signals", "信号记录"),
            ("allocation", "防守建议"),
        ):
            report[key].apply(lambda column: column.map(safe_cell)).to_excel(
                writer, sheet_name=sheet, index=False
            )
