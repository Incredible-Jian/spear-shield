"""Local cached-data audit; never downloads data or overwrites old evidence."""

from datetime import date, datetime, timezone
from collections import Counter
import hashlib
import json
from pathlib import Path

from spear_shield.backtest.lineage import validate_lineage
from spear_shield.backtest.models import BacktestConfig
from spear_shield.backtest.reporting import persist_report
from spear_shield.backtest.research import result_payload
from spear_shield.backtest.strategy_replay import StrategyReplay
from spear_shield.database.engine import Database
from spear_shield.services.research_dataset import load_operational_dataset
from spear_shield.services.workspace import Workspace


def main():
    root = Path(__file__).resolve().parents[1]
    base = root / "cache/phase65"
    folder = base / (
        "final_replay_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    if folder.exists():
        raise FileExistsError(folder)
    db = Database(
        "sqlite:///" + (root / "cache/phase5-preview/spear_shield.db").as_posix()
    )
    try:
        workspace = Workspace(db)
        dataset = load_operational_dataset(workspace)
        frames = {
            s: workspace.history(s, "qfq")
            for s in ("159915", "563020", "511360", "511990")
        }
        result = StrategyReplay(dataset, frames).run(
            BacktestConfig(
                date(2024, 1, 2), date(2026, 10, 30), 100000.0, 0.0003, 0.0005
            )
        )
        payload = result_payload(result)
        graph = payload["metadata"]["phase65_audit"]
        validate_lineage(json.loads(json.dumps(graph, default=str, ensure_ascii=False)))
        persist_report(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "request": {"phase": "6.5"},
                "runs": [
                    {
                        "name": result.metadata["name"],
                        "status": "incomplete_strategy_research",
                        "blockers": dataset.limitations,
                        "result": payload,
                    }
                ],
            },
            folder,
        )
        economics = {
            "curve": payload["curve"],
            "trades": result.trades,
            "metrics": result.metrics,
        }
        economic_hash = hashlib.sha256(
            json.dumps(economics, sort_keys=True, default=str, allow_nan=False).encode()
        ).hexdigest()
        baseline = json.loads(
            (base / "baseline_summary.json").read_text(encoding="utf8")
        )
        attribution = {k: v for k, v in graph["attribution"].items() if k != "daily"}
        evidence = {
            "scope": "真实缓存数据、回溯前复权、假设发布时间的局部策略研究；不是完整策略认证",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": graph["identity"]["config"],
            "metrics": result.metrics,
            "weeks": len(result.metadata["strategy_audit"]),
            "attack_trades": result.metadata["attack_trade_count"],
            "defense_trades": result.metadata["defense_trade_count"],
            "economics_sha256": economic_hash,
            "baseline_economics_sha256": baseline["economics_sha256"],
            "economics_unchanged": economic_hash == baseline["economics_sha256"],
            "input_sha256": result.metadata["input_sha256"],
            "run_id": graph["run_id"],
            "lineage_status": graph["status"],
            "lineage_node_counts": {k: len(v) for k, v in graph["nodes"].items()},
            "lineage_unlinked": graph["unlinked"],
            "json_roundtrip_validation": True,
            "input_gaps": result.metadata["input_gaps"],
            "effective_start": result.metadata["effective_start"],
            "effective_end": result.metadata["effective_end"],
            "execution_coverage": {
                s: {
                    "rows": len(rows),
                    "start": rows[0]["date"],
                    "end": rows[-1]["date"],
                }
                for s, rows in result.metadata["input_bars"].items()
            },
            "entry_rule_status_counts": {
                name: dict(
                    Counter(
                        a["rule_status"][name]
                        for a in result.metadata["strategy_audit"]
                    )
                )
                for name in result.metadata["strategy_audit"][0]["rule_status"]
                if name.startswith("ENTRY_")
            },
            "triggered_but_blocked_entry_examples": [
                {"as_of": a["as_of"], "explanation": a["explanation"], "rule": name}
                for a in result.metadata["strategy_audit"]
                for name, state in a["rule_status"].items()
                if name.startswith("ENTRY_")
                and state == "触发"
                and a["selected"] != name
            ],
            "limitations": dataset.limitations,
            "attribution": attribution,
            "identity": graph["identity"],
            "local_report_directory": folder.relative_to(root).as_posix(),
            "synthetic_markers": [
                s
                for values in result.metadata["sources"].values()
                for s in values
                if "synthetic" in s.lower() or "test-only" in s.lower()
            ],
        }
        target = root / "docs/phase6_5/manifests/replay_evidence.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                evidence, ensure_ascii=False, indent=2, default=str, allow_nan=False
            )
            + "\n",
            encoding="utf8",
        )
        print(
            json.dumps(
                {
                    k: v
                    for k, v in evidence.items()
                    if k not in {"identity", "limitations", "attribution"}
                },
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
