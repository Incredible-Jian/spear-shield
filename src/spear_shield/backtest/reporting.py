"""可重复检查的报告包：参数、来源、曲线、逐笔记录、阻塞状态一起保存。"""

import hashlib
import html
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import pandas as pd

from ..services.reporting import safe_cell


def report_html(payload):
    e = lambda x: html.escape(str(x))
    rows = []
    details = []
    for item in payload["runs"]:
        result = item.get("result")
        metrics = result["metrics"] if result else {}

        def percent(key):
            value = metrics.get(key)
            return "—" if value is None else f"{value:.2%}"

        coverage = result["metadata"].get("coverage_note", "") if result else ""
        assessment = (
            "完整可判断"
            if result and result["metadata"].get("complete_strategy_validated") is True
            else "部分可判断" if result else "不可判断"
        )
        rows.append(
            f"<tr><td>{e(item['name'])}<br>{e(coverage)}</td><td>{e(assessment)} / {e(item['status'])}</td>"
            f"<td>{percent('total_return')}</td><td>{percent('annual_return')}</td>"
            f"<td>{percent('max_drawdown')}</td><td>{e('; '.join(item['blockers']))}</td></tr>"
        )
        audit = result["metadata"].get("phase65_audit") if result else None
        if audit:
            attribution = audit["attribution"]
            asset_rows = "".join(
                f"<tr><td>{e(a['symbol'])}</td><td>{e(a['scope'])}</td><td>{a['net_pnl']:.4f}</td><td>{a['fees']:.4f}</td><td>{a['trade_count']}</td></tr>"
                for a in attribution["assets"]
            )
            details.append(
                f"<h2>{e(item['name'])} 损益归因</h2><p>完整策略收益：未认证；以下为研究单位逐资产净损益，费用已计入一次，滑点已在成交价内。</p>"
                "<table border='1' cellpadding='6'><tr><th>资产</th><th>范围</th><th>净损益</th><th>已计手续费</th><th>成交笔数</th></tr>"
                + asset_rows
                + "</table>"
                f"<p>现金独立收益（含浮点残差）：{attribution['cash']['independent_pnl']:.6f}；末现金{attribution['cash']['end_balance']:.4f}不是利润。归因残差{attribution['total_residual']:.8f}。</p>"
                f"<p>缺失输入：{e(', '.join(result['metadata'].get('input_gaps', [])))}。进攻零交易不代表策略表现优秀。运行指纹：{e(audit['run_id'])}。</p>"
            )
    return (
        "<html><head><meta charset='utf-8'></head><body><h1>矛与盾 · 历史回测研究报告</h1>"
        f"<p>生成时间：{e(payload['generated_at'])}</p>"
        "<p>研究单位绩效不是正式全策略历史收益；空白表示不可计算，不代表0收益。</p>"
        "<table border='1' cellpadding='6'><tr><th>方案</th><th>状态</th><th>收益</th><th>年化</th><th>最大回撤</th><th>阻塞原因</th></tr>"
        + "".join(rows)
        + "</table>"
        + "".join(details)
        + "<pre>"
        + e(json.dumps(payload["request"], ensure_ascii=False, indent=2))
        + "</pre><p>完整来源、费用、滑点、信号、订单和局限见 report.json；曲线与交易见CSV。</p></body></html>"
    )


def persist_report(payload, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    text = json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False, default=str
    )
    (directory / "report.json").write_text(text, encoding="utf-8", newline="\n")
    (directory / "report.html").write_text(report_html(payload), encoding="utf-8")
    for i, item in enumerate(payload["runs"]):
        if item["result"]:
            for field in ("curve", "trades", "orders", "signals"):
                frame = pd.DataFrame(item["result"][field])
                # Series.map兼容pandas2.0；DataFrame.map要2.1才提供。
                for column in frame.columns:
                    frame[column] = frame[column].map(safe_cell)
                frame.to_csv(
                    directory / f"{i}_{field}.csv", index=False, encoding="utf-8-sig"
                )
            audit = item["result"]["metadata"].get("phase65_audit")
            if audit:
                pd.DataFrame(audit["attribution"]["assets"]).to_csv(
                    directory / f"{i}_asset_attribution.csv",
                    index=False,
                    encoding="utf-8-sig",
                )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (directory / "SHA256.txt").write_text(f"{digest}  report.json\n", encoding="ascii")
    return directory


def export_bundle(directory, destination):
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for file in sorted(Path(directory).iterdir()):
            if file.is_file():
                archive.write(file, file.name)
