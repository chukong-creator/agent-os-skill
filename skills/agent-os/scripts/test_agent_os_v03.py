#!/usr/bin/env python3
"""Disposable end-to-end acceptance test for Agent OS v0.3."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_OS = str(SCRIPT_DIR / "agent_os.py")
AGENT_SHIFT = str(SCRIPT_DIR.parents[1] / "agent-shift" / "scripts" / "agent_shift.py")
os.environ["AGENT_SHIFT_EXECUTABLE"] = AGENT_SHIFT


def call(command: list[str], cwd: Path, expected: int = 0, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != expected:
        raise AssertionError(f"expected {expected}, got {completed.returncode}: {' '.join(command)}\n{completed.stdout}")
    return completed.stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str) -> None:
    call(["git", "add", "-A"], repo)
    environment = os.environ.copy()
    environment["AGENT_SHIFT_ALLOW_MAIN_COMMIT"] = "1"
    completed = subprocess.run(
        ["git", "commit", "-m", message], cwd=repo, env=environment,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stdout)


def bootstrap(root: Path) -> None:
    root.mkdir(parents=True)
    call(["git", "init", "-b", "main"], root)
    call(["git", "config", "user.name", "Agent OS Test"], root)
    call(["git", "config", "user.email", "agent-os-test@example.invalid"], root)
    write(root / "AGENTS.md", "# Test rules\n")
    write(root / "app.txt", "base\n")
    write(root / ".gitignore", ".agent-shift/*\n!.agent-shift/project.json\n.agent-os/state.db*\n.agent-os/events.jsonl\n.agent-os/runs/\n.agent-os/runtime/\n")
    commit(root, "baseline")
    call([AGENT_SHIFT, "init", str(root), "--name", "Agent OS v0.3 Test"], root)
    shift_config = json.loads((root / ".agent-shift/project.json").read_text(encoding="utf-8"))
    unit = shift_config["work_units"][0]
    unit["implementation_paths"] = ["app.txt"]
    unit["director_owned_paths"] = ["AGENTS.md", "CLAUDE.md", ".agent-shift", ".agent-os", ".claude"]
    unit["deny_paths"] = ["AGENTS.md", "CLAUDE.md", ".agent-shift", ".agent-os", ".claude"]
    unit["verify_commands"] = ["grep -q success app.txt"]
    write(root / ".agent-shift/project.json", json.dumps(shift_config, ensure_ascii=False, indent=2) + "\n")
    call([AGENT_SHIFT, "protect-main", str(root), "--work-unit", "default"], root)
    commit(root, "governance: agent shift")
    call([AGENT_SHIFT, "baseline", str(root), "--work-unit", "default"], root)


def routing_fixture(parent: Path) -> Path:
    database = parent / "cc-switch-routing.db"
    db = sqlite3.connect(database)
    try:
        db.execute(
            """CREATE TABLE providers(
               id TEXT NOT NULL, app_type TEXT NOT NULL, name TEXT NOT NULL,
               settings_config TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0,
               sort_index INTEGER, PRIMARY KEY(id, app_type))"""
        )
        db.execute("INSERT INTO providers VALUES(?,?,?,?,?,?)", (
            "builder", "claude", "Test Builder", json.dumps({"env": {
                "ANTHROPIC_AUTH_TOKEN": "must-not-appear-builder",
                "ANTHROPIC_BASE_URL": "https://builder.example/anthropic",
                "ANTHROPIC_MODEL": "builder-model",
            }}), 1, 1,
        ))
        db.execute("INSERT INTO providers VALUES(?,?,?,?,?,?)", (
            "reviewer", "claude", "Test Reviewer", json.dumps({"env": {
                "ANTHROPIC_AUTH_TOKEN": "must-not-appear-reviewer",
                "ANTHROPIC_BASE_URL": "https://reviewer.example/anthropic",
                "ANTHROPIC_MODEL": "reviewer-model",
            }}), 0, 2,
        ))
        db.commit()
    finally:
        db.close()
    config = parent / "model-routing.json"
    write(config, json.dumps({
        "schema_version": 1, "cc_switch_database": str(database), "default_profile": "builder",
        "profiles": {
            "builder": {"mode": "builder", "provider": "Test Builder", "model": "builder-model", "effort": "medium"},
            "fallback": {"mode": "builder", "provider": "Test Reviewer", "model": "fallback-model"},
            "reviewer": {"mode": "reviewer", "provider": "Test Reviewer", "model": "reviewer-model", "effort": "high"},
        },
        "fallback_chains": {"builder": ["builder", "fallback"], "reviewer": ["reviewer"]},
    }, indent=2) + "\n")
    return config


def test_migration(parent: Path) -> None:
    root = parent / "migration"
    bootstrap(root)
    os_root = root / ".agent-os"
    (os_root / "policy").mkdir(parents=True)
    (os_root / "runtime").mkdir()
    write(os_root / "project.json", json.dumps({
        "agent_os_version": "0.2", "id": "legacy", "name": "Legacy", "mission": "Test migration",
        "control_root": str(root), "work_units_source": ".agent-shift/project.json",
        "protected_paths": [".agent-os"], "high_risk_operations": ["push"], "lock_ttl_seconds": 7200,
    }, indent=2) + "\n")
    write(os_root / "policy/evidence-review.json", json.dumps({"agent_os_version": "0.2", "acceptance_requires": []}, indent=2) + "\n")
    with sqlite3.connect(os_root / "state.db") as db:
        db.executescript("""
        CREATE TABLE work_packages(id TEXT PRIMARY KEY, work_unit TEXT NOT NULL, status TEXT NOT NULL, owner TEXT NOT NULL, reviewer TEXT NOT NULL, contract_path TEXT NOT NULL, current_run TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE runs(id TEXT PRIMARY KEY, package_id TEXT NOT NULL, status TEXT NOT NULL, owner TEXT NOT NULL, worktree TEXT NOT NULL, branch TEXT NOT NULL, baseline_commit TEXT NOT NULL, branch_commit TEXT, evidence_status TEXT, started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, ended_at TEXT, FOREIGN KEY(package_id) REFERENCES work_packages(id));
        CREATE TABLE locks(work_unit TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner TEXT NOT NULL, worktree TEXT NOT NULL, acquired_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(id));
        CREATE TABLE reviews(id TEXT PRIMARY KEY, package_id TEXT NOT NULL, run_id TEXT NOT NULL, decision TEXT NOT NULL, branch_commit TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
    output = json.loads(call([AGENT_OS, "upgrade", str(root)], root))
    assert output["from"] == "0.2" and output["to"] == "0.3" and output["database_backup"]
    with sqlite3.connect(os_root / "state.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
        assert {"merge_commit", "rollback_commit", "maturity_status"} <= columns
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    again = json.loads(call([AGENT_OS, "upgrade", str(root)], root))
    assert again["idempotent"] is True and again["database_backup"] is None


def test_delivery_and_rollback(parent: Path) -> None:
    root = parent / "delivery"
    bootstrap(root)
    route_config = routing_fixture(parent)
    call([AGENT_OS, "init", str(root), "--id", "test", "--name", "Test", "--mission", "Prove trustworthy delivery"], root)
    commit(root, "governance: agent os v0.3")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-001", "--work-unit", "default",
        "--goal", "Ship a verified change", "--objective", "Change app.txt from base to success",
        "--mission-alignment", "Proves the complete governed loop", "--priority", "P1",
        "--expected-gain", "A reproducible recovery contract", "--frontline-signal", "Disposable Git evidence",
        "--first-principles", "Trust requires independently checkable state",
        "--selected-approach", "Use one isolated Agent worktree",
        "--rationale", "It separates builder writes from director acceptance",
        "--alternative", "Shared main worktree::It cannot prove single-writer ownership",
        "--tradeoff", "More Git ceremony for stronger recovery",
        "--allow", "app.txt", "--verify", "grep -q success app.txt",
        "--rollback-check", "grep -q base app.txt", "--verified", "Verification command passes",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-001"], root)
    commit(root, "plan: approve wp-001")
    started = json.loads(call([AGENT_OS, "run-start", str(root), "--package", "wp-001", "--run", "run-001", "--agent", "claude"], root))
    worktree = Path(started["worktree"])
    launch = call([AGENT_OS, "claude-start", str(root), "--run", "run-001", "--routing-config", str(route_config), "--dry-run"], root)
    launch_metadata = json.loads(launch)
    assert launch_metadata["result"] == "DRY_RUN" and launch_metadata["profile"] == "builder" and launch_metadata["model"] == "builder-model"
    assert "must-not-appear" not in launch
    for filename in ("decision-trace.json", "permission-manifest.json", "rollback-plan.json"):
        assert (root / ".agent-os/runs/run-001" / filename).is_file()

    write(worktree / "app.txt", "broken\n")
    call(["git", "add", "app.txt"], worktree)
    call(["git", "commit", "-m", "test: broken first attempt"], worktree)
    call([AGENT_OS, "verify", str(root), "--run", "run-001"], root, expected=1)
    failures = json.loads((root / ".agent-os/runs/run-001/failures.json").read_text(encoding="utf-8"))["failures"]
    assert failures[0]["category"] == "verification" and failures[0]["status"] == "OPEN"
    call([AGENT_OS, "maturity-report", str(root), "--run", "run-001"], root, expected=1)

    write(worktree / "app.txt", "success\n")
    call(["git", "add", "app.txt"], worktree)
    call(["git", "commit", "-m", "fix: satisfy contract"], worktree)
    call([AGENT_OS, "failure-resolve", str(root), "--run", "run-001", "--id", failures[0]["id"], "--resolution", "Replaced the invalid output and committed the verified behavior"], root)
    call([AGENT_OS, "verify", str(root), "--run", "run-001"], root)
    call([AGENT_OS, "verifier", str(root), "--run", "run-001", "--actor", "codex-subagent"], root)
    call([AGENT_OS, "learn", str(root), "--run", "run-001", "--outcome", "proposal", "--observation", "The first attempt bypassed the expected content signal", "--reason", "A pre-commit contract check can shorten the next loop", "--hypothesis", "Earlier feedback prevents failed verification rounds", "--proposed-change", "Expose a lightweight builder preflight command", "--risk", "L1", "--expected-effect", "Fewer verification retries", "--metric", "verification retry count", "--validation-window", "next 3 runs"], root)
    report = json.loads(call([AGENT_OS, "maturity-report", str(root), "--run", "run-001"], root))
    assert report["result"] == "PASS" and report["answers"]["failure_location"]["unresolved_count"] == 0
    call([AGENT_OS, "review", str(root), "--run", "run-001", "--decision", "ACCEPTED", "--summary", "Five-question maturity and shipped behavior both pass"], root)
    merged = json.loads(call([AGENT_OS, "merge", str(root), "--run", "run-001"], root))
    assert (root / "app.txt").read_text(encoding="utf-8") == "success\n"
    plan = json.loads(call([AGENT_OS, "rollback", str(root), "--run", "run-001", "--reason", "Exercise the reversible path"], root))
    assert plan["mutated"] is False
    receipt = json.loads(call([AGENT_OS, "rollback", str(root), "--run", "run-001", "--reason", "Exercise the reversible path", "--execute"], root))
    assert receipt["result"] == "PASS" and receipt["merge_commit"] == merged["merge_commit"]
    assert (root / "app.txt").read_text(encoding="utf-8") == "base\n"
    assert (root / ".agent-os/reviews/run-001-rollback.json").is_file()
    state = json.loads((root / ".agent-shift/state.json").read_text(encoding="utf-8"))
    assert state["status"] == "ROLLED_BACK" and state["rollback_commit"] == receipt["rollback_commit"]

    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-rework", "--work-unit", "default",
        "--goal", "Exercise explicit review rework", "--objective", "Move an accepted Run through Claude rework",
        "--mission-alignment", "Proves role clarity after Codex findings", "--priority", "P1",
        "--expected-gain", "A tested Review-to-Builder return path", "--selected-approach", "Reuse one Agent worktree",
        "--rationale", "Normal rework remains with the implementation owner", "--alternative", "Codex edits directly::It blurs director and builder roles",
        "--tradeoff", "One additional review round", "--allow", "app.txt",
        "--verify", "grep -q success app.txt", "--rollback-check", "grep -q base app.txt",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-rework"], root)
    commit(root, "plan: approve explicit rework fixture")
    rework_started = json.loads(call([AGENT_OS, "run-start", str(root), "--package", "wp-rework", "--run", "run-rework", "--agent", "claude"], root))
    rework_tree = Path(rework_started["worktree"])
    write(rework_tree / "app.txt", "success\n")
    call(["git", "add", "app.txt"], rework_tree)
    call(["git", "commit", "-m", "feat: first review candidate"], rework_tree)
    call([AGENT_OS, "verify", str(root), "--run", "run-rework"], root)
    review_launch = call([AGENT_OS, "claude-start", str(root), "--run", "run-rework", "--routing-config", str(route_config), "--dry-run"], root)
    review_metadata = json.loads(review_launch)
    assert review_metadata["profile"] == "reviewer" and review_metadata["mode"] == "reviewer" and review_metadata["model"] == "reviewer-model"
    assert "must-not-appear" not in review_launch
    call([AGENT_OS, "verifier", str(root), "--run", "run-rework"], root)
    call([AGENT_OS, "review", str(root), "--run", "run-rework", "--decision", "CHANGES_REQUESTED", "--summary", "The result needs a visible improved marker", "--required-change", "Add the improved marker while preserving success"], root)
    review_failures = json.loads((root / ".agent-os/runs/run-rework/failures.json").read_text(encoding="utf-8"))["failures"]
    assert review_failures[0]["stage"] == "CODEX_REVIEWING" and review_failures[0]["status"] == "OPEN"
    call([AGENT_OS, "rework-start", str(root), "--run", "run-rework"], root)
    write(rework_tree / "app.txt", "success improved\n")
    call(["git", "add", "app.txt"], rework_tree)
    call(["git", "commit", "-m", "fix: complete Codex rework"], rework_tree)
    call([AGENT_OS, "failure-resolve", str(root), "--run", "run-rework", "--id", review_failures[0]["id"], "--resolution", "Claude added the requested marker on the same Agent branch"], root)
    call([AGENT_OS, "verify", str(root), "--run", "run-rework"], root)
    call([AGENT_OS, "verifier", str(root), "--run", "run-rework"], root)
    call([AGENT_OS, "learn", str(root), "--run", "run-rework", "--outcome", "no-change", "--observation", "The standard review rework path behaved as designed", "--reason", "No new repeatable governance defect was observed"], root)
    rework_report = json.loads(call([AGENT_OS, "maturity-report", str(root), "--run", "run-rework"], root))
    assert rework_report["result"] == "PASS"
    call([AGENT_OS, "review", str(root), "--run", "run-rework", "--decision", "ACCEPTED", "--summary", "Claude completed the required rework and all gates pass"], root)
    call([AGENT_OS, "merge", str(root), "--run", "run-rework"], root)
    assert (root / "app.txt").read_text(encoding="utf-8") == "success improved\n"
    call([AGENT_OS, "doctor", str(root), "--strict"], root)
    assert call(["git", "status", "--porcelain"], root) == ""


def test_external_rollback_guard(parent: Path) -> None:
    root = parent / "external-guard"
    bootstrap(root)
    call([AGENT_OS, "init", str(root), "--id", "external", "--name", "External", "--mission", "Protect external state"], root)
    commit(root, "governance: agent os v0.3")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-external", "--work-unit", "default",
        "--goal", "Guard rollback authority", "--objective", "Prove external effects require acknowledgement",
        "--mission-alignment", "Prevents false recovery claims", "--priority", "P1",
        "--expected-gain", "Safer operational rollback", "--selected-approach", "Declare the side effect before execution",
        "--rationale", "Git cannot reverse external systems", "--alternative", "Assume Git is enough::It creates a false recovery claim",
        "--external-side-effect", "test deployment marker", "--allow", "app.txt",
        "--verify", "grep -q success app.txt", "--rollback-check", "grep -q base app.txt",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-external"], root)
    commit(root, "plan: approve external guard")
    started = json.loads(call([AGENT_OS, "run-start", str(root), "--package", "wp-external", "--run", "run-external", "--agent", "claude"], root))
    worktree = Path(started["worktree"])
    write(worktree / "app.txt", "success\n")
    call(["git", "add", "app.txt"], worktree)
    call(["git", "commit", "-m", "feat: external guard fixture"], worktree)
    call([AGENT_OS, "verify", str(root), "--run", "run-external"], root)
    call([AGENT_OS, "verifier", str(root), "--run", "run-external"], root)
    call([AGENT_OS, "learn", str(root), "--run", "run-external", "--outcome", "no-change", "--observation", "The declared guard is sufficient for this fixture", "--reason", "No repeatable process defect was observed"], root)
    call([AGENT_OS, "review", str(root), "--run", "run-external", "--decision", "ACCEPTED", "--summary", "External effect declaration is explicit"], root)
    call([AGENT_OS, "merge", str(root), "--run", "run-external"], root)
    call([AGENT_OS, "rollback", str(root), "--run", "run-external", "--reason", "Guard test", "--execute"], root, expected=2)
    assert (root / "app.txt").read_text(encoding="utf-8") == "success\n"
    receipt = json.loads(call([AGENT_OS, "rollback", str(root), "--run", "run-external", "--reason", "Guard test with separate external recovery", "--execute", "--ack-external"], root))
    assert receipt["external_recovery_status"] == "NOT_VERIFIED"
    state = json.loads((root / ".agent-shift/state.json").read_text(encoding="utf-8"))
    assert state["status"] == "CODE_REVERTED_EXTERNAL_PENDING"
    assert (root / "app.txt").read_text(encoding="utf-8") == "base\n"


def test_runtime_provider_fallback(parent: Path) -> None:
    root = parent / "runtime-fallback"
    bootstrap(root)
    fixture_root = parent / "runtime-routing"
    fixture_root.mkdir()
    route_config = routing_fixture(fixture_root)
    call([AGENT_OS, "init", str(root), "--id", "runtime", "--name", "Runtime", "--mission", "Recover from provider exhaustion"], root)
    commit(root, "governance: runtime fallback")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-runtime", "--work-unit", "default",
        "--goal", "Recover from exhausted provider", "--objective", "Start the next authorized Builder profile once",
        "--mission-alignment", "Prevents unattended Runs from stalling", "--priority", "P1",
        "--expected-gain", "Finite automatic recovery", "--selected-approach", "Use a role-specific fallback chain",
        "--rationale", "The next provider preserves the same Git worktree and contract",
        "--alternative", "Global provider switching::It affects unrelated Claude sessions",
        "--allow", "app.txt", "--verify", "grep -q base app.txt", "--rollback-check", "grep -q base app.txt",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-runtime"], root)
    commit(root, "plan: approve runtime fallback fixture")
    call([AGENT_OS, "run-start", str(root), "--package", "wp-runtime", "--run", "run-runtime", "--agent", "claude"], root)

    fake_bin = parent / "fake-claude-bin"
    fake_bin.mkdir()
    launches = parent / "fake-claude-launches.txt"
    fake_claude = fake_bin / "claude"
    write(fake_claude, f"""#!/bin/sh
if [ "$1" = "agents" ]; then
  if grep -q 'run-runtime-fallback' '{launches}' 2>/dev/null; then
    printf '%s\n' '[{{"id":"fallback-job","name":"agent-os-run-runtime-fallback","state":"done","startedAt":2}}]'
  else
    printf '%s\n' '[{{"id":"builder-job","name":"agent-os-run-runtime-builder","state":"failed","detail":"HTTP 429 quota exhausted","startedAt":1}}]'
  fi
  exit 0
fi
name=""
previous=""
for value in "$@"; do
  if [ "$previous" = "--name" ]; then name="$value"; break; fi
  previous="$value"
done
printf '%s\n' "$name" >> '{launches}'
if [ "$name" = "agent-os-run-runtime-builder" ]; then
  printf '%s\n' 'HTTP 429 rate_limit_error: quota exhausted'
  exit 1
fi
printf '%s\n' 'fake-background-started'
""")
    fake_claude.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment.get('PATH', '')}"
    call([
        AGENT_OS, "claude-start", str(root), "--run", "run-runtime", "--profile", "builder",
        "--routing-config", str(route_config),
    ], root, env=environment)
    state_path = root / ".agent-os/runs/run-runtime/routing-state.json"
    deadline = time.monotonic() + 10
    routing_state = {}
    while time.monotonic() < deadline:
        routing_state = json.loads(state_path.read_text(encoding="utf-8"))
        if routing_state.get("status") in {"COMPLETED", "RUNTIME_FAILED"}:
            break
        time.sleep(0.1)
    launched = launches.read_text(encoding="utf-8").splitlines()
    assert launched == ["agent-os-run-runtime-builder", "agent-os-run-runtime-fallback"]
    assert routing_state["status"] == "COMPLETED" and routing_state["active_profile"] == "fallback"
    assert [item["profile"] for item in routing_state["attempts"]] == ["builder", "fallback"]
    events = (root / ".agent-os/runs/run-runtime/events.jsonl").read_text(encoding="utf-8")
    assert '"event": "routing_fallback"' in events and "must-not-appear" not in events


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="agent-os-v03-", dir="/tmp"))
    try:
        test_migration(parent)
        test_delivery_and_rollback(parent)
        test_external_rollback_guard(parent)
        test_runtime_provider_fallback(parent)
        print(json.dumps({"result": "PASS", "workspace": str(parent), "scenarios": ["migration", "routing-dry-run", "unresolved-failure-block", "failure-resolution", "explicit-review-rework", "maturity-drift-check", "merge-gate-refresh", "rollback", "external-side-effect-guard", "external-recovery-pending", "runtime-provider-fallback"]}, indent=2))
        return 0
    except Exception:
        print(json.dumps({"result": "FAIL", "workspace": str(parent)}, indent=2))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
