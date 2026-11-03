"""Collect free snapshots; no database import, credentials or paid API required."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spear_shield.data.research_sources import (  # noqa: E402
    DEFAULT_OUTPUT,
    collect_research_sources,
    research_tasks,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--timeout", type=float, default=45, help="Per-task limit, <=45 seconds"
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--include-market", action="store_true", help="Also fetch unadjusted ETF prices"
    )
    parser.add_argument(
        "--task", action="append", help="Only collect these task keys (repeatable)"
    )
    parser.add_argument(
        "--list", action="store_true", help="List all task keys without network access"
    )
    args = parser.parse_args(argv)
    catalogue = research_tasks(include_market=True)
    if args.list:
        for task in catalogue:
            print(task.key)
        return 0
    tasks = research_tasks(include_market=args.include_market)
    if args.task:
        unknown = set(args.task) - {t.key for t in catalogue}
        if unknown:
            parser.error("Unknown task key")
        tasks = tuple(t for t in catalogue if t.key in args.task)
    if not 0 < args.timeout <= 45 or not 1 <= args.workers <= 8:
        parser.error("timeout must be (0,45]; workers must be [1,8]")
    manifest = collect_research_sources(
        args.output, tasks=tasks, timeout=args.timeout, workers=args.workers
    )
    records = manifest["runs"][-1]["tasks"]
    for record in sorted(records, key=lambda r: r["key"]):
        rows = sum(a["rows"] for a in record["artifacts"])
        print(
            f"{record['key']}: {record['status']} rows={rows} {record.get('error', '')}"
        )
    print(f"Manifest: {(args.output / 'manifest.json').resolve()}")
    return 1 if any(r["status"] == "failed" for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
