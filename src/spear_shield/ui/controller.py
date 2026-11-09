"""桌面控制器：显式本地缓存/来源，网络任务与持久存储分离。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
from PySide6.QtCore import QObject, Signal, QTimer

from ..services.workspace import Workspace, SYMBOLS, PRICE_LABELS
from ..database.strategy_audit import load_history
from ..portfolio.paper_account import account_view
from ..strategy import Snapshot, Position
from ..strategy.service import run_research
from .jobs import ProcessJob
from ..utils.logger import get_logger

logger = get_logger(__name__)


class Controller(QObject):
    changed = Signal()
    message = Signal(str)

    def __init__(self, database, data_dir, parent=None):
        super().__init__(parent)
        self.database = database
        self.data_dir = Path(data_dir)
        self.workspace = Workspace(database)
        self.job = ProcessJob(self)
        self.job.succeeded.connect(self._fetched)
        self.job.failed.connect(self._failed)
        self.frames = {}
        self.summaries = []
        self.audits = []
        self.pending = None
        self.batch_active = False
        self.batch_queue = []
        self.batch_total = 0
        self.batch_results = []
        self.refresh()

    def refresh(self):
        self.frames = {
            (code, adjust): self.workspace.history(code, adjust)
            for code in SYMBOLS
            for adjust in PRICE_LABELS
        }
        self.summaries = self.workspace.summary()
        with self.database.new_session() as session:
            from ..services.weekly_workflow import weekly_history
            from ..services.weekly_documents import document_history
            from ..portfolio.paper_execution import execution_history

            self.weekly_snapshots = weekly_history(session)
            self.weekly_documents = document_history(session)
            self.paper_history = execution_history(session)
            self.audits = [
                dict(row["audit"], weekly_snapshot_id=row["id"])
                for row in self.weekly_snapshots
            ] + load_history(session)
            self.audits.sort(
                key=lambda a: pd.Timestamp(a["snapshot"]["as_of"]), reverse=True
            )
            from ..services.market_view import quote_view

            quotes = {}
            for code, symbol in SYMBOLS.items():
                quote = quote_view(symbol, self.history(code, "none"), pd.DataFrame())
                if quote["price"] is not None:
                    quotes[code] = {
                        "price": quote["price"],
                        "date": quote["date"],
                        "source": quote["source"],
                    }
            self.account = account_view(session, quotes)
        self.changed.emit()

    def history(self, code, adjust="qfq"):
        return self.frames.get((code, adjust), pd.DataFrame()).copy(deep=True)

    def fetch(self, code, start, end, adjust="qfq", provider="akshare"):
        if self.batch_active:
            self.message.emit("六标的批量更新进行中；可取消后更新所选")
            return
        self._start_fetch(code, start, end, adjust, provider)

    def _start_fetch(self, code, start, end, adjust="qfq", provider="akshare"):
        if self.job.busy:
            self.message.emit("已有更新任务，请等待或取消")
            return
        self.pending = (code, adjust, provider)
        self.message.emit(f"正在更新 {code}，最长45秒；界面可继续操作")
        self.job.fetch(code, start, end, adjust, provider)

    def fetch_core(self):
        if self.job.busy or self.batch_active:
            self.message.emit("已有更新任务，请等待或取消")
            return
        self.batch_queue = [(code, "qfq") for code in SYMBOLS]
        self.batch_total = len(self.batch_queue)
        self.batch_results = []
        self.batch_active = True
        self._next_batch()

    def _next_batch(self):
        if not self.batch_active:
            return
        if not self.batch_queue:
            self.batch_active = False
            ok = sum(r["success"] for r in self.batch_results)
            self.message.emit(
                f"六标的更新结束：成功{ok}/{self.batch_total}；失败标的保留原缓存，详见数据管理日志"
            )
            self.changed.emit()
            return
        code, adjust = self.batch_queue.pop(0)
        frame = self.history(code, adjust)
        start = frame.date.min().date().isoformat() if len(frame) else "2010-01-01"
        self._start_fetch(
            code,
            start,
            end=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            adjust=adjust,
        )

    def cancel_updates(self):
        self.batch_active = False
        self.batch_queue = []
        self.job.cancel()
        self.message.emit("已取消更新队列；已有真实缓存保留")
        self.changed.emit()

    def shutdown(self):
        self.batch_active = False
        self.batch_queue = []
        self.job.shutdown()

    def _fetched(self, payload):
        try:
            code, adjust, _ = self.pending
            count = self.workspace.store(
                code, adjust, pd.DataFrame(payload["data"]), payload["source"]
            )
            self.message.emit(
                f"已更新 {code} 共 {count} 行；来源 {payload['source']}，非实时订阅"
            )
        except Exception as exc:
            self._failed(f"校验/保存失败：{exc}")
            return
        self.pending = None
        if self.batch_active:
            self.batch_results.append({"code": code, "success": True})
            QTimer.singleShot(0, self._next_batch)
        self.refresh()

    def _failed(self, message):
        logger.warning("行情更新失败：%s", message)
        if self.pending:
            code, _, provider = self.pending
            self.workspace.failure(code, provider)
        self.pending = None
        self.message.emit(f"更新失败：{message}。保留原缓存，不视为实时。")
        if self.batch_active:
            self.batch_results.append({"success": False, "error": message})
            QTimer.singleShot(0, self._next_batch)
        self.refresh()

    def diagnose(self):
        # 不把未经批准的缓存序列包装成策略证据；诊断有明确独立标签。
        with self.database.new_session() as session:
            result = run_research(
                session, Snapshot(datetime.now(timezone.utc)), Position()
            )
            session.commit()
        self.message.emit("已保存空仓研究诊断；无已确认行情输入，不是账户交易建议")
        self.refresh()
        return result
