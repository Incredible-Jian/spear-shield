"""策略审计与逐项条件证据。"""

import json
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QPlainTextEdit
from .base import BasePage
from ..widgets import table, fill, note


class SignalCenterPage(BasePage):
    def __init__(self, controller=None, parent=None):
        super().__init__(
            "策略信号中心", "SIGNALS / P0 > P1 > P2 > P3 · 可解释审计", parent
        )
        self.controller = controller
        bar = QHBoxLayout()
        self.history = QComboBox()
        bar.addWidget(self.history, 1)
        self.diagnose = QPushButton("运行可用性诊断")
        bar.addWidget(self.diagnose)
        self.prepare = QPushButton("生成本周策略裁决")
        self.confirm = QPushButton("确认保存快照（不交易）")
        self.confirm.setEnabled(False)
        bar.addWidget(self.prepare)
        bar.addWidget(self.confirm)
        self.content_layout.addLayout(bar)
        self.status = note("尚无审计记录")
        self.content_layout.addWidget(self.status)
        self.rules = table(
            ["规则", "优先级", "裁决状态", "数据/口径可判断性", "建议 / 原因"], 300
        )
        self.content_layout.addWidget(self.rules)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(220)
        self.content_layout.addWidget(self.detail)
        self.content_layout.addWidget(
            note(
                "诊断使用明确的空仓研究假设和缺失行情输入，不等于账户建议，不执行任何订单。"
            )
        )
        self.history.currentIndexChanged.connect(self.render_audit)
        self.rules.itemSelectionChanged.connect(self.render_detail)
        if controller:
            self.diagnose.clicked.connect(controller.diagnose)
            self.prepare.clicked.connect(self.prepare_weekly)
            self.confirm.clicked.connect(self.confirm_weekly)
        self.refresh()

    def prepare_weekly(self):
        from ...services.weekly_workflow import prepare_weekly

        try:
            with self.controller.database.new_session() as session:
                self.draft = prepare_weekly(session, self.controller.workspace)
            body = self.draft["body"]
            self.audit = body["audit"]
            self.status.setText(
                f"草稿 {body['id']} · 周线完成={body['week_complete']} · UNKNOWN={len(body['unknown'])} · 请审阅后确认；不自动下单"
            )
            fill(
                self.rules,
                [
                    [
                        r["rule_id"],
                        r["priority"],
                        r["status"],
                        (
                            "UNKNOWN"
                            if any(c["value"] is None for c in r["conditions"])
                            else "可计算"
                        ),
                        r["explanation"],
                    ]
                    for r in self.audit["decision"]["results"]
                ],
            )
            self.detail.setPlainText(
                json.dumps(
                    {
                        k: body[k]
                        for k in (
                            "as_of",
                            "data_cutoff",
                            "market",
                            "week_complete",
                            "month_complete",
                            "unknown",
                            "account_position_known",
                            "recommended_position",
                            "limits",
                        )
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            self.confirm.setEnabled(True)
        except Exception as exc:
            self.status.setText("生成失败：" + str(exc))
            self.confirm.setEnabled(False)

    def confirm_weekly(self):
        from ...services.weekly_workflow import confirm_weekly

        try:
            with self.controller.database.new_session() as session:
                id = confirm_weekly(session, self.draft)
                session.commit()
            self.confirm.setEnabled(False)
            self.controller.refresh()
            self.refresh()
            self.status.setText("已保存不可覆盖裁决快照 " + id + "；没有执行订单")
        except Exception as exc:
            self.status.setText("保存失败：" + str(exc))

    def refresh(self):
        if not self.controller:
            return
        selected = self.history.currentIndex()
        self.history.blockSignals(True)
        self.history.clear()
        for a in self.controller.audits:
            prefix = (
                "空仓可用性诊断"
                if not a.get("weekly_snapshot_id")
                and not a["snapshot"]["weekly_final"]
                and not a["snapshot"]["facts"]
                else (
                    "本周缓存裁决（非成交）"
                    if a.get("weekly_snapshot_id")
                    else "审计记录"
                )
            )
            self.history.addItem(
                f"{prefix} · {a['snapshot']['as_of']} · {a['decision']['status']}"
            )
        self.history.setCurrentIndex(
            min(max(selected, 0), len(self.controller.audits) - 1)
        )
        self.history.blockSignals(False)
        self.render_audit()

    def render_audit(self):
        idx = self.history.currentIndex()
        self.audit = (
            self.controller.audits[idx]
            if self.controller and 0 <= idx < len(self.controller.audits)
            else None
        )
        if not self.audit:
            fill(self.rules, [])
            self.status.setText("暂无审计记录，可运行诊断查看缺失与待确认规则。")
            self.detail.setPlainText("选择审计记录或运行可用性诊断。")
            return
        self.status.setText(
            self.audit["decision"]["explanation"]
            + " · 规则版本 "
            + self.audit["rule_version"]
        )
        fill(
            self.rules,
            [
                [
                    r["rule_id"],
                    "入场" if r["priority"] == 4 else "P" + str(r["priority"]),
                    r["status"],
                    (
                        "不可判断"
                        if r["conditions"]
                        and all(c["value"] is None for c in r["conditions"])
                        else (
                            "部分可判断"
                            if any(c["value"] is None for c in r["conditions"])
                            else "完整可判断" if r["conditions"] else "不可判断"
                        )
                    ),
                    r["explanation"],
                ]
                for r in self.audit["decision"]["results"]
            ],
        )
        if self.rules.rowCount():
            self.rules.selectRow(0)
            self.render_detail()

    def render_detail(self):
        row = self.rules.currentRow()
        if not getattr(self, "audit", None) or row < 0:
            return
        results = self.audit["decision"]["results"]
        if row >= len(results):
            return
        rule = results[row]
        keys = {k for c in rule["conditions"] for k in c["inputs"]}
        payload = {
            "rule": rule,
            "evidence": {
                k: self.audit["snapshot"]["facts"].get(k, "数据缺失") for k in keys
            },
            "confirmed_definitions": self.audit["policy"],
        }
        saved = next(
            (
                s
                for s in self.controller.weekly_snapshots
                if s["id"] == self.audit.get("weekly_snapshot_id")
            ),
            None,
        )
        if saved:
            payload["saved_weekly_context"] = {
                k: saved[k]
                for k in (
                    "id",
                    "as_of",
                    "data_cutoff",
                    "market",
                    "week_complete",
                    "month_complete",
                    "recommended_position",
                    "unknown",
                    "limits",
                )
                if k in saved
            }
        self.detail.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
