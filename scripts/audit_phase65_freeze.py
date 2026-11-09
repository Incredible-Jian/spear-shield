"""Freeze actual local audit evidence; no Git mutations, uploads or source copying."""

import ast
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET

from spear_shield.strategy.operational import DEFINITION_VERSION, operational_policy
from spear_shield.backtest.lineage import digest, implementation_hashes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/phase6_5/manifests"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return (
        subprocess.check_output(["git", "-c", "core.quotepath=false", *args], cwd=ROOT)
        .decode("utf8")
        .strip()
    )


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf8"))


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str)
        + "\n",
        encoding="utf8",
    )


def main():
    xml = ET.parse(ROOT / "cache/phase65/final-tests.xml").getroot()
    cases = list(xml.iter("testcase"))

    def status(case):
        if case.find("failure") is not None or case.find("error") is not None:
            return "FAIL"
        skipped = case.find("skipped")
        if skipped is not None:
            return "XFAIL" if skipped.attrib.get("type") == "pytest.xfail" else "SKIP"
        return "PASS"

    results = {c.attrib["name"].split("[")[0]: status(c) for c in cases}
    counts = {
        s: sum(status(c) == s for c in cases) for s in ("PASS", "FAIL", "SKIP", "XFAIL")
    }
    policy = asdict(operational_policy())
    mapping_path = OUT / "definition_mapping.json"
    mapping = load(mapping_path.relative_to(ROOT))
    assert set(policy["approvals"]) == {
        d["definition_id"] for d in mapping["definitions"]
    }
    mapping["baseline"] = {
        "head": git("rev-parse", "HEAD"),
        "clean_at_start": True,
        "verification": "主执行者在任何修改前实际核查git status/log；独立审阅者只静态审阅",
    }
    mapping["scope"] = (
        "33项冻结定义的静态逐项映射，附主执行者最终实际回归；局部断言不等于完整算法验收"
    )
    mapping["method"]["coordinator_runtime_tests_executed"] = True
    mapping["method"]["reviewer_runtime_tests_executed"] = False
    mapping["method"]["runtime_tests_executed"] = True
    mapping["method"]["git_used"] = True
    mapping["method"]["coordinator_bounded_network_tests_executed"] = True
    mapping["summary"]["executed_tests"] = len(cases)
    mapping["summary"]["execution_counts"] = counts
    mapping["baseline_reviewed_file_sha256"] = mapping.get(
        "baseline_reviewed_file_sha256", mapping["reviewed_file_sha256"]
    )
    mapping["reviewed_file_sha256"] = {
        p: sha(ROOT / p) for p in mapping["reviewed_file_sha256"]
    }
    missing = []
    executed_names = set()
    for definition in mapping["definitions"]:
        for evidence in definition["implementation_evidence"]:
            path = ROOT / evidence["file"]
            function = evidence["function"].split(".")[-1]
            nodes = [
                n
                for n in ast.walk(ast.parse(path.read_text(encoding="utf8")))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == function
            ]
            if not nodes:
                missing.append(
                    {
                        "definition": definition["definition_id"],
                        "implementation": evidence,
                    }
                )
            else:
                evidence["current_line"] = nodes[0].lineno
        for evidence in definition["test_evidence"]:
            path = ROOT / evidence["test_file"]
            name = evidence["test_case"].split("::")[-1].split("[")[0]
            nodes = [
                n
                for n in ast.walk(ast.parse(path.read_text(encoding="utf8")))
                if isinstance(n, ast.FunctionDef) and n.name == name
            ]
            if not nodes or name not in results:
                missing.append(
                    {"definition": definition["definition_id"], "test": name}
                )
            else:
                evidence["current_line"] = nodes[0].lineno
                evidence["execution"] = results[name]
                executed_names.add(name)
    if missing:
        raise ValueError(f"unresolved mapping references: {missing}")
    mapping["summary"]["unique_mapped_test_functions_executed"] = len(executed_names)
    write(mapping_path, mapping)
    replay = load("docs/phase6_5/manifests/replay_evidence.json")
    assert (
        replay["identity"]["implementation_sha256"] == implementation_hashes()
    ), "Replay code changed: rerun replay"
    assert replay["economics_unchanged"] and replay["json_roundtrip_validation"]
    dependencies = {}
    for package in (
        "PySide6",
        "pandas",
        "numpy",
        "SQLAlchemy",
        "akshare",
        "plotly",
        "openpyxl",
        "pytest",
        "pytest-qt",
        "pyinstaller",
    ):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = "not installed"
    privacy = load("cache/phase65/privacy_scan.json")
    sources = load("cache/research-sources/manifest.json")
    files = {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "docs/phase6_5").rglob("*")
        if p.is_file()
    }
    files.update(git("diff", "--name-only").splitlines())
    files.update(git("ls-files", "--others", "--exclude-standard").splitlines())
    files.update(
        (
            "pyproject.toml",
            "requirements.txt",
            "docs/strategy/operational_definitions.md",
            "src/spear_shield/strategy/operational.py",
        )
    )
    excluded = {
        "docs/phase6_5/manifests/phase6_5_manifest.json",
        "docs/phase6_5/manifests/SHA256.txt",
    }
    hashes = {
        name: sha(ROOT / name)
        for name in sorted(files - excluded)
        if (ROOT / name).is_file()
    }
    baseline_policy_sha = hashlib.sha256(
        subprocess.check_output(
            ["git", "show", "HEAD:src/spear_shield/strategy/operational.py"], cwd=ROOT
        )
    ).hexdigest()
    assert baseline_policy_sha == sha(ROOT / "src/spear_shield/strategy/operational.py")
    manifest = {
        "project": "Spear & Shield",
        "phase": "6.5",
        "audit_date": "2026-11-03",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_status": "PARTIAL",
        "strategy_definition_version": DEFINITION_VERSION,
        "software_version": version("spear-shield"),
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "audit_commit": None,
        "pushed": False,
        "working_tree_clean": False,
        "commit_blocker": "最终执行文档第十二节：原始PDF与全文已在历史，版权许可不确定，停止commit/push待负责人确认",
        "initial_git_status": "clean; no user changes or untracked files",
        "recent_commits": git("log", "-10", "--format=%H %s").splitlines(),
        "repository_visibility_checked_read_only": "private",
        "execution_document": {
            "name": "Spear & Shield（矛与盾）Phase 6.5：最.docx",
            "sha256": "318d48662c214ee20e4b7ce9aca3b1174333c0e05c877eb41b12b7c7dcd404bf",
            "paragraphs": 335,
        },
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "dependencies": dependencies,
        "strategy_configuration": policy,
        "strategy_configuration_sha256": digest(policy),
        "operational_policy_file_unchanged_vs_HEAD": True,
        "implementation_sha256": implementation_hashes(),
        "definition_audit_summary": mapping["summary"],
        "data_sources": replay["identity"]["source_versions"],
        "source_collection_manifest_sha256": sha(
            ROOT / "cache/research-sources/manifest.json"
        ),
        "local_source_artifact_root": "cache/research-sources",
        "source_collection_runs": [
            {
                "id": r["id"],
                "started_at": r["started_at"],
                "tasks": [
                    {
                        k: t.get(k)
                        for k in (
                            "key",
                            "status",
                            "retrieved_at",
                            "source_url",
                            "artifacts",
                        )
                    }
                    for t in r["tasks"]
                ],
            }
            for r in sources["runs"]
        ],
        "test_results": {
            "collected": len(cases),
            **counts,
            "warnings": 9,
            "startup_smoke": {
                "command": "python -m spear_shield --data-dir cache/phase65/startup-smoke --smoke-test",
                "exit_code": 0,
                "observed": "V0.1.0 window and Qt event loop; normal exit",
            },
            "duration_seconds": float(xml.find("testsuite").attrib["time"]),
            "command": "python -m pytest --ignore=tests/integration/test_akshare_provider.py -q --basetemp=cache/phase65/pytest-final --junitxml=cache/phase65/final-tests.xml",
            "xml_sha256": sha(ROOT / "cache/phase65/final-tests.xml"),
            "network": load("cache/phase65/network/summary.json"),
        },
        "privacy": {
            k: v for k, v in privacy.items() if k != "absolute_path_occurrences"
        },
        "privacy_scope": "all reachable Git text objects plus current tracked/unignored new text; 13 tracked images visually reviewed; pattern scan not proof of absence",
        "replay_evidence_sha256": hashes[
            "docs/phase6_5/manifests/replay_evidence.json"
        ],
        "blockers": [
            "B02 stale mixed pending target can rebuy after ATR stop; strict xfail",
            "21 definitions partial; 2 without targeted tests",
            "IV, PE/PEG, equity-bond definition/data and historical point-in-time gaps",
            "third-party source copyright permission/history handling pending",
        ],
        "hashes": hashes,
        "hash_scope": "actual file bytes; manifest excludes itself and sibling SHA256.txt to avoid recursion",
    }
    write(OUT / "phase6_5_manifest.json", manifest)
    (OUT / "SHA256.txt").write_text(
        f"{sha(OUT / 'phase6_5_manifest.json')}  phase6_5_manifest.json\n",
        encoding="ascii",
    )
    print(
        json.dumps(
            {
                "status": manifest["audit_status"],
                "tests": counts,
                "mapped_functions_executed": len(executed_names),
                "hashed_files": len(hashes),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
