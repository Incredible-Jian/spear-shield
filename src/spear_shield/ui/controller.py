"""桌面控制器：显式本地缓存/来源，网络任务与持久存储分离。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from PySide6.QtCore import QObject, Signal

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
        self.refresh()

    def refresh(self):
        self.frames = {
            (code, adjust): self.workspace.history(code, adjust)
            for code in SYMBOLS
            for adjust in PRICE_LABELS
        }
        self.summaries = self.workspace.summary()
        with self.database.new_session() as session:
            self.audits = load_history(session)
            quotes = {
                code: {"price": df.iloc[-1].close, "date": str(df.iloc[-1].date)}
                for (code, adjust), df in self.frames.items()
                if adjust == "none" and len(df)
            }
            self.account = account_view(session, quotes)
        self.changed.emit()

    def history(self, code, adjust="qfq"):
        return self.frames.get((code, adjust), pd.DataFrame()).copy(deep=True)

    def fetch(self, code, start, end, adjust="qfq", provider="akshare"):
        if self.job.busy:
            self.message.emit("已有更新任务，请等待或取消")
            return
        self.pending = (code, adjust, provider)
        self.message.emit(f"正在更新 {code}，最长45秒；界面可继续操作")
        self.job.fetch(code, start, end, adjust, provider)

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
        self.refresh()

    def _failed(self, message):
        logger.warning("行情更新失败：%s", message)
        if self.pending:
            code, _, provider = self.pending
            self.workspace.failure(code, provider)
        self.pending = None
        self.message.emit(f"更新失败：{message}。保留原缓存，不视为实时。")
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
