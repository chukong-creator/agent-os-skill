#!/usr/bin/env python3
"""Disposable acceptance tests for Agent OS v0.4 proportional governance."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from test_agent_os_v03 import AGENT_OS, AGENT_SHIFT, bootstrap, call, commit, write


def initialize(root: Path, project_id: str) -> None:
    bootstrap(root)
    call([
        AGENT_OS, "init", str(root), "--id", project_id,
        "--name", f"Agent OS v0.4 {project_id}", "--mission", "Prove proportional governance",
    ], root)
    commit(root, "governance: initialize Agent OS v0.4")


def deliver_candidate(root: Path, package_id: str, run_id: str) -> Path:
    call([AGENT_OS, "package-ready", str(root), "--id", package_id], root)
    commit(root, f"plan: approve {package_id}")
    started = json.loads(call([
        AGENT_OS, "run-start", str(root), "--package", package_id,
        "--run", run_id, "--agent", "claude",
    ], root))
    worktree = Path(started["worktree"])
    write(worktree / "app.txt", "success\n")
    call(["git", "add", "app.txt"], worktree)
    call(["git", "commit", "-m", f"feat: deliver {package_id}"], worktree)
    call([AGENT_OS, "verify", str(root), "--run", run_id], root)
    call([AGENT_OS, "verifier", str(root), "--run", run_id], root)
    return worktree


def l1_outcome_args() -> list[str]:
    return [
        "--outcome-metric", "verified user-visible result",
        "--outcome-baseline", "result absent",
        "--outcome-target", "result present and accepted",
        "--outcome-validation-window", "within one delivery cycle",
        "--outcome-evidence-source", "hashed acceptance fixture",
    ]


def test_l0_lightweight(parent: Path) -> None:
    root = parent / "l0"
    initialize(root, "l0")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-l0", "--work-unit", "default",
        "--goal", "Make a small verified change",
        "--expected-gain", "The repository contains the verified success marker",
        "--allow", "app.txt", "--verify", "grep -q success app.txt",
        "--rollback-check", "grep -q base app.txt",
    ], root)
    deliver_candidate(root, "wp-l0", "run-l0")
    call([
        AGENT_OS, "review", str(root), "--run", "run-l0", "--decision", "ACCEPTED",
        "--summary", "L0 exact-commit evidence passes without mandatory maturity ceremony",
    ], root)
    merged = json.loads(call([AGENT_OS, "merge", str(root), "--run", "run-l0"], root))
    assert merged["run_status"] == "MERGED" and merged["outcome_status"] == "NOT_REQUIRED"
    economics = json.loads((root / ".agent-os/runs/run-l0/run-economics.json").read_text(encoding="utf-8"))
    assert economics["governance_level"] == "L0"
    assert economics["counts"]["review_rounds"] == 1
    assert economics["token_usage"]["input_tokens"] is None
    assert economics["token_usage"]["source"] == "unavailable-from-runtime"
    call([AGENT_OS, "doctor", str(root), "--strict"], root)


def test_post_acceptance_drift_gate(parent: Path) -> None:
    root = parent / "post-acceptance-drift"
    initialize(root, "post-acceptance-drift")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-drift", "--work-unit", "default",
        "--goal", "Detect tracked changes after acceptance",
        "--expected-gain", "Accepted Git state remains mechanically reconcilable",
        "--allow", "app.txt", "--verify", "grep -q success app.txt",
    ], root)
    deliver_candidate(root, "wp-drift", "run-drift")
    call([
        AGENT_OS, "review", str(root), "--run", "run-drift", "--decision", "ACCEPTED",
        "--summary", "The candidate passes exact-commit delivery checks",
    ], root)
    call([AGENT_OS, "merge", str(root), "--run", "run-drift"], root)
    call([AGENT_OS, "doctor", str(root), "--strict"], root)

    write(root / "local-observation.txt", "untracked local evidence\n")
    call([AGENT_OS, "doctor", str(root), "--strict"], root)
    call([AGENT_SHIFT, "baseline", str(root), "--work-unit", "default"], root)

    write(root / "app.txt", "uncommitted drift\n")
    drift = call([AGENT_OS, "doctor", str(root), "--strict"], root, expected=1)
    assert "post-acceptance tracked drift: app.txt" in drift

    commit(root, "fix: reconcile accepted product state")
    call([AGENT_OS, "doctor", str(root), "--strict"], root)

    call(["git", "switch", "-c", "codex/future-work"], root)
    branch_drift = call([AGENT_OS, "doctor", str(root), "--strict"], root, expected=1)
    assert "post-acceptance canonical worktree branch is codex/future-work; expected main" in branch_drift
    call(["git", "switch", "main"], root)


def test_l1_live_delivery_binds_final_artifact_and_endpoint(parent: Path) -> None:
    root = parent / "l1-live"
    initialize(root, "l1-live")
    endpoint = "https://example.invalid/demo"
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-live-no-rollback", "--work-unit", "default",
        "--governance-level", "L1", "--goal", "Reject a release without an explicit rollback check",
        "--objective", "Prove reversible release validation", "--mission-alignment", "Keep release recovery real",
        "--priority", "P1", "--expected-gain", "An incomplete release contract cannot start",
        "--selected-approach", "Exercise release validation", "--rationale", "A build command is not a release rollback",
        *l1_outcome_args(), "--allow", "app.txt", "--verify", "grep -q success app.txt",
        "--delivery-target", "live", "--artifact-path", "app.txt", "--live-endpoint", endpoint,
        "--acceptance-check", f"The final endpoint serves the expected artifact::endpoint={endpoint}; test \"$endpoint\" = \"{endpoint}\" && grep -q success app.txt",
        "--external-side-effect", "reversible static demo release",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-live-no-rollback"], root, expected=2)
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-live", "--work-unit", "default",
        "--governance-level", "L1", "--goal", "Accept only the final usable live release",
        "--objective", "Bind release acceptance to the exact artifact and endpoint",
        "--mission-alignment", "Prevent local-only evidence from claiming a live result",
        "--priority", "P1", "--expected-gain", "The declared endpoint passes its core release check",
        "--selected-approach", "Hash the final artifact and recheck the endpoint at acceptance",
        "--rationale", "Repackaging and deployment can invalidate local browser evidence",
        *l1_outcome_args(), "--allow", "app.txt", "--verify", "grep -q success app.txt",
        "--delivery-target", "live", "--artifact-path", "app.txt",
        "--live-endpoint", endpoint,
        "--acceptance-check", f"The final endpoint serves the expected artifact::endpoint={endpoint}; test \"$endpoint\" = \"{endpoint}\" && grep -q success app.txt",
        "--external-side-effect", "reversible static demo release",
        "--rollback-check", "grep -q base app.txt",
    ], root)
    worktree = deliver_candidate(root, "wp-live", "run-live")
    manifest_path = root / ".agent-os/runs/run-live/evidence/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["delivery"]["target"] == "live"
    assert manifest["delivery"]["live_endpoints"] == [endpoint]
    assert manifest["delivery"]["artifact_evidence"][0]["sha256"]
    assert manifest["delivery"]["acceptance_evidence"][0]["claim"] == "The final endpoint serves the expected artifact"
    write(worktree / "app.txt", "changed after verification\n")
    call([
        AGENT_OS, "review", str(root), "--run", "run-live", "--decision", "ACCEPTED",
        "--summary", "A changed release artifact must invalidate prior evidence",
    ], root, expected=2)
    write(worktree / "app.txt", "success\n")
    call([
        AGENT_OS, "review", str(root), "--run", "run-live", "--decision", "ACCEPTED",
        "--summary", "The final artifact and live endpoint are rechecked at acceptance",
    ], root)


def test_installable_delivery_requires_real_package_acceptance(parent: Path) -> None:
    root = parent / "installable"
    initialize(root, "installable")
    common = [
        AGENT_OS, "package-create", str(root), "--work-unit", "default",
        "--governance-level", "L1", "--goal", "Deliver an installable application",
        "--objective", "Accept the packaged runtime instead of source files",
        "--mission-alignment", "Keep packaged application delivery trustworthy",
        "--priority", "P1", "--expected-gain", "The final package installs and launches in its declared test runtime",
        "--selected-approach", "Hash and exercise the final installable artifact",
        "--rationale", "A successful source build does not prove the package can install or launch",
        *l1_outcome_args(), "--allow", "app.txt", "--verify", "grep -q success app.txt",
        "--delivery-target", "installable", "--artifact-path", "app.txt",
    ]
    call([*common, "--id", "wp-installable-missing-check"], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-installable-missing-check"], root, expected=2)
    call([
        *common, "--id", "wp-installable",
        "--acceptance-check", "The packaged app installs and launches in the simulator::grep -q success app.txt",
    ], root)
    deliver_candidate(root, "wp-installable", "run-installable")
    manifest = json.loads((root / ".agent-os/runs/run-installable/evidence/manifest.json").read_text(encoding="utf-8"))
    assert manifest["delivery"]["target"] == "installable"
    assert manifest["delivery"]["acceptance_evidence"][0]["result"] == "pass"
    call([
        AGENT_OS, "review", str(root), "--run", "run-installable", "--decision", "ACCEPTED",
        "--summary", "The exact installable artifact passed its declared install and launch check",
    ], root)


def test_l1_outcome_and_rollback(parent: Path) -> None:
    root = parent / "l1"
    initialize(root, "l1")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-invalid", "--work-unit", "default",
        "--governance-level", "L1", "--goal", "Reject a missing outcome contract",
        "--objective", "Prove L1 validation", "--mission-alignment", "Protect outcome truth",
        "--priority", "P1", "--expected-gain", "Invalid package cannot become READY",
        "--selected-approach", "Exercise package validation", "--rationale", "The gate must be deterministic",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-invalid"], root, expected=2)

    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-underclassified", "--work-unit", "default",
        "--governance-level", "L1", "--risk-factor", "production",
        "--goal", "Reject an underclassified production package", "--objective", "Prove L2 risk forcing",
        "--mission-alignment", "Keep risk classification deterministic", "--priority", "P0",
        "--expected-gain", "A production package cannot use L1",
        "--selected-approach", "Exercise the risk validator", "--rationale", "Production authority requires L2",
        *l1_outcome_args(),
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-underclassified"], root, expected=2)

    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-l1", "--work-unit", "default",
        "--governance-level", "L1", "--goal", "Deliver and validate an outcome",
        "--objective", "Exercise post-merge outcome states", "--mission-alignment", "Close the expected-gain loop",
        "--priority", "P1", "--expected-gain", "A delivered result with evidence-backed outcome",
        "--selected-approach", "Separate delivery acceptance from outcome validation",
        "--rationale", "The metric is observable only after merge", *l1_outcome_args(),
        "--allow", "app.txt", "--verify", "grep -q success app.txt",
        "--rollback-check", "grep -q base app.txt",
    ], root)
    deliver_candidate(root, "wp-l1", "run-l1")
    call([
        AGENT_OS, "review", str(root), "--run", "run-l1", "--decision", "ACCEPTED",
        "--summary", "L1 delivery gates pass and outcome remains pending",
    ], root)
    merged = json.loads(call([AGENT_OS, "merge", str(root), "--run", "run-l1"], root))
    assert merged["run_status"] == "OUTCOME_PENDING"
    evidence = parent / "l1-outcome-evidence.json"
    write(evidence, json.dumps({"observed": "result present and accepted"}) + "\n")
    inconclusive = json.loads(call([
        AGENT_OS, "outcome-check", str(root), "--run", "run-l1", "--result", "INCONCLUSIVE",
        "--observed-value", "result present but validation window incomplete", "--evidence-file", str(evidence),
        "--note", "The first observation is real but not yet sufficient",
    ], root))
    assert inconclusive["status"] == "OUTCOME_INCONCLUSIVE"
    outcome = json.loads(call([
        AGENT_OS, "outcome-check", str(root), "--run", "run-l1", "--result", "CONFIRMED",
        "--observed-value", "result present and accepted", "--evidence-file", str(evidence),
        "--note", "The target is supported by a hashed fixture",
    ], root))
    assert outcome["status"] == "OUTCOME_CONFIRMED"
    assert outcome["evidence"][0]["sha256"]
    receipt = json.loads(call([
        AGENT_OS, "rollback", str(root), "--run", "run-l1",
        "--reason", "Prove outcome metadata does not weaken exact-head rollback", "--execute",
    ], root))
    assert receipt["result"] == "PASS"


def test_intermediate_review_stays_run_local(parent: Path) -> None:
    root = parent / "run-local-review"
    initialize(root, "run-local-review")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-review", "--work-unit", "default",
        "--goal", "Keep unaccepted review churn out of main",
        "--expected-gain", "Only accepted product truth is committed",
        "--allow", "app.txt", "--verify", "grep -q success app.txt",
    ], root)
    deliver_candidate(root, "wp-review", "run-review")
    before = call(["git", "rev-parse", "HEAD"], root)
    call([
        AGENT_OS, "review", str(root), "--run", "run-review", "--decision", "CHANGES_REQUESTED",
        "--summary", "The candidate needs one bounded correction",
        "--required-change", "F-001: correct the candidate and rerun its check",
    ], root)
    assert call(["git", "rev-parse", "HEAD"], root) == before
    assert not list((root / ".agent-os/reviews").glob("run-review-r1.*"))
    assert (root / ".agent-os/runs/run-review/reviews/run-review-r1.json").is_file()


def test_l1_refuted_outcome(parent: Path) -> None:
    root = parent / "l1-refuted"
    initialize(root, "l1-refuted")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-refuted", "--work-unit", "default",
        "--governance-level", "L1", "--goal", "Record an honestly refuted outcome",
        "--objective", "Exercise the refuted terminal state", "--mission-alignment", "Keep gain claims falsifiable",
        "--priority", "P1", "--expected-gain", "The target is checked even when it fails",
        "--selected-approach", "Separate delivery from outcome", "--rationale", "A valid delivery can miss its target",
        *l1_outcome_args(), "--allow", "app.txt", "--verify", "grep -q success app.txt",
    ], root)
    deliver_candidate(root, "wp-refuted", "run-refuted")
    call([
        AGENT_OS, "review", str(root), "--run", "run-refuted", "--decision", "ACCEPTED",
        "--summary", "Delivery is accepted independently of the later gain",
    ], root)
    call([AGENT_OS, "merge", str(root), "--run", "run-refuted"], root)
    evidence = parent / "l1-refuted-evidence.json"
    write(evidence, json.dumps({"observed": "target not reached"}) + "\n")
    outcome = json.loads(call([
        AGENT_OS, "outcome-check", str(root), "--run", "run-refuted", "--result", "REFUTED",
        "--observed-value", "target not reached", "--evidence-file", str(evidence),
        "--note", "The frozen target was not achieved",
    ], root))
    assert outcome["status"] == "OUTCOME_REFUTED"


def test_l2_challenge_and_maturity(parent: Path) -> None:
    root = parent / "l2"
    initialize(root, "l2")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-l2", "--work-unit", "default",
        "--governance-level", "L2", "--risk-factor", "shared-contract",
        "--goal", "Deliver a challenged high-impact change", "--objective", "Exercise L2 gates",
        "--mission-alignment", "Prevent governance-perfect wrong decisions", "--priority", "P1",
        "--expected-gain", "A challenged decision with full maturity evidence",
        "--first-principles", "High-impact scope needs disconfirming review",
        "--selected-approach", "Require an independent Director Challenge",
        "--rationale", "The challenge occurs before package approval",
        "--alternative", "Codex self-review only::It leaves the Director as an unchecked judgment point",
        "--tradeoff", "Additional review cost for high-impact work", *l1_outcome_args(),
        "--allow", "app.txt", "--verify", "grep -q success app.txt",
        "--rollback-check", "grep -q base app.txt",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-l2"], root, expected=2)
    review_file = parent / "l2-independent-review.md"
    write(review_file, "# L2 challenge\n\nPASS: scope, disconfirming evidence, and rollback are coherent.\n")
    call([
        AGENT_OS, "director-challenge", str(root), "--package", "wp-l2",
        "--reviewer", "independent-test-reviewer", "--decision", "PASS",
        "--summary", "The Director decision survives a separate challenge",
        "--finding", "Residual product outcome remains post-merge", "--review-file", str(review_file),
    ], root)
    deliver_candidate(root, "wp-l2", "run-l2")
    call([
        AGENT_OS, "review", str(root), "--run", "run-l2", "--decision", "ACCEPTED",
        "--summary", "This must fail until L2 learning exists",
    ], root, expected=2)
    call([
        AGENT_OS, "learn", str(root), "--run", "run-l2", "--outcome", "no-change",
        "--observation", "The independent challenge and delivery gates behaved as designed",
        "--reason", "No repeatable governance defect was observed",
    ], root)
    report = json.loads(call([AGENT_OS, "maturity-report", str(root), "--run", "run-l2"], root))
    assert report["result"] == "PASS"
    call([
        AGENT_OS, "review", str(root), "--run", "run-l2", "--decision", "ACCEPTED",
        "--summary", "L2 challenge, learning, maturity, and delivery evidence pass",
    ], root)
    merged = json.loads(call([AGENT_OS, "merge", str(root), "--run", "run-l2"], root))
    assert merged["run_status"] == "OUTCOME_PENDING"


def test_v03_explicit_migration(parent: Path) -> None:
    root = parent / "migration-v03"
    initialize(root, "migration-v03")
    config_path = root / ".agent-os/project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["agent_os_version"] = "0.3"
    config["schema_revision"] = 3
    write(config_path, json.dumps(config, indent=2) + "\n")
    with sqlite3.connect(root / ".agent-os/state.db") as db:
        db.execute("PRAGMA user_version = 3")
    output = json.loads(call([AGENT_OS, "upgrade", str(root)], root))
    assert output["from"] == "0.3" and output["to"] == "0.6" and output["database_backup"]
    with sqlite3.connect(root / ".agent-os/state.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert "outcomes" in {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    again = json.loads(call([AGENT_OS, "upgrade", str(root)], root))
    assert again["idempotent"] is True and again["database_backup"] is None


def test_migration_refuses_active_lock(parent: Path) -> None:
    root = parent / "migration-active-lock"
    initialize(root, "migration-active-lock")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-active", "--work-unit", "default",
        "--governance-level", "L0", "--goal", "Keep one active writer",
        "--expected-gain", "Migration refuses an active Run", "--allow", "app.txt",
        "--verify", "grep -q success app.txt",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-active"], root)
    commit(root, "plan: approve active migration fixture")
    call([
        AGENT_OS, "run-start", str(root), "--package", "wp-active",
        "--run", "run-active", "--agent", "claude",
    ], root)
    config_path = root / ".agent-os/project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["agent_os_version"] = "0.3"
    config["schema_revision"] = 3
    write(config_path, json.dumps(config, indent=2) + "\n")
    with sqlite3.connect(root / ".agent-os/state.db") as db:
        db.execute("PRAGMA user_version = 3")
    call([AGENT_OS, "upgrade", str(root)], root, expected=2)
    assert not list((root / ".agent-os").glob("state.db.v0.3.*.bak"))


def test_runtime_recover_reuses_same_run(parent: Path) -> None:
    root = parent / "runtime-recover"
    initialize(root, "runtime-recover")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-recover", "--work-unit", "default",
        "--governance-level", "L0", "--goal", "Resume interrupted implementation",
        "--expected-gain", "The same Run and worktree continue without duplicated context",
        "--allow", "app.txt", "--verify", "grep -q success app.txt",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-recover"], root)
    commit(root, "plan: approve runtime recovery fixture")
    started = json.loads(call([
        AGENT_OS, "run-start", str(root), "--package", "wp-recover",
        "--run", "run-recover", "--agent", "claude",
    ], root))
    worktree = Path(started["worktree"])
    write(worktree / "app.txt", "partial work\n")
    call([
        AGENT_OS, "lock-release", str(root), "--work-unit", "default",
        "--reason", "simulate runtime interruption",
    ], root)
    recovered = json.loads(call([
        AGENT_OS, "runtime-recover", str(root), "--run", "run-recover",
        "--reason", "resume after supervisor repair",
    ], root))
    assert recovered["run"] == "run-recover"
    assert recovered["package"] == "wp-recover"
    assert recovered["worktree"] == str(worktree)
    assert recovered["branch"] == started["branch"]
    assert recovered["dirty"] is True
    with sqlite3.connect(root / ".agent-os/state.db") as db:
        assert db.execute("SELECT status FROM runs WHERE id='run-recover'").fetchone()[0] == "BUILDING"
        assert db.execute("SELECT status FROM work_packages WHERE id='wp-recover'").fetchone()[0] == "BUILDING"
        assert db.execute("SELECT run_id FROM locks WHERE work_unit='default'").fetchone()[0] == "run-recover"
    routing = json.loads((root / ".agent-os/runs/run-recover/routing-state.json").read_text(encoding="utf-8"))
    assert routing["status"] == "RUNTIME_RECOVERY_READY"


def test_orphaned_run_can_be_cancelled(parent: Path) -> None:
    root = parent / "run-cancel"
    initialize(root, "run-cancel")
    call([
        AGENT_OS, "package-create", str(root), "--id", "wp-cancel", "--work-unit", "default",
        "--governance-level", "L0", "--goal", "Close an obsolete interrupted Run",
        "--expected-gain", "Recovery no longer reports a deliberately abandoned Run",
        "--allow", "app.txt", "--verify", "grep -q success app.txt",
    ], root)
    call([AGENT_OS, "package-ready", str(root), "--id", "wp-cancel"], root)
    commit(root, "plan: approve cancellation fixture")
    started = json.loads(call([
        AGENT_OS, "run-start", str(root), "--package", "wp-cancel",
        "--run", "run-cancel", "--agent", "claude",
    ], root))
    call([
        AGENT_OS, "lock-release", str(root), "--work-unit", "default",
        "--reason", "simulate an obsolete interrupted Run",
    ], root)
    state_path = root / ".agent-shift/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["handoff_id"] = "newer-handoff"
    write(state_path, json.dumps(state, indent=2) + "\n")
    cancelled = json.loads(call([
        AGENT_OS, "run-cancel", str(root), "--run", "run-cancel",
        "--reason", "A newer handoff superseded this clean abandoned Run",
    ], root))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["worktree"] == started["worktree"]
    assert cancelled["worktree_preserved"] is True
    with sqlite3.connect(root / ".agent-os/state.db") as db:
        assert db.execute("SELECT status FROM runs WHERE id='run-cancel'").fetchone()[0] == "CANCELLED"
        assert db.execute("SELECT status FROM work_packages WHERE id='wp-cancel'").fetchone()[0] == "CANCELLED"


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="agent-os-v04-", dir="/tmp"))
    try:
        test_l0_lightweight(parent)
        test_post_acceptance_drift_gate(parent)
        test_l1_live_delivery_binds_final_artifact_and_endpoint(parent)
        test_installable_delivery_requires_real_package_acceptance(parent)
        test_l1_outcome_and_rollback(parent)
        test_intermediate_review_stays_run_local(parent)
        test_l1_refuted_outcome(parent)
        test_l2_challenge_and_maturity(parent)
        test_v03_explicit_migration(parent)
        test_migration_refuses_active_lock(parent)
        test_runtime_recover_reuses_same_run(parent)
        test_orphaned_run_can_be_cancelled(parent)
        print(json.dumps({
            "result": "PASS", "workspace": str(parent),
            "scenarios": [
                "L0-default-lightweight", "post-acceptance-drift-gate", "L1-live-artifact-endpoint-gate", "L1-installable-package-acceptance", "L1-risk-forces-L2", "L1-outcome-contract",
                "run-local-intermediate-review",
                "outcome-inconclusive", "outcome-confirmed", "outcome-refuted",
                "outcome-safe-rollback", "L2-director-challenge", "L2-maturity",
                "governance-economics", "v03-explicit-migration", "migration-active-lock-refusal",
                "same-run-runtime-recovery",
                "orphaned-run-cancellation",
            ],
        }, indent=2))
        return 0
    except Exception:
        print(json.dumps({"result": "FAIL", "workspace": str(parent)}, indent=2))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
