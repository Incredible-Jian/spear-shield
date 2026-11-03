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
    for item in payload["runs"]:
        result = item.get("result")
        metrics = result["metrics"] if result else {}

        def percent(key):
            value = metrics.get(key)
            return "—" if value is None else f"{value:.2%}"

        coverage = result["metadata"].get("coverage_note", "") if result else ""
        rows.append(
            f"<tr><td>{e(item['name'])}<br>{e(coverage)}</td><td>{e(item['status'])}</td>"
            f"<td>{percent('total_return')}</td><td>{percent('annual_return')}</td>"
            f"<td>{percent('max_drawdown')}</td><td>{e('; '.join(item['blockers']))}</td></tr>"
        )
    return (
        "<html><head><meta charset='utf-8'></head><body><h1>矛与盾 · 历史回测研究报告</h1>"
        f"<p>生成时间：{e(payload['generated_at'])}</p>"
        "<p>研究单位绩效不是正式全策略历史收益；空白表示不可计算，不代表0收益。</p>"
        "<table border='1' cellpadding='6'><tr><th>方案</th><th>状态</th><th>收益</th><th>年化</th><th>最大回撤</th><th>阻塞原因</th></tr>"
        + "".join(rows)
        + "</table><pre>"
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
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (directory / "SHA256.txt").write_text(f"{digest}  report.json\n", encoding="ascii")
    return directory


def export_bundle(directory, destination):
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for file in sorted(Path(directory).iterdir()):
            if file.is_file():
                archive.write(file, file.name)
