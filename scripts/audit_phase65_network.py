"""单独、有上限地执行原有网络测试，不把skip/超时算通过。"""

import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "cache/phase65/network"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for name in ("test_fetch_etf_daily", "test_fetch_index_daily", "test_fetch_margin"):
        start = time.monotonic()
        xml = output / f"{name}.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            f"tests/integration/test_akshare_provider.py::{name}",
            "-q",
            f"--junitxml={xml}",
            f"--basetemp={output/name}",
        ]
        row = {"test": name, "timeout_seconds": 40}
        try:
            run = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=40,
            )
            (output / f"{name}.log").write_text(
                run.stdout + run.stderr, encoding="utf-8"
            )
            row["exit_code"] = run.returncode
            test = ET.parse(xml).find(".//testcase") if xml.exists() else None
            if test is None:
                row.update(status="FAIL", category="test_runner_failure")
            elif test.find("skipped") is not None:
                reason = test.find("skipped").attrib.get("message", "")
                low = reason.lower()
                category = (
                    "rate_limited"
                    if any(s in low for s in ("429", "rate limit", "too many"))
                    else (
                        "network_unavailable"
                        if any(
                            s in low
                            for s in (
                                "connection",
                                "timeout",
                                "resolve",
                                "network",
                                "proxy",
                            )
                        )
                        else "unclassified_provider_error_possible_code_issue"
                    )
                )
                row.update(
                    status="SKIPPED",
                    category=category,
                    exception_reason_recorded_locally=True,
                )
            elif test.find("failure") is not None or test.find("error") is not None:
                row.update(status="FAIL", category="data_quality_or_code_failure")
            elif run.returncode == 0:
                row.update(status="PASS", category="success")
            else:
                row.update(status="FAIL", category="runner_exit")
        except subprocess.TimeoutExpired:
            row.update(
                status="TIMEOUT",
                category="provider_call_exceeded_limit_not_counted_pass",
            )
        row["elapsed_seconds"] = round(time.monotonic() - start, 2)
        results.append(row)
        print(json.dumps(row), flush=True)
    summary = {
        "tests": results,
        "passed": sum(r["status"] == "PASS" for r in results),
        "skipped": sum(r["status"] == "SKIPPED" for r in results),
        "timeouts": sum(r["status"] == "TIMEOUT" for r in results),
        "failed": sum(r["status"] == "FAIL" for r in results),
        "limitations": [
            "原测试捕获所有提供方异常并skip，未分类的skip不能证明代码无误",
            "超时仅说明请求未在预算内完成，不证明永久不可得",
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
