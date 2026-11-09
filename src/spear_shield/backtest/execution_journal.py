"""B02 durable execution journal. Restart replays bound inputs, never resumes stale intents.

No market/account database is modified. Entries are append-only and content checked;
target cancellation tombstones survive process exit. Historical replay is allowed
before the tombstone's model phase, never after it. This is not live broker recovery.
"""

import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime

ATR_TARGET_POLICY_VERSION = "atr-target-invalidation-A-20261108-v1"


def encode(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str
    )


def identifier(value):
    return hashlib.sha256(encode(value).encode("utf8")).hexdigest()


class ExecutionJournal:
    def __init__(self, path=None):
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path is not None else ":memory:")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS audit (kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id))"
        )
        self.db.commit()

    def append(self, kind, key, payload):
        text = encode(payload)
        row = self.db.execute(
            "SELECT payload FROM audit WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        if row is not None:
            if row[0] != text:
                raise ValueError(f"执行审计冲突，拒绝覆盖: {kind}/{key}")
            return False
        with self.db:
            self.db.execute("INSERT INTO audit VALUES (?,?,?)", (kind, key, text))
        return True

    def get(self, kind, key):
        row = self.db.execute(
            "SELECT payload FROM audit WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def rows(self, kind):
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload FROM audit WHERE kind=? ORDER BY rowid", (kind,)
            )
        ]

    def register(self, target):
        self.append(
            "target",
            target.target_id,
            {
                "target_id": target.target_id,
                "signal_at": target.signal_at.isoformat(),
                "available_at": target.available_at.isoformat(),
                "reason": target.reason,
                "weights": dict(target.weights),
            },
        )

    def target_state(self, target_id):
        target = self.get("target", target_id)
        if target is None:
            return None
        cancellation = self.get("cancel", target_id)
        if cancellation:
            return {**target, **cancellation}
        receipts = [r for r in self.rows("receipt") if r["target_id"] == target_id]
        return {
            **target,
            "target_status": receipts[-1]["status"] if receipts else "pending",
        }

    def cancelled(self, target_id, model_time):
        row = self.get("cancel", target_id)
        return (
            row
            if row
            and datetime.fromisoformat(row["invalidation_time"])
            <= datetime.fromisoformat(model_time)
            else None
        )

    def close(self):
        self.db.close()
