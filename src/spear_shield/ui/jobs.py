"""QProcess网络任务：超时/取消时终止抓取进程，数据库只由主进程写入。"""

from __future__ import annotations

import json
import sys
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


class ProcessJob(QObject):
    succeeded = Signal(dict)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.cancel("更新超时，未写入缓存"))
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.process.started.connect(self._started)
        self.reason = None
        self._done = True

    @property
    def busy(self):
        return not self._done

    def start(self, program, args, timeout_ms=45000):
        if self.busy:
            raise RuntimeError("已有更新任务运行中")
        self.reason = None
        self._done = False
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(env)
        self.process.start(program, args)
        self.timer.start(timeout_ms)
        self.busy_changed.emit(True)

    def fetch(self, code, start, end, adjust, provider):
        self.start(
            sys.executable,
            [
                "-m",
                "spear_shield.data.fetch_worker",
                code,
                start,
                end,
                adjust,
                provider,
            ],
        )

    def cancel(self, reason="已取消，未写入缓存"):
        if self.busy:
            self.reason = reason
            self.process.kill()

    def shutdown(self):
        self.timer.stop()
        if self.busy:
            self.reason = "窗口关闭，更新任务已终止"
            self.process.kill()
            self.process.waitForFinished(1500)

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self._complete(False, "无法启动数据抓取进程")

    def _started(self):
        if self.reason:
            self.process.kill()

    def _finished(self, code, status):
        if self._done:
            return
        if self.reason:
            self._complete(False, self.reason)
            return
        try:
            payload = json.loads(
                bytes(self.process.readAllStandardOutput()).decode("utf-8")
            )
            if not isinstance(payload, dict):
                raise ValueError("抓取进程返回格式不正确")
            if code != 0 or "error" in payload:
                raise ValueError(payload.get("error", "接口更新失败"))
            if (
                not isinstance(payload, dict)
                or "data" not in payload
                or "source" not in payload
            ):
                raise ValueError("抓取进程返回格式不正确")
            self._complete(True, payload)
        except (ValueError, UnicodeError, TypeError) as exc:
            self._complete(False, str(exc))

    def _complete(self, success, payload):
        if self._done:
            return
        self._done = True
        self.timer.stop()
        self.busy_changed.emit(False)
        (self.succeeded if success else self.failed).emit(payload)
