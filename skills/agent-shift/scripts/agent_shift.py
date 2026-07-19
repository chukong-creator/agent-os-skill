#!/usr/bin/env python3
"""Deterministic local control plane for Codex-Claude collaboration."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = 2
STATUS_OWNER = {
    "SCOPED": "codex",
    "CLAUDE_IMPLEMENTING": "claude",
    "READY_FOR_REVIEW": "codex",
    "CODEX_REVIEWING": "codex",
    "CHANGES_REQUESTED": "claude",
    "CLAUDE_REWORK": "claude",
    "BLOCKED_DECISION": "codex",
    "ACCEPTED": "codex",
    "ROLLED_BACK": "codex",
    "CODE_REVERTED_EXTERNAL_PENDING": "codex",
    "ROLLBACK_FAILED": "codex",
}
ALLOWED_TRANSITIONS = {
    "SCOPED": {"CLAUDE_IMPLEMENTING", "BLOCKED_DECISION"},
    "CLAUDE_IMPLEMENTING": {"READY_FOR_REVIEW", "BLOCKED_DECISION"},
    "READY_FOR_REVIEW": {"CODEX_REVIEWING", "BLOCKED_DECISION"},
    "CODEX_REVIEWING": {"ACCEPTED", "CHANGES_REQUESTED", "BLOCKED_DECISION"},
    "CHANGES_REQUESTED": {"CLAUDE_REWORK", "BLOCKED_DECISION"},
    "CLAUDE_REWORK": {"READY_FOR_REVIEW", "BLOCKED_DECISION"},
    "BLOCKED_DECISION": {"SCOPED", "CLAUDE_IMPLEMENTING", "CLAUDE_REWORK"},
    "ACCEPTED": {"SCOPED"},
    "ROLLED_BACK": {"SCOPED"},
    "CODE_REVERTED_EXTERNAL_PENDING": {"SCOPED"},
    "ROLLBACK_FAILED": {"SCOPED"},
}
REQUIRED_SHIFT_FILES = (
    "project.json",
    "state.json",
    "baselines.json",
    "worktrees.json",
    "HANDOFF.md",
    "WORK_QUEUE.md",
    "WORKLOG.md",
    "RETURN.md",
    "ACTIVITY.jsonl",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def find_work_unit(config: dict[str, Any], unit_id: str) -> dict[str, Any]:
    for unit in config.get("work_units", []):
        if isinstance(unit, dict) and unit.get("id") == unit_id:
            return unit
    raise ValueError(f"unknown work unit: {unit_id}")


def git_output(repo: Path, *args: str, timeout: int = 60) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return completed.stdout.strip()


def repo_is_clean(repo: Path) -> bool:
    return not git_output(repo, "status", "--porcelain")


def path_is_allowed(path: str, allowed: list[str]) -> bool:
    normalized = path.rstrip("/")
    return any(normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/") for item in allowed)


def path_is_denied(path: str, denied: list[str]) -> bool:
    normalized = path.rstrip("/")
    return any(normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/") for item in denied)


def project_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project root does not exist: {root}")
    return root


def skill_assets() -> Path:
    return Path(__file__).resolve().parents[1] / "assets"


def copy_template_if_missing(template_name: str, destination: Path, project_name: str) -> bool:
    if destination.exists():
        return False
    text = (skill_assets() / template_name).read_text(encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text.replace("{{PROJECT_NAME}}", project_name), encoding="utf-8")
    return True


def append_activity(root: Path, actor: str, event: str, summary: str, **extra: Any) -> None:
    record = {"timestamp": now_iso(), "actor": actor, "event": event, "summary": summary}
    record.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    path = root / ".agent-shift" / "ACTIVITY.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def cmd_init(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    shift = root / ".agent-shift"
    shift.mkdir(exist_ok=True)
    (shift / "reviews").mkdir(exist_ok=True)
    created: list[str] = []

    config_path = shift / "project.json"
    if not config_path.exists():
        atomic_json_write(
            config_path,
            {
                "protocol_version": PROTOCOL_VERSION,
                "project_name": args.name,
                "work_units": [
                    {
                        "id": "default",
                        "repo_root": ".",
                        "implementation_paths": [],
                        "director_owned_paths": ["AGENTS.md", "CLAUDE.md", ".agent-shift"],
                        "verify_commands": [],
                        "git_policy": {
                            "required": True,
                            "baseline_branch": "main",
                            "agent_branch_prefix": "agent",
                            "merge_strategy": "no-ff",
                        },
                        "publish_policy": "Do not publish without explicit user authorization.",
                    }
                ],
                "known_blockers": [],
                "user_escalation": [
                    "material product or scope change",
                    "irreversible, production, credential, security, privacy, or financial action",
                    "same review finding fails three times",
                    "user-owned dirty work cannot be safely isolated",
                ],
            },
        )
        created.append(str(config_path.relative_to(root)))

    state_path = shift / "state.json"
    if not state_path.exists():
        atomic_json_write(
            state_path,
            {
                "protocol_version": PROTOCOL_VERSION,
                "handoff_id": None,
                "status": "SCOPED",
                "owner": "codex",
                "active_work_unit": None,
                "active_work_package": None,
                "review_round": 0,
                "baseline_commit": None,
                "agent_branch": None,
                "worktree_path": None,
                "merge_commit": None,
                "rollback_commit": None,
                "updated_at": now_iso(),
                "note": "Initialized; Codex must scope the first work package.",
            },
        )
        created.append(str(state_path.relative_to(root)))

    baselines_path = shift / "baselines.json"
    if not baselines_path.exists():
        atomic_json_write(baselines_path, {"protocol_version": PROTOCOL_VERSION, "work_units": {}})
        created.append(str(baselines_path.relative_to(root)))

    worktrees_path = shift / "worktrees.json"
    if not worktrees_path.exists():
        atomic_json_write(worktrees_path, {"protocol_version": PROTOCOL_VERSION, "branches": {}})
        created.append(str(worktrees_path.relative_to(root)))

    templates = {
        "CLAUDE.md.template": root / "CLAUDE.md",
        "HANDOFF.md.template": shift / "HANDOFF.md",
        "WORK_QUEUE.md.template": shift / "WORK_QUEUE.md",
        "WORKLOG.md.template": shift / "WORKLOG.md",
        "RETURN.md.template": shift / "RETURN.md",
    }
    for source, destination in templates.items():
        if copy_template_if_missing(source, destination, args.name):
            created.append(str(destination.relative_to(root)))

    activity = shift / "ACTIVITY.jsonl"
    if not activity.exists():
        activity.touch()
        created.append(str(activity.relative_to(root)))
    append_activity(root, "system", "initialized", f"Agent Shift initialized for {args.name}")

    print(json.dumps({"project": str(root), "created": created, "preserved_existing": True}, ensure_ascii=False, indent=2))
    return 0


def run_command(command: str, cwd: Path, timeout: int = 180) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout.rstrip()


def check_claude_sessions(root: Path) -> tuple[str, str]:
    claude = shutil.which("claude")
    if not claude:
        return "FAIL", "claude executable not found"
    try:
        completed = subprocess.run(
            [claude, "agents", "--json", "--all", "--cwd", str(root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "WARN", "claude agent query timed out"
    if completed.returncode != 0:
        return "WARN", f"claude agent query failed: {completed.stderr.strip()}"
    try:
        sessions = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return "WARN", "claude agent query returned invalid JSON"
    return "PASS", f"claude available; {len(sessions)} recorded background session(s) for cwd"


def cmd_doctor(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    shift = root / ".agent-shift"
    checks: list[tuple[str, str]] = []

    for relative in ("AGENTS.md", "CLAUDE.md"):
        path = root / relative
        checks.append(("PASS" if path.is_file() else "FAIL", f"{relative} {'present' if path.is_file() else 'missing'}"))
    for relative in REQUIRED_SHIFT_FILES:
        path = shift / relative
        checks.append(("PASS" if path.is_file() else "FAIL", f".agent-shift/{relative} {'present' if path.is_file() else 'missing'}"))

    config: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    baselines: dict[str, Any] | None = None
    worktrees: dict[str, Any] | None = None
    try:
        config = load_json(shift / "project.json")
        checks.append(("PASS" if config.get("protocol_version") == PROTOCOL_VERSION else "FAIL", "project protocol version"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        checks.append(("FAIL", f"invalid project.json: {error}"))
    try:
        state = load_json(shift / "state.json")
        status = state.get("status")
        owner = state.get("owner")
        checks.append(("PASS" if status in STATUS_OWNER else "FAIL", f"state status: {status}"))
        checks.append(("PASS" if STATUS_OWNER.get(status) == owner else "FAIL", f"state owner: {owner}"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        checks.append(("FAIL", f"invalid state.json: {error}"))
    try:
        baselines = load_json(shift / "baselines.json")
        checks.append(("PASS" if baselines.get("protocol_version") == PROTOCOL_VERSION else "FAIL", "baseline protocol version"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        checks.append(("FAIL", f"invalid baselines.json: {error}"))
    try:
        worktrees = load_json(shift / "worktrees.json")
        checks.append(("PASS" if worktrees.get("protocol_version") == PROTOCOL_VERSION else "FAIL", "worktree registry protocol version"))
        for branch, record in worktrees.get("branches", {}).items():
            worktree_path = Path(str(record.get("path", "")))
            checks.append(("PASS" if worktree_path.is_dir() else "WARN", f"registered worktree {branch}: {worktree_path}"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        checks.append(("FAIL", f"invalid worktrees.json: {error}"))

    if config:
        units = config.get("work_units")
        if not isinstance(units, list) or not units:
            checks.append(("FAIL", "project.json has no work_units"))
        else:
            for unit in units:
                if not isinstance(unit, dict) or not unit.get("id") or not unit.get("repo_root"):
                    checks.append(("FAIL", "work unit missing id or repo_root"))
                    continue
                unit_root = (root / str(unit["repo_root"])).resolve()
                checks.append(("PASS" if unit_root.is_dir() else "FAIL", f"work unit {unit['id']} root: {unit_root}"))
                if unit_root.is_dir():
                    git_code, git_head = run_command("git rev-parse --verify HEAD", unit_root, timeout=10)
                    git_required = unit.get("git_policy", {}).get("required", True)
                    level = "PASS" if git_code == 0 else ("FAIL" if git_required else "WARN")
                    checks.append((level, f"work unit {unit['id']} Git HEAD {'available' if git_code == 0 else 'unavailable'}"))
                    baseline = (baselines or {}).get("work_units", {}).get(str(unit["id"]))
                    if baseline and git_code == 0:
                        baseline_commit = str(baseline.get("commit", ""))
                        commit_code, _ = run_command(f"git cat-file -e {baseline_commit}^{{commit}}", unit_root, timeout=10)
                        baseline_ok = commit_code == 0 and baseline_commit == git_head.strip()
                        checks.append(("PASS" if baseline_ok else "FAIL", f"work unit {unit['id']} recorded baseline equals current HEAD"))
                    else:
                        checks.append(("FAIL" if git_required else "WARN", f"work unit {unit['id']} baseline record missing"))
                    clean_code, clean_output = run_command("git status --porcelain", unit_root, timeout=10)
                    checks.append(("PASS" if clean_code == 0 and not clean_output else "WARN", f"work unit {unit['id']} base working tree {'clean' if clean_code == 0 and not clean_output else 'dirty'}"))
                    hooks_code, hooks_output = run_command("git config --get core.hooksPath", unit_root, timeout=10)
                    hooks_ok = hooks_code == 0 and hooks_output == ".githooks"
                    checks.append(("PASS" if hooks_ok else "FAIL", f"work unit {unit['id']} protected-main hooks configured"))
                    for hook_name in ("pre-commit", "pre-merge-commit", "pre-push"):
                        hook_path = unit_root / ".githooks" / hook_name
                        checks.append(("PASS" if hook_path.is_file() and os.access(hook_path, os.X_OK) else "FAIL", f"work unit {unit['id']} hook {hook_name}"))
                for source in unit.get("canonical_sources", []):
                    source_path = Path(str(source)).expanduser()
                    checks.append(("PASS" if source_path.exists() else "FAIL", f"work unit {unit['id']} canonical source: {source_path}"))
                commands = unit.get("verify_commands", [])
                if not isinstance(commands, list):
                    checks.append(("FAIL", f"work unit {unit['id']} verify_commands must be an array"))
                elif args.run_verify:
                    for command in commands:
                        code, output = run_command(str(command), unit_root)
                        summary = output.splitlines()[-1] if output else "no output"
                        checks.append(("PASS" if code == 0 else "FAIL", f"{unit['id']} verify `{command}`: {summary}"))
            for blocker in config.get("known_blockers", []):
                checks.append(("WARN", f"known blocker: {blocker}"))

    checks.append(check_claude_sessions(root))
    for level, message in checks:
        print(f"{level:4} {message}")
    failures = sum(level == "FAIL" for level, _ in checks)
    warnings = sum(level == "WARN" for level, _ in checks)
    print(f"SUMMARY failures={failures} warnings={warnings} checks={len(checks)}")
    if failures or (args.strict and warnings):
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    state = load_json(root / ".agent-shift" / "state.json")
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        for key in ("status", "owner", "handoff_id", "active_work_unit", "active_work_package", "baseline_commit", "agent_branch", "worktree_path", "merge_commit", "rollback_commit", "review_round", "updated_at", "note"):
            print(f"{key}: {state.get(key)}")
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    state_path = root / ".agent-shift" / "state.json"
    state = load_json(state_path)
    current = str(state.get("status"))
    target = args.status
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid transition: {current} -> {target}")
    handoff_id = args.handoff_id or state.get("handoff_id")
    if target in {"CLAUDE_IMPLEMENTING", "CLAUDE_REWORK"} and not handoff_id:
        raise ValueError(f"{target} requires --handoff-id or an existing handoff_id")
    if target in {"CLAUDE_IMPLEMENTING", "CLAUDE_REWORK"} and (not state.get("agent_branch") or not state.get("worktree_path")):
        raise ValueError(f"{target} requires an Agent Shift worktree")
    if target == "ACCEPTED":
        gate_path = root / ".agent-shift" / "merge-gate.json"
        gate = load_json(gate_path)
        if gate.get("result") != "PASS" or gate.get("branch") != state.get("agent_branch"):
            raise ValueError("ACCEPTED requires a passing merge gate for the active branch")
        config = load_json(root / ".agent-shift" / "project.json")
        unit_id = str(state.get("active_work_unit") or "")
        unit = find_work_unit(config, unit_id)
        repo = (root / str(unit["repo_root"])).resolve()
        branch = str(state.get("agent_branch") or "")
        if not branch or git_output(repo, "rev-parse", branch) != gate.get("branch_commit"):
            raise ValueError("ACCEPTED requires the exact gated branch commit")
    state.update(
        {
            "status": target,
            "owner": STATUS_OWNER[target],
            "handoff_id": handoff_id,
            "updated_at": now_iso(),
            "note": args.note,
        }
    )
    if args.work_unit:
        state["active_work_unit"] = args.work_unit
    if args.work_package:
        state["active_work_package"] = args.work_package
    if target == "CHANGES_REQUESTED":
        state["review_round"] = int(state.get("review_round", 0)) + 1
    atomic_json_write(state_path, state)
    append_activity(root, args.actor, "transition", f"{current} -> {target}", handoff_id=handoff_id, note=args.note)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    append_activity(root, args.actor, args.event, args.summary, files=args.files, result=args.result)
    print("activity appended")
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    config = load_json(root / ".agent-shift" / "project.json")
    unit = find_work_unit(config, args.work_unit)
    repo = (root / str(unit["repo_root"])).resolve()
    commit = git_output(repo, "rev-parse", "HEAD")
    branch = git_output(repo, "branch", "--show-current")
    expected_branch = str(unit.get("git_policy", {}).get("baseline_branch", "main"))
    if branch != expected_branch:
        raise ValueError(f"baseline must be recorded on {expected_branch}, current branch is {branch}")
    if not repo_is_clean(repo):
        raise ValueError(f"baseline working tree is dirty: {repo}")
    baselines_path = root / ".agent-shift" / "baselines.json"
    lock_path = root / ".agent-shift" / ".baseline.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        baselines = load_json(baselines_path)
        units = baselines.setdefault("work_units", {})
        units[args.work_unit] = {"repo_root": str(unit["repo_root"]), "branch": branch, "commit": commit, "recorded_at": now_iso()}
        baselines["protocol_version"] = PROTOCOL_VERSION
        atomic_json_write(baselines_path, baselines)
    append_activity(root, "codex", "baseline_recorded", f"Recorded {args.work_unit} at {commit[:12]}", work_unit=args.work_unit)
    print(json.dumps(units[args.work_unit], ensure_ascii=False, indent=2))
    return 0


def cmd_worktree_create(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    config = load_json(root / ".agent-shift" / "project.json")
    unit = find_work_unit(config, args.work_unit)
    repo = (root / str(unit["repo_root"])).resolve()
    baselines = load_json(root / ".agent-shift" / "baselines.json")
    baseline = baselines.get("work_units", {}).get(args.work_unit)
    if not baseline:
        raise ValueError(f"record a baseline for {args.work_unit} before creating worktrees")
    base_branch = str(unit.get("git_policy", {}).get("baseline_branch", "main"))
    baseline_commit = str(baseline["commit"])
    git_output(repo, "merge-base", "--is-ancestor", baseline_commit, base_branch)
    current_base_commit = git_output(repo, "rev-parse", base_branch)
    if current_base_commit != baseline_commit:
        raise ValueError(
            f"recorded baseline {baseline_commit[:12]} does not match {base_branch} "
            f"{current_base_commit[:12]}; review and record a fresh baseline"
        )
    if not repo_is_clean(repo):
        raise ValueError(f"base working tree is dirty: {repo}")
    safe_handoff = "".join(character if character.isalnum() or character in "-_" else "-" for character in args.handoff_id)
    prefix = str(unit.get("git_policy", {}).get("agent_branch_prefix", "agent"))
    branch = f"{prefix}/{args.agent}/{args.work_unit}/{safe_handoff}"
    worktree = root / ".agent-shift" / "worktrees" / args.work_unit / safe_handoff
    if worktree.exists():
        raise ValueError(f"worktree path already exists: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git_output(repo, "worktree", "add", "-b", branch, str(worktree), baseline_commit, timeout=120)
    registry_path = root / ".agent-shift" / "worktrees.json"
    registry = load_json(registry_path)
    branches = registry.setdefault("branches", {})
    branches[branch] = {
        "work_unit": args.work_unit,
        "handoff_id": args.handoff_id,
        "agent": args.agent,
        "path": str(worktree),
        "baseline_commit": baseline_commit,
        "created_at": now_iso(),
    }
    registry["protocol_version"] = PROTOCOL_VERSION
    atomic_json_write(registry_path, registry)
    state_path = root / ".agent-shift" / "state.json"
    state = load_json(state_path)
    state.update(
        {
            "handoff_id": args.handoff_id,
            "active_work_unit": args.work_unit,
            "baseline_commit": baseline_commit,
            "agent_branch": branch,
            "worktree_path": str(worktree),
            "merge_commit": None,
            "rollback_commit": None,
            "updated_at": now_iso(),
            "note": f"Worktree prepared for {args.agent}.",
        }
    )
    atomic_json_write(state_path, state)
    append_activity(root, "codex", "worktree_created", f"Created {branch}", work_unit=args.work_unit, worktree=str(worktree))
    print(json.dumps({"work_unit": args.work_unit, "branch": branch, "worktree": str(worktree), "baseline_commit": state["baseline_commit"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_merge_gate(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    config = load_json(root / ".agent-shift" / "project.json")
    unit = find_work_unit(config, args.work_unit)
    repo = (root / str(unit["repo_root"])).resolve()
    state = load_json(root / ".agent-shift" / "state.json")
    if state.get("status") not in {"READY_FOR_REVIEW", "CODEX_REVIEWING"}:
        raise ValueError("merge gate requires READY_FOR_REVIEW or CODEX_REVIEWING")
    branch = args.branch or state.get("agent_branch")
    registry = load_json(root / ".agent-shift" / "worktrees.json")
    branch_record = registry.get("branches", {}).get(str(branch), {})
    worktree_value = branch_record.get("path") or state.get("worktree_path")
    if not branch or not worktree_value:
        raise ValueError("active branch and worktree are required")
    worktree = Path(str(worktree_value))
    base_branch = str(unit.get("git_policy", {}).get("baseline_branch", "main"))
    base_commit = git_output(repo, "rev-parse", base_branch)
    branch_commit = git_output(repo, "rev-parse", str(branch))
    checks: list[dict[str, Any]] = []

    ahead = int(git_output(repo, "rev-list", "--count", f"{base_branch}..{branch}") or "0")
    checks.append({"name": "branch_ahead", "passed": ahead > 0, "detail": f"{ahead} commit(s)"})
    diff_check, diff_output = run_command(f"git diff --check {base_branch}...{branch}", repo, timeout=30)
    checks.append({"name": "diff_check", "passed": diff_check == 0, "detail": diff_output or "clean"})
    merge_tree, merge_output = run_command(f"git merge-tree --write-tree {base_branch} {branch}", repo, timeout=30)
    checks.append({"name": "merge_conflicts", "passed": merge_tree == 0, "detail": "none" if merge_tree == 0 else merge_output})
    changed = [line for line in git_output(repo, "diff", "--name-only", f"{base_branch}...{branch}").splitlines() if line]
    allowed = [str(value) for value in unit.get("implementation_paths", [])]
    denied = [str(value) for value in [*unit.get("director_owned_paths", []), *unit.get("deny_paths", [])]]
    disallowed = [path for path in changed if not path_is_allowed(path, allowed) or path_is_denied(path, denied)]
    checks.append({"name": "path_allowlist", "passed": not disallowed, "detail": disallowed or changed})
    checks.append({"name": "worktree_clean", "passed": repo_is_clean(worktree), "detail": str(worktree)})
    for command in unit.get("verify_commands", []):
        code, output = run_command(str(command), worktree)
        checks.append({"name": f"verify:{command}", "passed": code == 0, "detail": output.splitlines()[-1] if output else "no output"})

    result = "PASS" if all(check["passed"] for check in checks) else "FAIL"
    gate = {
        "protocol_version": PROTOCOL_VERSION,
        "result": result,
        "work_unit": args.work_unit,
        "base_branch": base_branch,
        "base_commit": base_commit,
        "branch": branch,
        "branch_commit": branch_commit,
        "changed_paths": changed,
        "checks": checks,
        "checked_at": now_iso(),
    }
    atomic_json_write(root / ".agent-shift" / "merge-gate.json", gate)
    append_activity(root, "codex", "merge_gate", f"Merge gate {result} for {branch}", work_unit=args.work_unit)
    print(json.dumps(gate, ensure_ascii=False, indent=2))
    return 0 if result == "PASS" else 1


def cmd_merge(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    config = load_json(root / ".agent-shift" / "project.json")
    unit = find_work_unit(config, args.work_unit)
    repo = (root / str(unit["repo_root"])).resolve()
    state_path = root / ".agent-shift" / "state.json"
    state = load_json(state_path)
    gate = load_json(root / ".agent-shift" / "merge-gate.json")
    branch = str(state.get("agent_branch") or "")
    if state.get("status") != "ACCEPTED":
        raise ValueError("merge requires Codex ACCEPTED state")
    if gate.get("result") != "PASS" or gate.get("branch") != branch:
        raise ValueError("merge requires a passing gate for the active branch")
    if git_output(repo, "rev-parse", branch) != gate.get("branch_commit"):
        raise ValueError("agent branch changed after merge gate; run the gate again")
    base_branch = str(unit.get("git_policy", {}).get("baseline_branch", "main"))
    if git_output(repo, "branch", "--show-current") != base_branch:
        raise ValueError(f"base worktree must be on {base_branch}")
    if not repo_is_clean(repo):
        raise ValueError("base worktree must be clean before merge")
    current_base_commit = git_output(repo, "rev-parse", base_branch)
    if current_base_commit != gate.get("base_commit"):
        raise ValueError("base branch changed after merge gate; run the gate again")
    strategy = str(unit.get("git_policy", {}).get("merge_strategy", "no-ff"))
    merge_args = ["merge", "--no-ff", "--no-edit", branch] if strategy == "no-ff" else ["merge", "--ff-only", branch]
    previous_allow = os.environ.get("AGENT_SHIFT_ALLOW_MAIN_COMMIT")
    os.environ["AGENT_SHIFT_ALLOW_MAIN_COMMIT"] = "1"
    try:
        git_output(repo, *merge_args, timeout=120)
    finally:
        if previous_allow is None:
            os.environ.pop("AGENT_SHIFT_ALLOW_MAIN_COMMIT", None)
        else:
            os.environ["AGENT_SHIFT_ALLOW_MAIN_COMMIT"] = previous_allow
    merge_commit = git_output(repo, "rev-parse", "HEAD")
    state.update({"merge_commit": merge_commit, "updated_at": now_iso(), "note": f"Merged {branch} into {base_branch}."})
    atomic_json_write(state_path, state)
    append_activity(root, "codex", "merged", f"Merged {branch}", work_unit=args.work_unit, merge_commit=merge_commit)
    print(json.dumps({"branch": branch, "base_branch": base_branch, "merge_commit": merge_commit}, ensure_ascii=False, indent=2))
    return 0


def cmd_rollback_record(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    state_path = root / ".agent-shift" / "state.json"
    state = load_json(state_path)
    if state.get("status") != "ACCEPTED":
        raise ValueError("rollback-record requires ACCEPTED state")
    if state.get("merge_commit") != args.merge_commit:
        raise ValueError("rollback-record merge commit does not match Agent Shift state")
    state.update({
        "status": args.status, "owner": "codex",
        "rollback_commit": args.rollback_commit, "updated_at": now_iso(),
        "note": args.note,
    })
    atomic_json_write(state_path, state)
    append_activity(root, "codex", "rolled_back", args.note, merge_commit=args.merge_commit, rollback_commit=args.rollback_commit)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_worktree_remove(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    config = load_json(root / ".agent-shift" / "project.json")
    unit = find_work_unit(config, args.work_unit)
    repo = (root / str(unit["repo_root"])).resolve()
    state_path = root / ".agent-shift" / "state.json"
    state = load_json(state_path)
    registry_path = root / ".agent-shift" / "worktrees.json"
    registry = load_json(registry_path)
    branch = args.branch or state.get("agent_branch")
    branch_record = registry.get("branches", {}).get(str(branch), {})
    worktree_value = branch_record.get("path") or state.get("worktree_path")
    if not worktree_value:
        raise ValueError("no active worktree recorded")
    worktree = Path(str(worktree_value))
    if worktree.exists() and not repo_is_clean(worktree):
        raise ValueError(f"worktree is dirty and will not be removed: {worktree}")
    git_output(repo, "worktree", "remove", str(worktree), timeout=120)
    registry.get("branches", {}).pop(str(branch), None)
    atomic_json_write(registry_path, registry)
    if state.get("agent_branch") == branch:
        state.update({"worktree_path": None, "updated_at": now_iso(), "note": "Agent worktree removed."})
    atomic_json_write(state_path, state)
    append_activity(root, "codex", "worktree_removed", f"Removed {worktree}", work_unit=args.work_unit)
    print(str(worktree))
    return 0


def cmd_protect_main(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    config = load_json(root / ".agent-shift" / "project.json")
    unit = find_work_unit(config, args.work_unit)
    repo = (root / str(unit["repo_root"])).resolve()
    hooks_source = skill_assets() / "hooks"
    hooks_target = repo / ".githooks"
    hooks_target.mkdir(exist_ok=True)
    for hook_name in ("pre-commit", "pre-merge-commit", "pre-push"):
        source = hooks_source / hook_name
        target = hooks_target / hook_name
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError(f"refusing to overwrite different hook: {target}")
        shutil.copyfile(source, target)
        target.chmod(0o755)
    git_output(repo, "config", "core.hooksPath", ".githooks")
    append_activity(root, "codex", "protected_main", f"Installed protected-main hooks for {args.work_unit}", work_unit=args.work_unit)
    print(str(hooks_target))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize missing project collaboration files")
    init.add_argument("project")
    init.add_argument("--name", required=True)
    init.set_defaults(func=cmd_init)

    doctor = sub.add_parser("doctor", help="validate project collaboration health")
    doctor.add_argument("project")
    doctor.add_argument("--run-verify", action="store_true")
    doctor.add_argument("--strict", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    status = sub.add_parser("status", help="show collaboration runtime state")
    status.add_argument("project")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    transition = sub.add_parser("transition", help="perform a validated state transition")
    transition.add_argument("project")
    transition.add_argument("status", choices=sorted(STATUS_OWNER))
    transition.add_argument("--handoff-id")
    transition.add_argument("--work-unit")
    transition.add_argument("--work-package")
    transition.add_argument("--note", required=True)
    transition.add_argument("--actor", choices=("codex", "claude", "codex-subagent", "claude-subagent", "system"), default="codex")
    transition.set_defaults(func=cmd_transition)

    log = sub.add_parser("log", help="append a structured activity record")
    log.add_argument("project")
    log.add_argument("--actor", required=True, choices=("codex", "claude", "codex-subagent", "claude-subagent", "system"))
    log.add_argument("--event", required=True)
    log.add_argument("--summary", required=True)
    log.add_argument("--files", nargs="*", default=[])
    log.add_argument("--result")
    log.set_defaults(func=cmd_log)

    baseline = sub.add_parser("baseline", help="record a clean Git baseline for one work unit")
    baseline.add_argument("project")
    baseline.add_argument("--work-unit", required=True)
    baseline.set_defaults(func=cmd_baseline)

    worktree = sub.add_parser("worktree-create", help="create an isolated agent branch and worktree")
    worktree.add_argument("project")
    worktree.add_argument("--work-unit", required=True)
    worktree.add_argument("--handoff-id", required=True)
    worktree.add_argument("--agent", choices=("claude", "codex-subagent", "claude-subagent"), required=True)
    worktree.set_defaults(func=cmd_worktree_create)

    gate = sub.add_parser("merge-gate", help="verify an agent branch before Codex acceptance")
    gate.add_argument("project")
    gate.add_argument("--work-unit", required=True)
    gate.add_argument("--branch")
    gate.set_defaults(func=cmd_merge_gate)

    merge = sub.add_parser("merge", help="merge a gate-passing accepted agent branch")
    merge.add_argument("project")
    merge.add_argument("--work-unit", required=True)
    merge.set_defaults(func=cmd_merge)

    rollback = sub.add_parser("rollback-record", help="record an Agent OS verified rollback")
    rollback.add_argument("project")
    rollback.add_argument("--merge-commit", required=True)
    rollback.add_argument("--rollback-commit", required=True)
    rollback.add_argument("--status", choices=("ROLLED_BACK", "CODE_REVERTED_EXTERNAL_PENDING", "ROLLBACK_FAILED"), required=True)
    rollback.add_argument("--note", required=True)
    rollback.set_defaults(func=cmd_rollback_record)

    remove = sub.add_parser("worktree-remove", help="remove a clean recorded agent worktree")
    remove.add_argument("project")
    remove.add_argument("--work-unit", required=True)
    remove.add_argument("--branch")
    remove.set_defaults(func=cmd_worktree_remove)

    protect = sub.add_parser("protect-main", help="install tracked local hooks that protect main")
    protect.add_argument("project")
    protect.add_argument("--work-unit", required=True)
    protect.set_defaults(func=cmd_protect_main)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
