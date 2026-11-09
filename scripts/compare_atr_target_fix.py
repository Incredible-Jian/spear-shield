"""Capture identical cached research inputs before/after B02 fix; no network."""

import json
import sys
from datetime import date
from pathlib import Path
from spear_shield.database.engine import Database
from spear_shield.services.workspace import Workspace
from spear_shield.services.research_dataset import load_operational_dataset
from spear_shield.backtest.strategy_replay import StrategyReplay
from spear_shield.backtest.models import BacktestConfig


def main():
    output = Path(sys.argv[1])
    if output.exists():
        raise FileExistsError(output)
    db = Database("sqlite:///D:/spear-shield/cache/phase5-preview/spear_shield.db")
    try:
        w = Workspace(db)
        result = StrategyReplay(
            load_operational_dataset(w),
            {s: w.history(s, "qfq") for s in ("159915", "563020", "511360", "511990")},
        ).run(
            BacktestConfig(
                date(2024, 1, 2), date(2026, 10, 30), 100000.0, 0.0003, 0.0005
            )
        )
        evidence = {
            "curve": json.loads(
                result.curve.to_json(orient="records", date_format="iso")
            ),
            "trades": result.trades,
            "orders": result.orders,
            "signals": result.signals,
            "metrics": result.metrics,
            "input_sha256": result.metadata["input_sha256"],
            "audit": result.metadata["strategy_audit"],
            "receipts": result.metadata["execution_receipts"],
            "target_states": result.metadata.get("target_states", []),
            "stop_events": result.metadata.get("stop_events", []),
        }
        output.write_text(
            json.dumps(evidence, ensure_ascii=False, default=str, allow_nan=False),
            encoding="utf8",
        )
        print(
            json.dumps(
                {"output": str(output), "metrics": result.metrics}, ensure_ascii=False
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
