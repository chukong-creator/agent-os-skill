#!/usr/bin/env python3
"""Acceptance tests for Agent OS v0.6 project intelligence."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from test_agent_os_v03 import AGENT_OS, AGENT_SHIFT, call, commit, write
from test_agent_os_v04 import initialize


def configure_intelligence(root: Path) -> None:
    write(root / "docs" / "ARCHITECTURE.md", "# Architecture\n\nKeep the fixture small.\n")
    write(root / "docs" / "RULES.md", "# Rules\n\nRegression behavior is durable.\n")
    config_path = root / ".agent-os" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["project_intelligence"] = {
        "architecture_sources": [
            {"path": "docs/ARCHITECTURE.md", "role": "module boundaries", "last_validated": "2026-08-31"},
        ],
        "knowledge_sources": [
            {"path": "docs/RULES.md", "role": "non-derivable project rules", "last_validated": "2026-08-31"},
        ],
        "verify_entrypoints": [
            {"work_unit": "default", "command": "grep -q success app.txt"},
        ],
        "failure_corpus_path": ".agent-os/knowledge/failure-corpus.json",
        "freshness_days": 180,
    }
    write(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    commit(root, "governance: declare project intelligence sources")


def test_knowledge_doctor(parent: Path) -> None:
    root = parent / "knowledge-doctor"
    initialize(root, "knowledge-doctor")
    configure_intelligence(root)
    report = json.loads(call([AGENT_OS, "knowledge-doctor", str(root), "--strict", "--json"], root))
    assert report["status"] == "PASS"
    assert report["mutated"] is False
    assert len(report["sources"]) == 2
    assert report["failure_corpus"]["entries"] == 0

    config_path = root / ".agent-os" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["project_intelligence"]["knowledge_sources"][0]["last_validated"] = "2020-01-01"
    write(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    stale = json.loads(call([AGENT_OS, "knowledge-doctor", str(root), "--json"], root))
    assert stale["status"] == "WARN"
    assert "STALE_KNOWLEDGE_SOURCE" in {item["code"] for item in stale["findings"]}
    call([AGENT_OS, "knowledge-doctor", str(root), "--strict"], root, expected=1)


def test_maintenance_delta_gate(parent: Path) -> None:
    root = parent / "maintenance"
    initialize(root, "maintenance")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-incomplete", "--work-unit", "default",
        "--work-type", "maintenance", "--goal", "Add a dependency honestly",
        "--expected-gain", "Dependency cost is explicit",
        "--maintenance-delta", "dependency::Add a parser library",
    ], root)
    invalid = call([AGENT_OS, "package-ready", str(root), "--id", "wp-incomplete"], root, expected=2)
    assert "maintenance.owner is required" in invalid
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-complete", "--work-unit", "default",
        "--work-type", "maintenance", "--goal", "Add a dependency with an exit path",
        "--expected-gain", "Dependency cost and removal path are explicit",
        "--maintenance-delta", "dependency::Add a parser library",
        "--maintenance-owner", "default work unit",
        "--maintenance-rationale", "The existing parser cannot preserve the required format",
        "--maintenance-removal", "Remove when the standard library supports the format",
        "--maintenance-rollback", "Revert the dependency and restore the previous parser",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-complete"], root)
    contract = json.loads((root / ".agent-os/work-packages/wp-complete.json").read_text(encoding="utf-8"))
    assert contract["maintenance"]["deltas"][0]["category"] == "dependency"


def test_bugfix_requires_project_learning(parent: Path) -> None:
    root = parent / "bugfix"
    initialize(root, "bugfix")
    shift_path = root / ".agent-shift" / "project.json"
    shift = json.loads(shift_path.read_text(encoding="utf-8"))
    unit = shift["work_units"][0]
    unit["implementation_paths"] = ["app.txt", "tests"]
    unit["verify_commands"] = ["grep -q success app.txt && grep -q regression tests/regression.txt"]
    write(shift_path, json.dumps(shift, ensure_ascii=False, indent=2) + "\n")
    commit(root, "governance: add regression-test path")
    call([AGENT_SHIFT, "baseline", str(root), "--work-unit", "default"], root)

    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-bug", "--work-unit", "default",
        "--work-type", "bugfix", "--bug-reproduction", "app.txt lacks the success marker",
        "--knowledge-disposition", "test", "--goal", "Fix and remember the missing success marker",
        "--expected-gain", "The defect cannot recur silently", "--allow", "app.txt", "tests",
        "--verify", "grep -q success app.txt && grep -q regression tests/regression.txt",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-bug"], root)
    commit(root, "plan: approve bug knowledge fixture")
    started = json.loads(call([
        AGENT_OS, "run-start", str(root), "--package", "wp-bug", "--run", "run-bug", "--agent", "claude",
    ], root))
    worktree = Path(started["worktree"])
    write(worktree / "app.txt", "success\n")
    write(worktree / "tests" / "regression.txt", "regression\n")
    call(["git", "add", "app.txt", "tests/regression.txt"], worktree)
    call(["git", "commit", "-m", "fix: preserve the success marker"], worktree)
    call([AGENT_OS, "verify", str(root), "--run", "run-bug"], root)
    call([AGENT_OS, "verifier", str(root), "--run", "run-bug"], root)
    missing = call([
        AGENT_OS, "review", str(root), "--run", "run-bug", "--decision", "ACCEPTED",
        "--summary", "A bug fix without learning must not pass",
    ], root, expected=2)
    assert "requires a knowledge assessment" in missing
    call([
        AGENT_OS, "knowledge-record", str(root), "--run", "run-bug",
        "--reproduction", "The pre-fix file lacked the success marker",
        "--root-cause", "The success invariant had no regression oracle",
        "--regression-evidence", "tests/regression.txt::The fixture preserves the failed case",
        "--sibling-risk-search", "Searched the default work unit; no sibling marker paths exist",
        "--disposition", "test", "--reason", "The behavior is executable and local",
    ], root)
    call([
        AGENT_OS, "review", str(root), "--run", "run-bug", "--decision", "ACCEPTED",
        "--summary", "Exact-commit evidence and the regression asset both pass",
    ], root)
    corpus = json.loads((root / ".agent-os/knowledge/failure-corpus.json").read_text(encoding="utf-8"))
    assert len(corpus["entries"]) == 1
    assert corpus["entries"][0]["disposition"] == "test"
    assert corpus["entries"][0]["branch_commit"] == call(["git", "-C", str(worktree), "rev-parse", "HEAD"], root)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-os-v06-") as temporary:
        parent = Path(temporary)
        test_knowledge_doctor(parent)
        test_maintenance_delta_gate(parent)
        test_bugfix_requires_project_learning(parent)
    print("Agent OS v0.6 project-intelligence tests passed: 3 scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
