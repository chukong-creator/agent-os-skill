#!/usr/bin/env python3
"""Agent OS v0.4 proportional, outcome-aware delivery control plane."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


AGENT_OS_VERSION = "0.4"
SCHEMA_REVISION = 4
DEFAULT_LOCK_SECONDS = 7200
DECISIONS = {"ACCEPTED", "CHANGES_REQUESTED", "BLOCKED_DECISION"}
GOVERNANCE_LEVELS = {"L0", "L1", "L2"}
OUTCOME_RESULTS = {"CONFIRMED", "REFUTED", "INCONCLUSIVE"}
OUTCOME_STATES = {f"OUTCOME_{value}" for value in OUTCOME_RESULTS} | {"OUTCOME_PENDING"}
L2_RISK_FACTORS = {
    "production", "privacy", "credentials", "database-migration", "data-deletion",
    "payment", "irreversible", "external-side-effect",
}
FAILURE_CATEGORIES = {
    "goal_contract", "context", "permission", "implementation", "verification",
    "dependency", "runtime", "merge", "external_service", "governance", "unknown",
}
BLOCKER_CLASSES = {"model-fixable", "contradiction", "unverifiable", "new-authority-required"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
HIGH_RISK_FRAGMENTS = (
    "git push", "git reset --hard", "git clean -f", "rm -rf", "deploy", "publish",
    "database migration", "db:migrate", "drizzle-kit migrate", "prisma migrate",
    ".env", "credentials", "secret", "private_key", "payment", "stripe",
)
CC_SWITCH_PROVIDER_ENV_KEYS = {
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
    "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION",
    "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
}
MODEL_ENV_KEYS = {
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
    "CLAUDE_CODE_SUBAGENT_MODEL",
}
EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}
RETRYABLE_RUNTIME_PATTERNS = (
    "quota exhausted", "quota_exhausted", "rate limit exceeded", "rate_limit_error",
    "usage limit reached", "usage_limit_reached", "token limit exhausted",
    "insufficient balance", "insufficient_balance", "insufficient credit", "credit balance",
    "token exhausted", "tokens exhausted", "resource exhausted", "resource_exhausted",
    "overloaded_error", "provider capacity exhausted", "http 402", "http 429", "status 402", "status 429",
    "status code 402", "status code 429", "connection reset by provider", "provider connection refused",
    "provider service unavailable", "provider bad gateway", "provider gateway timeout",
    "http 502", "http 503", "http 504", "authentication_error", "invalid api key",
)
NON_RETRYABLE_RUNTIME_PATTERNS = (
    "working directory no longer exists", "worktree does not exist", "permission denied",
    "agent os routing config", "cc switch database", "unsupported provider schema",
)


def now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
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


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def default_routing_config_path() -> Path:
    configured = os.environ.get("AGENT_OS_ROUTING_CONFIG")
    return Path(configured).expanduser().resolve() if configured else Path("~/.config/agent-os/model-routing.json").expanduser().resolve()


def default_cc_switch_db_path() -> Path:
    configured = os.environ.get("CC_SWITCH_DB")
    return Path(configured).expanduser().resolve() if configured else Path("~/.cc-switch/cc-switch.db").expanduser().resolve()


def cc_switch_provider_rows(database: Path) -> list[sqlite3.Row]:
    database = database.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"CC Switch database does not exist: {database}")
    db: sqlite3.Connection | None = None
    try:
        db = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        return db.execute(
            """SELECT id, name, settings_config, is_current
               FROM providers WHERE app_type='claude'
               ORDER BY is_current DESC, sort_index, name"""
        ).fetchall()
    except sqlite3.Error as error:
        raise ValueError("CC Switch database is unreadable or has an unsupported provider schema") from error
    finally:
        if db is not None:
            db.close()


def parse_cc_switch_provider(row: sqlite3.Row) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        settings = json.loads(str(row["settings_config"]))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"CC Switch provider has invalid settings JSON: {row['name']}") from error
    if not isinstance(settings, dict) or not isinstance(settings.get("env", {}), dict):
        raise ValueError(f"CC Switch provider has an invalid Claude env object: {row['name']}")
    raw_env = settings.get("env", {})
    invalid_values = [key for key, value in raw_env.items() if not isinstance(key, str) or not isinstance(value, str)]
    if invalid_values:
        raise ValueError(f"CC Switch provider has non-string environment values: {row['name']}")
    provider_env = {key: value for key, value in raw_env.items() if key in CC_SWITCH_PROVIDER_ENV_KEYS}
    base_url = provider_env.get("ANTHROPIC_BASE_URL", "")
    parsed_base_url = urlparse(base_url) if base_url else None
    metadata = {
        "provider_id": str(row["id"]),
        "provider": str(row["name"]),
        "is_current": bool(row["is_current"]),
        "model": provider_env.get("ANTHROPIC_MODEL"),
        "base_url_host": parsed_base_url.hostname if parsed_base_url else None,
        "credential_source": "cc-switch-memory",
        "ignored_env_keys": sorted(set(raw_env) - CC_SWITCH_PROVIDER_ENV_KEYS),
    }
    return metadata, provider_env


def cc_switch_providers(database: Path) -> list[dict[str, Any]]:
    return [parse_cc_switch_provider(row)[0] for row in cc_switch_provider_rows(database)]


def cc_switch_provider(database: Path, selector: str) -> tuple[dict[str, Any], dict[str, str]]:
    rows = cc_switch_provider_rows(database)
    id_matches = [row for row in rows if str(row["id"]) == selector]
    matches = id_matches or [row for row in rows if str(row["name"]) == selector]
    if not matches:
        raise ValueError(f"CC Switch Claude provider not found: {selector}")
    if len(matches) > 1:
        raise ValueError(f"CC Switch provider name is ambiguous; use provider_id: {selector}")
    return parse_cc_switch_provider(matches[0])


def load_routing_config(path: Path) -> dict[str, Any]:
    config = read_json(path)
    if int(config.get("schema_version", 0)) != 1:
        raise ValueError("Agent OS routing config requires schema_version 1")
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("Agent OS routing config requires non-empty profiles")
    for name, profile in profiles.items():
        if not isinstance(name, str) or not isinstance(profile, dict):
            raise ValueError("Agent OS routing profiles must be named JSON objects")
        forbidden = [key for key in profile if any(fragment in key.lower() for fragment in ("key", "token", "secret", "password", "credential", "auth"))]
        if forbidden:
            raise ValueError(f"Agent OS routing profiles cannot contain credentials: {name}")
    return config


def resolve_execution_profile(profile_name: str | None, config_path: Path | None = None) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if profile_name == "inherit":
        return None, None
    path = (config_path or default_routing_config_path()).expanduser().resolve()
    if not path.is_file():
        if profile_name is None:
            return None, None
        raise FileNotFoundError(f"Agent OS routing config does not exist: {path}")
    config = load_routing_config(path)
    selected_name = profile_name or str(config.get("default_profile", "builder"))
    profile = config["profiles"].get(selected_name)
    if not isinstance(profile, dict):
        raise ValueError(f"unknown Agent OS execution profile: {selected_name}")
    selector = profile.get("provider_id") or profile.get("provider")
    if not isinstance(selector, str) or not selector:
        raise ValueError(f"execution profile requires provider or provider_id: {selected_name}")
    database = Path(str(config.get("cc_switch_database", default_cc_switch_db_path()))).expanduser().resolve()
    metadata, provider_env = cc_switch_provider(database, selector)
    model = profile.get("model") or metadata.get("model")
    if model is not None and (not isinstance(model, str) or not model):
        raise ValueError(f"execution profile has an invalid model: {selected_name}")
    effort = profile.get("effort")
    if effort is not None and effort not in EFFORT_LEVELS:
        raise ValueError(f"execution profile has an invalid effort: {selected_name}")
    if model:
        provider_env.update({key: model for key in MODEL_ENV_KEYS})
    safe = {
        **metadata,
        "profile": selected_name,
        "model": model,
        "effort": effort,
        "mode": str(profile.get("mode", "builder")),
        "routing_config": str(path),
    }
    return safe, provider_env


def provider_child_environment(provider_env: dict[str, str] | None) -> dict[str, str] | None:
    if provider_env is None:
        return None
    environment = os.environ.copy()
    for key in CC_SWITCH_PROVIDER_ENV_KEYS:
        environment.pop(key, None)
    environment.update(provider_env)
    return environment


def fallback_chain(config_path: Path, mode: str, current_profile: str) -> list[str]:
    config = load_routing_config(config_path)
    chains = config.get("fallback_chains", {})
    if not isinstance(chains, dict):
        raise ValueError("fallback_chains must be a JSON object")
    configured = chains.get(mode, [current_profile])
    if not isinstance(configured, list) or not configured or not all(isinstance(item, str) and item for item in configured):
        raise ValueError(f"fallback chain must be a non-empty profile list: {mode}")
    unknown = [item for item in configured if item not in config["profiles"]]
    if unknown:
        raise ValueError(f"fallback chain contains unknown profiles: {', '.join(unknown)}")
    if len(configured) != len(set(configured)):
        raise ValueError(f"fallback chain contains duplicate profiles: {mode}")
    if current_profile not in configured:
        return [current_profile]
    return configured


def classify_runtime_failure(detail: str | None) -> str:
    normalized = (detail or "").lower()
    if any(pattern in normalized for pattern in NON_RETRYABLE_RUNTIME_PATTERNS):
        return "environment"
    if any(pattern in normalized for pattern in RETRYABLE_RUNTIME_PATTERNS):
        return "provider_or_quota"
    return "runtime_unknown"


def runtime_recovery_decision(
    state: str | None, detail: str | None, chain: list[str], current_profile: str,
    attempted_profiles: list[str] | None = None, failure_category: str | None = None,
) -> dict[str, Any]:
    normalized_state = (state or "unknown").lower()
    if normalized_state in {"running", "active", "starting", "unknown"}:
        return {"action": "wait", "state": normalized_state}
    if normalized_state == "done":
        return {"action": "complete", "state": normalized_state}
    if normalized_state == "stopped":
        return {"action": "stop", "state": normalized_state, "category": "operator_or_runtime_stop"}
    category = failure_category or classify_runtime_failure(detail)
    if category != "provider_or_quota":
        return {"action": "fail", "state": normalized_state, "category": category}
    try:
        index = chain.index(current_profile)
    except ValueError:
        return {"action": "fail", "state": normalized_state, "category": "routing_state"}
    if index + 1 < len(chain):
        next_profile = chain[index + 1]
        if next_profile in set(attempted_profiles or []):
            return {"action": "fail", "state": normalized_state, "category": "routing_attempt_repeated"}
        return {"action": "fallback", "state": normalized_state, "category": category, "next_profile": next_profile}
    return {"action": "fail", "state": normalized_state, "category": f"{category}_chain_exhausted"}


def routing_state_path(root: Path, run_id: str) -> Path:
    return artifact_path(root, run_id, "routing-state.json")


def update_routing_state(root: Path, run_id: str, **updates: Any) -> dict[str, Any]:
    path = routing_state_path(root, run_id)
    state = read_json(path) if path.is_file() else {"schema_version": 1, "run_id": run_id, "attempts": []}
    state.update(updates)
    atomic_json(path, state)
    return state


def validate_routing_launch_authorization(
    state: dict[str, Any], mode: str, profile: str, internal_fallback: bool,
) -> None:
    if internal_fallback:
        authorized = (
            state.get("status") == "FALLBACK_STARTING"
            and state.get("next_profile") == profile
            and state.get("mode") == mode
        )
        if not authorized:
            raise ValueError("internal fallback launch requires Supervisor authorization in routing state")
        return
    if state and state.get("mode") == mode and state.get("status") != "REWORK_READY":
        raise ValueError("a routing cycle already exists for this role; only its Supervisor may advance profiles")


def latest_named_agent(executable: str, worktree: Path, name: str) -> dict[str, Any] | None:
    code, output = run([executable, "agents", "--json", "--all", "--cwd", str(worktree)], worktree, timeout=30)
    if code:
        raise ValueError("Claude Agent status failed during supervision")
    try:
        agents = json.loads(output or "[]")
    except json.JSONDecodeError as error:
        raise ValueError("Claude Agent status returned invalid JSON during supervision") from error
    if not isinstance(agents, list):
        raise ValueError("Claude Agent status returned an invalid payload during supervision")
    matches = [item for item in agents if isinstance(item, dict) and item.get("name") == name]
    return max(matches, key=lambda item: int(item.get("startedAt") or 0)) if matches else None


def active_routed_agents(executable: str, worktree: Path, run_id: str) -> list[dict[str, Any]]:
    code, output = run([executable, "agents", "--json", "--all", "--cwd", str(worktree)], worktree, timeout=30)
    if code:
        raise ValueError("Claude Agent status failed before launch; refusing a second writer")
    try:
        agents = json.loads(output or "[]")
    except json.JSONDecodeError as error:
        raise ValueError("Claude Agent status returned invalid JSON before launch; refusing a second writer") from error
    if not isinstance(agents, list):
        raise ValueError("Claude Agent status returned an invalid payload before launch; refusing a second writer")
    return [
        item for item in agents
        if isinstance(item, dict)
        and str(item.get("state") or "").lower() not in {"done", "failed", "stopped"}
    ]


@contextmanager
def claude_launch_mutex(root: Path, worktree: Path):
    """Serialize the status-check plus launch critical section for one worktree."""
    runtime = os_dir(root) / "runtime" / "claude-launch-locks"
    runtime.mkdir(parents=True, exist_ok=True)
    worktree_key = hashlib.sha256(str(worktree.expanduser().resolve()).encode("utf-8")).hexdigest()[:24]
    path = runtime / f"{worktree_key}.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another Claude launch is already in progress for this Run") from error
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "locked_at": now_iso()}))
        handle.flush()
        yield path
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def parse_agent_activity(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, timezone.utc).astimezone()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        except ValueError:
            return None
    return None


def safe_agent_status(agent: dict[str, Any]) -> tuple[str, datetime | None]:
    detail = str(agent.get("detail") or "")
    activity_at = parse_agent_activity(agent.get("updatedAt") or agent.get("startedAt"))
    identifier = str(agent.get("id") or "")
    if identifier and len(identifier) <= 16:
        job = Path("~/.claude/jobs").expanduser() / identifier / "state.json"
        if job.is_file():
            try:
                value = read_json(job)
                detail = str(value.get("detail") or detail)
                activity_at = parse_agent_activity(value.get("updatedAt")) or activity_at
            except (OSError, ValueError, json.JSONDecodeError):
                pass
    return detail, activity_at


def mark_runtime_failed(root: Path, run_id: str, category: str) -> None:
    with db_connect(root) as db:
        row = active_run(db, run_id)
        db.execute("UPDATE runs SET status='RUNTIME_FAILED', ended_at=? WHERE id=?", (now_iso(), run_id))
        db.execute("UPDATE work_packages SET status='RUNTIME_FAILED', updated_at=? WHERE id=?", (now_iso(), row["package_id"]))
    record_failure(
        root, run_id, "BUILDING", "runtime", "new-authority-required",
        f"Claude execution could not continue after finite provider fallback: {category}",
        "The authorized fallback chain is exhausted or the local execution environment is unavailable.",
        [str(routing_state_path(root, run_id))],
    )
    update_routing_state(root, run_id, status="RUNTIME_FAILED", terminal_category=category, ended_at=now_iso())
    append_event(root, run_id, "system", "routing_failed", "Finite model fallback could not continue", category=category)


def start_route_supervisor(root: Path, run_id: str, profile: str, config_path: Path) -> int:
    runtime = run_dir(root, run_id) / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = runtime / "route-supervisor.log"
    command = [
        sys.executable, str(Path(__file__).resolve()), "claude-watch", str(root), "--run", run_id,
        "--profile", profile, "--routing-config", str(config_path),
    ]
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    update_routing_state(root, run_id, supervisor_pid=process.pid, supervisor_log=str(log_path))
    return process.pid


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], cwd: Path, timeout: int = 300, env: dict[str, str] | None = None) -> tuple[int, str]:
    completed = subprocess.run(
        command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout, check=False,
    )
    return completed.returncode, completed.stdout.rstrip()


def verification_shell() -> str:
    configured = os.environ.get("AGENT_OS_SHELL")
    if configured:
        candidate = Path(configured).expanduser() if "/" in configured else Path(shutil.which(configured) or "")
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        raise FileNotFoundError(f"AGENT_OS_SHELL is not executable: {configured}")
    executable = shutil.which("sh")
    if not executable:
        raise FileNotFoundError("POSIX sh executable not found; set AGENT_OS_SHELL explicitly")
    return executable


def git(repo: Path, *args: str) -> str:
    code, output = run(["git", "-C", str(repo), *args], repo)
    if code:
        raise ValueError(f"git {' '.join(args)} failed in {repo}: {output}")
    return output.strip()


def root_path(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project root does not exist: {root}")
    adapter = root / ".agent-os" / "project.json"
    if adapter.is_file():
        config = read_json(adapter)
        if config.get("adapter") and config.get("control_root"):
            control_root = Path(str(config["control_root"])).expanduser().resolve()
            if not control_root.is_dir():
                raise FileNotFoundError(f"adapter control root does not exist: {control_root}")
            return control_root
    return root


def find_runtime_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        config = candidate / ".agent-os" / "project.json"
        if config.is_file():
            value = read_json(config).get("control_root")
            return Path(str(value)).expanduser().resolve() if value else candidate
    raise FileNotFoundError("no .agent-os/project.json found from current directory")


def os_dir(root: Path) -> Path:
    return root / ".agent-os"


def db_connect(root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(os_dir(root) / "state.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db(root: Path, allow_migration: bool = False) -> None:
    db_path = os_dir(root) / "state.db"
    existed = db_path.is_file()
    if existed:
        with db_connect(root) as probe:
            user_version = int(probe.execute("PRAGMA user_version").fetchone()[0])
        if user_version < SCHEMA_REVISION and not allow_migration:
            raise ValueError(f"Agent OS database requires explicit upgrade: agent-os upgrade {root}")
    with db_connect(root) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS work_packages(
              id TEXT PRIMARY KEY, work_unit TEXT NOT NULL, status TEXT NOT NULL,
              owner TEXT NOT NULL, reviewer TEXT NOT NULL, contract_path TEXT NOT NULL,
              current_run TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY, package_id TEXT NOT NULL, status TEXT NOT NULL,
              owner TEXT NOT NULL, worktree TEXT NOT NULL, branch TEXT NOT NULL,
              baseline_commit TEXT NOT NULL, branch_commit TEXT, evidence_status TEXT,
              started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, ended_at TEXT,
              merge_commit TEXT, rollback_commit TEXT, maturity_status TEXT,
              governance_level TEXT, outcome_status TEXT, economics_status TEXT,
              FOREIGN KEY(package_id) REFERENCES work_packages(id));
            CREATE TABLE IF NOT EXISTS locks(
              work_unit TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner TEXT NOT NULL,
              worktree TEXT NOT NULL, acquired_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL,
              expires_at TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(id));
            CREATE TABLE IF NOT EXISTS reviews(
              id TEXT PRIMARY KEY, package_id TEXT NOT NULL, run_id TEXT NOT NULL,
              decision TEXT NOT NULL, branch_commit TEXT NOT NULL,
              evidence_sha256 TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS failures(
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL, stage TEXT NOT NULL,
              category TEXT NOT NULL, blocker_class TEXT NOT NULL, status TEXT NOT NULL,
              root_cause TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT,
              FOREIGN KEY(run_id) REFERENCES runs(id));
            CREATE TABLE IF NOT EXISTS improvements(
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL, status TEXT NOT NULL,
              risk TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY(run_id) REFERENCES runs(id));
            CREATE TABLE IF NOT EXISTS outcomes(
              run_id TEXT PRIMARY KEY, status TEXT NOT NULL, path TEXT NOT NULL,
              recorded_at TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(id));
            CREATE TABLE IF NOT EXISTS schema_migrations(
              version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL);
            """
        )
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(runs)").fetchall()}
        for name in (
            "merge_commit", "rollback_commit", "maturity_status",
            "governance_level", "outcome_status", "economics_status",
        ):
            if name not in columns:
                db.execute(f"ALTER TABLE runs ADD COLUMN {name} TEXT")
        db.execute("UPDATE runs SET governance_level='L2' WHERE governance_level IS NULL OR governance_level='' ")
        db.execute("UPDATE runs SET outcome_status='LEGACY' WHERE outcome_status IS NULL OR outcome_status='' ")
        db.execute("UPDATE runs SET economics_status='NOT_RECORDED' WHERE economics_status IS NULL OR economics_status='' ")
        if not existed or allow_migration:
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations VALUES(?,?,?)",
                (SCHEMA_REVISION, now_iso(), "agent-os-v0.4-proportional-outcomes-economics"),
            )
            db.execute(f"PRAGMA user_version = {SCHEMA_REVISION}")


def run_dir(root: Path, run_id: str) -> Path:
    return os_dir(root) / "runs" / run_id


def artifact_path(root: Path, run_id: str, filename: str) -> Path:
    return run_dir(root, run_id) / filename


def write_run_artifact(root: Path, run_id: str, filename: str, value: dict[str, Any]) -> Path:
    value = {"agent_os_version": AGENT_OS_VERSION, "run_id": run_id, **value}
    target = artifact_path(root, run_id, filename)
    atomic_json(target, value)
    return target


def safe_split(value: str) -> tuple[str, str]:
    left, separator, right = value.partition("::")
    if not separator or not left.strip() or not right.strip():
        raise ValueError("expected OPTION::REASON")
    return left.strip(), right.strip()


def contract_digest(contract: dict[str, Any]) -> str:
    stable = {key: value for key, value in contract.items() if key != "approved_at"}
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def governance_level(contract: dict[str, Any]) -> str:
    if int(contract.get("schema_revision", 1)) < 4:
        return "L2"
    level = str(contract.get("governance", {}).get("level", ""))
    if level not in GOVERNANCE_LEVELS:
        raise ValueError(f"invalid governance level: {level or 'missing'}")
    return level


def challenge_path(root: Path, package_id: str) -> Path:
    return os_dir(root) / "challenges" / f"{package_id}.json"


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def hashed_evidence(root: Path, value: str) -> dict[str, Any]:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"evidence file does not exist: {value}")
    try:
        reference = str(path.relative_to(root))
        location = "project"
    except ValueError:
        reference = path.name
        location = "external-user-provided"
    return {
        "reference": reference, "location": location, "sha256": sha256(path),
        "size_bytes": path.stat().st_size, "level": "verified",
    }


def append_event(root: Path, run_id: str | None, actor: str, event: str, summary: str, **extra: Any) -> None:
    record = {"timestamp": now_iso(), "actor": actor, "event": event, "summary": summary}
    record.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    target = os_dir(root) / "events.jsonl" if not run_id else os_dir(root) / "runs" / run_id / "events.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def shift_config(root: Path) -> dict[str, Any]:
    return read_json(root / ".agent-shift" / "project.json")


def work_unit(root: Path, unit_id: str) -> dict[str, Any]:
    for unit in shift_config(root).get("work_units", []):
        if unit.get("id") == unit_id:
            return unit
    raise ValueError(f"unknown work unit: {unit_id}")


def repo_root(root: Path, unit: dict[str, Any]) -> Path:
    return (root / str(unit["repo_root"])).resolve()


def package_path(root: Path, package_id: str) -> Path:
    return os_dir(root) / "work-packages" / f"{package_id}.json"


def load_package(root: Path, package_id: str) -> dict[str, Any]:
    return read_json(package_path(root, package_id))


def active_run(db: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        raise ValueError(f"unknown run: {run_id}")
    return row


def call_agent_shift(root: Path, *args: str) -> tuple[int, str]:
    configured = os.environ.get("AGENT_SHIFT_EXECUTABLE")
    executable = configured or shutil.which("agent-shift")
    if not executable:
        raise FileNotFoundError("agent-shift executable not found")
    return run([executable, *args], root, timeout=600)


def cmd_init(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    if not (root / ".agent-shift" / "project.json").is_file():
        raise ValueError("Agent Shift must be initialized first")
    target = os_dir(root)
    for relative in ("policy", "work-packages", "runs", "reviews", "improvements", "challenges", "outcomes", "runtime"):
        (target / relative).mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    project_file = target / "project.json"
    if not project_file.exists():
        atomic_json(project_file, {
            "agent_os_version": AGENT_OS_VERSION,
            "schema_revision": SCHEMA_REVISION,
            "id": args.id, "name": args.name, "mission": args.mission,
            "control_root": str(root),
            "work_units_source": ".agent-shift/project.json",
            "protected_paths": [".agent-os", ".agent-shift", ".githooks", ".claude/settings.json", "AGENTS.md", "CLAUDE.md", "secrets"],
            "high_risk_operations": ["deploy", "publish", "credential_access", "private_data", "database_migration", "data_deletion", "destructive_git", "push"],
            "lock_ttl_seconds": DEFAULT_LOCK_SECONDS,
            "default_governance_level": "L1",
        })
        created.append(str(project_file.relative_to(root)))
    policy = target / "policy" / "evidence-review.json"
    if not policy.exists():
        atomic_json(policy, {
            "agent_os_version": AGENT_OS_VERSION,
            "evidence_levels": ["verified", "reviewed", "observed", "assumed"],
            "acceptance_requires_by_level": {
                "L0": ["evidence_manifest_pass", "verifier_pass", "exact_commit_match", "no_unresolved_failures", "merge_gate_pass", "codex_review"],
                "L1": ["evidence_manifest_pass", "verifier_pass", "exact_commit_match", "no_unresolved_failures", "outcome_contract", "merge_gate_pass", "codex_review"],
                "L2": ["evidence_manifest_pass", "verifier_pass", "exact_commit_match", "no_unresolved_failures", "director_challenge_pass", "learning_assessment", "five_question_maturity_pass", "outcome_contract", "merge_gate_pass", "codex_review"],
            },
            "max_rework_rounds": 3,
            "legacy_runs_count_toward_v04": False,
        })
        created.append(str(policy.relative_to(root)))
    director_policy = target / "policy" / "director-principles.json"
    if not director_policy.exists():
        source = Path(__file__).resolve().parents[1] / "assets" / "director-principles.json"
        director_policy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        created.append(str(director_policy.relative_to(root)))
    maturity_policy = target / "policy" / "five-question-maturity.json"
    if not maturity_policy.exists():
        source = Path(__file__).resolve().parents[1] / "assets" / "five-question-maturity.json"
        maturity_policy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        created.append(str(maturity_policy.relative_to(root)))
    proportional_policy = target / "policy" / "proportional-governance.json"
    if not proportional_policy.exists():
        source = Path(__file__).resolve().parents[1] / "assets" / "proportional-governance.json"
        proportional_policy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        created.append(str(proportional_policy.relative_to(root)))
    claude = root / ".claude"
    (claude / "agents").mkdir(parents=True, exist_ok=True)
    settings = claude / "settings.json"
    if not settings.exists():
        atomic_json(settings, {"hooks": {
            "PreToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash", "hooks": [{"type": "command", "command": "agent-os hook pre"}]}],
            "PostToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash", "hooks": [{"type": "command", "command": "agent-os hook post"}]}],
            "PostToolUseFailure": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash", "hooks": [{"type": "command", "command": "agent-os hook failure"}]}],
            "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "agent-os hook stop"}]}],
        }})
        created.append(str(settings.relative_to(root)))
    verifier = claude / "agents" / "verifier.md"
    if not verifier.exists():
        source = Path(__file__).resolve().parents[1] / "assets" / "verifier.md"
        verifier.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        created.append(str(verifier.relative_to(root)))
    init_db(root)
    append_event(root, None, "system", "initialized", f"Agent OS initialized for {args.id}")
    print(json.dumps({"project": str(root), "created": created, "preserved_existing": True}, ensure_ascii=False, indent=2))
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    requested = Path(args.project).expanduser().resolve()
    root = root_path(args.project)
    config_path = os_dir(root) / "project.json"
    config = read_json(config_path)
    source_version = str(config.get("agent_os_version", "0.2"))
    if source_version not in {"0.2", "0.3", AGENT_OS_VERSION}:
        raise ValueError(f"unsupported Agent OS upgrade source: {source_version}")
    backup: str | None = None
    db_path = os_dir(root) / "state.db"
    database_version = 0
    if db_path.is_file():
        with db_connect(root) as db:
            database_version = int(db.execute("PRAGMA user_version").fetchone()[0])
            active_locks = int(db.execute("SELECT COUNT(*) FROM locks").fetchone()[0])
            if active_locks:
                raise ValueError(f"upgrade requires no active writer locks; found {active_locks}")
    already_upgraded = source_version == AGENT_OS_VERSION and database_version >= SCHEMA_REVISION
    if not already_upgraded and db_path.is_file():
        migration_dir = os_dir(root) / "runtime" / "migrations"
        migration_dir.mkdir(parents=True, exist_ok=True)
        backup_path = migration_dir / f"state.db.v{source_version}-{now().strftime('%Y%m%dT%H%M%S')}.bak"
        with db_connect(root) as source_db, sqlite3.connect(backup_path) as backup_db:
            source_db.backup(backup_db)
        backup = str(backup_path)
    init_db(root, allow_migration=True)
    for relative in ("challenges", "outcomes"):
        (os_dir(root) / relative).mkdir(parents=True, exist_ok=True)
    with db_connect(root) as db:
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise ValueError(f"database migration validation failed: integrity={integrity}, foreign_keys={len(foreign_keys)}")
    maturity_policy = os_dir(root) / "policy" / "five-question-maturity.json"
    if not maturity_policy.exists():
        source = Path(__file__).resolve().parents[1] / "assets" / "five-question-maturity.json"
        maturity_policy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        maturity = read_json(maturity_policy)
        maturity["agent_os_version"] = AGENT_OS_VERSION
        maturity["required_governance_level"] = "L2"
        atomic_json(maturity_policy, maturity)
    director_policy = os_dir(root) / "policy" / "director-principles.json"
    if director_policy.is_file():
        director = read_json(director_policy)
        director["version"] = max(2, int(director.get("version", 1)))
        review_requires = list(director.get("review_requires", []))
        for item in ("governance level proportional to risk", "outcome contract for L1 and L2"):
            if item not in review_requires:
                review_requires.append(item)
        director["review_requires"] = review_requires
        atomic_json(director_policy, director)
    proportional_policy = os_dir(root) / "policy" / "proportional-governance.json"
    if not proportional_policy.exists():
        source = Path(__file__).resolve().parents[1] / "assets" / "proportional-governance.json"
        proportional_policy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    evidence_policy = os_dir(root) / "policy" / "evidence-review.json"
    evidence = read_json(evidence_policy)
    evidence["agent_os_version"] = AGENT_OS_VERSION
    evidence.pop("acceptance_requires", None)
    evidence["acceptance_requires_by_level"] = {
        "L0": ["evidence_manifest_pass", "verifier_pass", "exact_commit_match", "no_unresolved_failures", "merge_gate_pass", "codex_review"],
        "L1": ["evidence_manifest_pass", "verifier_pass", "exact_commit_match", "no_unresolved_failures", "outcome_contract", "merge_gate_pass", "codex_review"],
        "L2": ["evidence_manifest_pass", "verifier_pass", "exact_commit_match", "no_unresolved_failures", "director_challenge_pass", "learning_assessment", "five_question_maturity_pass", "outcome_contract", "merge_gate_pass", "codex_review"],
    }
    evidence.pop("legacy_runs_count_toward_v02", None)
    evidence.pop("legacy_runs_count_toward_v03", None)
    evidence["legacy_runs_count_toward_v04"] = False
    atomic_json(evidence_policy, evidence)
    config["agent_os_version"] = AGENT_OS_VERSION
    config["schema_revision"] = SCHEMA_REVISION
    config.setdefault("default_governance_level", "L1")
    atomic_json(config_path, config)
    adapters: list[str] = []
    shift = shift_config(root)
    for unit in shift.get("work_units", []):
        candidate = repo_root(root, unit) / ".agent-os" / "project.json"
        if candidate == config_path or not candidate.is_file():
            continue
        adapter = read_json(candidate)
        if adapter.get("adapter") and Path(str(adapter.get("control_root", ""))).expanduser().resolve() == root:
            adapter["agent_os_version"] = AGENT_OS_VERSION
            adapter["schema_revision"] = SCHEMA_REVISION
            atomic_json(candidate, adapter)
            adapters.append(str(candidate))
    append_event(root, None, "codex", "upgraded", f"Agent OS {source_version} -> {AGENT_OS_VERSION}", backup=backup)
    print(json.dumps({
        "project": str(root), "requested_path": str(requested), "from": source_version,
        "to": AGENT_OS_VERSION, "schema_revision": SCHEMA_REVISION,
        "database_backup": backup, "adapters_updated": adapters,
        "idempotent": already_upgraded,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_package_create(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    if package_path(root, args.id).exists():
        raise ValueError(f"work package already exists: {args.id}")
    unit = work_unit(root, args.work_unit)
    allow = args.allow or [str(value) for value in unit.get("implementation_paths", [])]
    verify = args.verify or [str(value) for value in unit.get("verify_commands", [])]
    level = args.governance_level
    if level not in GOVERNANCE_LEVELS:
        raise ValueError(f"unsupported governance level: {level}")
    mission_alignment = args.mission_alignment or ("Low-risk repository-local maintenance" if level == "L0" else "")
    objective = args.objective or (args.goal if level == "L0" else "")
    priority = args.priority or ("P2" if level == "L0" else "")
    selected_approach = args.selected_approach or ("Make the smallest reversible change inside the declared scope" if level == "L0" else "")
    rationale = args.rationale or ("L0 work is local, reversible, mechanically verified, and has no external side effects" if level == "L0" else "")
    if level == "L0":
        outcome_contract = {
            "mode": "delivery", "required_post_merge": False,
            "metric": "exact-commit delivery acceptance", "baseline": "not accepted",
            "target": args.expected_gain, "validation_window": "at Codex review",
            "evidence_source": "Evidence Manifest, Mechanical Verifier, and Codex Review",
        }
    else:
        outcome_contract = {
            "mode": "post-merge", "required_post_merge": True,
            "metric": args.outcome_metric, "baseline": args.outcome_baseline,
            "target": args.outcome_target, "validation_window": args.outcome_validation_window,
            "evidence_source": args.outcome_evidence_source,
        }
    contract = {
        "agent_os_version": AGENT_OS_VERSION, "schema_revision": SCHEMA_REVISION, "id": args.id,
        "project_id": read_json(os_dir(root) / "project.json")["id"],
        "work_unit": args.work_unit, "repo_root": str(unit["repo_root"]),
        "goal": args.goal, "objective": objective, "assumptions": args.assumption,
        "governance": {"level": level, "risk_factors": args.risk_factor},
        "director_context": {
            "mission_alignment": mission_alignment,
            "priority": priority,
            "expected_gain": args.expected_gain,
            "external_signals": args.external_signal,
            "frontline_signals": args.frontline_signal,
            "first_principles": args.first_principles,
        },
        "decision": {
            "selected_approach": selected_approach,
            "rationale": rationale,
            "alternatives_rejected": [
                {"option": option, "reason": reason}
                for option, reason in (safe_split(value) for value in args.alternative)
            ],
            "key_tradeoffs": args.tradeoff,
        },
        "scope": {"allow": allow, "deny": args.deny},
        "recovery": {
            "external_side_effects": args.external_side_effect,
            "rollback_verification": args.rollback_check or verify,
        },
        "outcome_contract": outcome_contract,
        "owner": {"role": "engineering-builder", "runtime": "claude-code"},
        "reviewer": {"role": "product-technical-director", "runtime": "codex"},
        "verifier": {"role": "independent-verifier", "runtime": "codex-subagent-or-claude-verifier"},
        "constraints": args.constraint,
        "success_criteria": {"verified": args.verified, "reviewed": args.reviewed, "observed": args.observed},
        "verify_commands": verify, "stop_conditions": args.stop,
        "budget": {"max_runs": args.max_runs, "max_rework_rounds": args.max_rework, "max_parallel_writers": 1},
        "created_at": now_iso(), "approved_at": None,
    }
    atomic_json(package_path(root, args.id), contract)
    init_db(root)
    with db_connect(root) as db:
        timestamp = now_iso()
        db.execute("INSERT INTO work_packages VALUES(?,?,?,?,?,?,?,?,?)", (
            args.id, args.work_unit, "DRAFT", "claude", "codex",
            str(package_path(root, args.id)), None, timestamp, timestamp,
        ))
    append_event(root, None, "codex", "package_created", f"Created {args.id}", work_unit=args.work_unit)
    print(str(package_path(root, args.id)))
    return 0


def validate_contract(root: Path, contract: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key in ("id", "work_unit", "goal", "objective", "scope", "owner", "reviewer", "success_criteria", "stop_conditions", "budget"):
        if not contract.get(key):
            problems.append(f"missing {key}")
    try:
        unit = work_unit(root, str(contract.get("work_unit")))
        allowed = [str(value) for value in unit.get("implementation_paths", [])]
        for path in contract.get("scope", {}).get("allow", []):
            if not any(path == item or path.startswith(item.rstrip("/") + "/") for item in allowed):
                problems.append(f"allow path outside work-unit implementation paths: {path}")
    except ValueError as error:
        problems.append(str(error))
    if int(contract.get("budget", {}).get("max_parallel_writers", 0)) != 1:
        problems.append("Phase 0 requires max_parallel_writers=1")
    revision = int(contract.get("schema_revision", 1))
    if revision >= 2:
        context = contract.get("director_context", {})
        for key in ("mission_alignment", "priority", "expected_gain", "external_signals", "frontline_signals", "first_principles"):
            if key not in context:
                problems.append(f"missing director_context.{key}")
        if context.get("priority") not in {"P0", "P1", "P2", "P3"}:
            problems.append("director_context.priority must be P0, P1, P2, or P3")
        for key in ("mission_alignment", "expected_gain"):
            if not str(context.get(key, "")).strip():
                problems.append(f"director_context.{key} must not be empty")
    if revision >= 3:
        decision = contract.get("decision", {})
        for key in ("selected_approach", "rationale"):
            if not str(decision.get(key, "")).strip():
                problems.append(f"decision.{key} must not be empty")
        if "alternatives_rejected" not in decision or "key_tradeoffs" not in decision:
            problems.append("decision must include alternatives_rejected and key_tradeoffs")
        recovery = contract.get("recovery", {})
        if "external_side_effects" not in recovery or "rollback_verification" not in recovery:
            problems.append("recovery must declare external_side_effects and rollback_verification")
    if revision >= 4:
        try:
            level = governance_level(contract)
        except ValueError as error:
            problems.append(str(error))
            level = ""
        risk_factors = contract.get("governance", {}).get("risk_factors", [])
        if not isinstance(risk_factors, list):
            problems.append("governance.risk_factors must be a list")
            risk_factors = []
        external = contract.get("recovery", {}).get("external_side_effects", [])
        if level == "L0" and (risk_factors or external):
            problems.append("L0 forbids declared risk factors and external side effects; use L1 or L2")
        if external and level != "L2":
            problems.append("external side effects require L2 governance")
        high_risk = sorted({str(value) for value in risk_factors} & L2_RISK_FACTORS)
        if high_risk and level != "L2":
            problems.append("risk factors require L2 governance: " + ", ".join(high_risk))
        if level in {"L1", "L2"}:
            context = contract.get("director_context", {})
            decision = contract.get("decision", {})
            for key in ("mission_alignment", "priority"):
                if not str(context.get(key, "")).strip():
                    problems.append(f"{level} requires director_context.{key}")
            for key in ("selected_approach", "rationale"):
                if not str(decision.get(key, "")).strip():
                    problems.append(f"{level} requires decision.{key}")
        if level == "L2":
            if not contract.get("director_context", {}).get("first_principles"):
                problems.append("L2 requires at least one first-principles statement")
            if not contract.get("decision", {}).get("alternatives_rejected"):
                problems.append("L2 requires at least one rejected alternative")
            if not contract.get("decision", {}).get("key_tradeoffs"):
                problems.append("L2 requires at least one explicit tradeoff")
            if not contract.get("recovery", {}).get("rollback_verification"):
                problems.append("L2 requires rollback verification")
        outcome = contract.get("outcome_contract", {})
        expected_mode = "delivery" if level == "L0" else "post-merge"
        if outcome.get("mode") != expected_mode:
            problems.append(f"{level} outcome_contract.mode must be {expected_mode}")
        for key in ("metric", "baseline", "target", "validation_window", "evidence_source"):
            value = outcome.get(key)
            if value is None or not str(value).strip():
                problems.append(f"outcome_contract.{key} must not be empty")
    return problems


def cmd_challenge_record(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    contract = load_package(root, args.package)
    if governance_level(contract) != "L2":
        raise ValueError("director-challenge is required only for L2 packages")
    if args.reviewer.strip().lower() in {"codex", "codex-main", "director"}:
        raise ValueError("L2 Director Challenge reviewer must be independent from Codex main")
    with db_connect(root) as db:
        row = db.execute("SELECT status FROM work_packages WHERE id=?", (args.package,)).fetchone()
    if not row or row["status"] != "DRAFT":
        raise ValueError("director-challenge requires a DRAFT package")
    path = challenge_path(root, args.package)
    document = read_json(path) if path.is_file() else {
        "agent_os_version": AGENT_OS_VERSION, "work_package": args.package, "reviews": [],
    }
    review = {
        "round": len(document.get("reviews", [])) + 1,
        "reviewer": args.reviewer, "decision": args.decision,
        "summary": args.summary, "findings": args.finding,
        "contract_digest": contract_digest(contract),
        "evidence": hashed_evidence(root, args.review_file),
        "reviewed_at": now_iso(),
    }
    document.setdefault("reviews", []).append(review)
    document["latest"] = review
    atomic_json(path, document)
    append_event(root, None, args.reviewer, "director_challenge", f"{args.decision} {args.package}", package=args.package)
    print(json.dumps(review, ensure_ascii=False, indent=2))
    return 0


def cmd_package_ready(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    contract = load_package(root, args.id)
    problems = validate_contract(root, contract)
    if problems:
        raise ValueError("invalid work package: " + "; ".join(problems))
    if int(contract.get("schema_revision", 1)) >= 4 and governance_level(contract) == "L2":
        path = challenge_path(root, args.id)
        challenge = read_json(path) if path.is_file() else {}
        latest = challenge.get("latest", {})
        if latest.get("decision") != "PASS":
            raise ValueError("L2 package-ready requires a PASS Director Challenge")
        if latest.get("contract_digest") != contract_digest(contract):
            raise ValueError("L2 Director Challenge does not match the current Work Package")
        evidence = latest.get("evidence", {})
        if not evidence.get("sha256") or evidence.get("level") != "verified":
            raise ValueError("L2 Director Challenge requires hashed review evidence")
    contract["approved_at"] = now_iso()
    atomic_json(package_path(root, args.id), contract)
    with db_connect(root) as db:
        row = db.execute("SELECT status FROM work_packages WHERE id=?", (args.id,)).fetchone()
        if not row or row["status"] != "DRAFT":
            raise ValueError("package-ready requires DRAFT")
        db.execute("UPDATE work_packages SET status='READY', updated_at=? WHERE id=?", (now_iso(), args.id))
    append_event(root, None, "codex", "package_ready", f"Approved {args.id}")
    print(f"READY {args.id}")
    return 0


def cmd_run_start(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    contract = load_package(root, args.package)
    unit_id = str(contract["work_unit"])
    unit = work_unit(root, unit_id)
    repo = repo_root(root, unit)
    init_db(root)
    with db_connect(root) as db:
        package_row = db.execute("SELECT * FROM work_packages WHERE id=?", (args.package,)).fetchone()
        if not package_row or package_row["status"] != "READY":
            raise ValueError("run-start requires READY package")
        if db.execute("SELECT 1 FROM locks WHERE work_unit=?", (unit_id,)).fetchone():
            raise ValueError(f"work unit already locked: {unit_id}")
        if db.execute("SELECT 1 FROM runs WHERE id=?", (args.run,)).fetchone():
            raise ValueError(f"run already exists: {args.run}")
    run_dir = os_dir(root) / "runs" / args.run
    if run_dir.exists():
        raise ValueError(f"run directory already exists: {run_dir}")
    if git(repo, "status", "--porcelain"):
        raise ValueError(f"base worktree is dirty: {repo}")
    control_git_code, _ = run(["git", "rev-parse", "--verify", "HEAD"], root, timeout=30)
    if root != repo and control_git_code == 0 and git(root, "status", "--porcelain"):
        raise ValueError(f"control worktree is dirty; commit the approved Work Package first: {root}")
    code, output = call_agent_shift(root, "baseline", str(root), "--work-unit", unit_id)
    if code:
        raise ValueError(output)
    shift_state = read_json(root / ".agent-shift" / "state.json")
    if shift_state.get("status") in {"ACCEPTED", "ROLLED_BACK"}:
        code, output = call_agent_shift(root, "transition", str(root), "SCOPED", "--work-unit", unit_id, "--work-package", args.package, "--note", f"Agent OS scoped {args.package}")
        if code:
            raise ValueError(output)
    elif shift_state.get("status") != "SCOPED":
        raise ValueError(f"Agent Shift must be SCOPED or ACCEPTED before a new Run, found {shift_state.get('status')}")
    code, output = call_agent_shift(root, "worktree-create", str(root), "--work-unit", unit_id, "--handoff-id", args.run, "--agent", args.agent)
    if code:
        raise ValueError(output)
    created = json.loads(output)
    worktree = str(created["worktree"])
    branch = str(created["branch"])
    baseline = str(created["baseline_commit"])
    (run_dir / "evidence").mkdir(parents=True, exist_ok=False)
    context = {
        "agent_os_version": AGENT_OS_VERSION, "id": f"ctx-{args.run}",
        "run_id": args.run, "work_package": args.package,
        "baseline_commit": baseline, "branch": branch, "worktree": worktree,
        "generated_at": now_iso(),
        "sources": ["AGENTS.md", "CLAUDE.md", ".agent-shift/project.json", str(package_path(root, args.package))],
        "source_hashes": {str(package_path(root, args.package)): sha256(package_path(root, args.package))},
    }
    atomic_json(run_dir / "context.json", context)
    project = read_json(os_dir(root) / "project.json")
    decision = contract.get("decision", {})
    write_run_artifact(root, args.run, "decision-trace.json", {
        "work_package": args.package,
        "selected_approach": decision.get("selected_approach"),
        "rationale": decision.get("rationale"),
        "alternatives_rejected": decision.get("alternatives_rejected", []),
        "key_tradeoffs": decision.get("key_tradeoffs", []),
        "first_principles": contract.get("director_context", {}).get("first_principles", []),
        "actor": "codex", "created_at": now_iso(),
    })
    write_run_artifact(root, args.run, "permission-manifest.json", {
        "work_package": args.package, "owner": args.agent,
        "work_unit": unit_id, "worktree": worktree, "branch": branch,
        "granted_paths": contract.get("scope", {}).get("allow", []),
        "denied_paths": list(dict.fromkeys([
            *contract.get("scope", {}).get("deny", []),
            *project.get("protected_paths", []), *unit.get("director_owned_paths", []),
        ])),
        "granted_actions": ["read", "edit-authorized-paths", "agent-branch-commit", "verify", "heartbeat"],
        "denied_actions": project.get("high_risk_operations", []),
        "lock": {"exclusive": True, "ttl_seconds": int(project.get("lock_ttl_seconds", DEFAULT_LOCK_SECONDS))},
        "authority_source": str(package_path(root, args.package)), "created_at": now_iso(),
    })
    recovery = contract.get("recovery", {})
    write_run_artifact(root, args.run, "rollback-plan.json", {
        "work_package": args.package, "baseline_commit": baseline,
        "base_branch": unit.get("git_policy", {}).get("baseline_branch", "main"),
        "strategy": "git-revert-merge-commit", "destructive_reset_allowed": False,
        "requires_explicit_execute": True, "requires_reason": True,
        "external_side_effects": recovery.get("external_side_effects", []),
        "rollback_verification": recovery.get("rollback_verification", []),
        "steps": [
            "confirm the recorded merge commit is the clean base branch HEAD",
            "create a revert commit for the recorded merge commit",
            "run rollback verification and save full logs",
            "write rollback receipt and refresh Agent Shift baseline",
        ],
        "created_at": now_iso(),
    })
    write_run_artifact(root, args.run, "outcome-contract.json", {
        "work_package": args.package,
        "governance_level": governance_level(contract),
        "contract": contract.get("outcome_contract", {}),
        "work_package_digest": contract_digest(contract),
        "created_at": now_iso(),
    })
    if int(contract.get("schema_revision", 1)) >= 4 and governance_level(contract) == "L2":
        challenge = read_json(challenge_path(root, args.package))
        write_run_artifact(root, args.run, "director-challenge.json", {
            "work_package": args.package, "latest": challenge.get("latest"),
            "source_sha256": sha256(challenge_path(root, args.package)),
            "created_at": now_iso(),
        })
    timestamp = now_iso()
    expires = (now() + timedelta(seconds=int(read_json(os_dir(root) / "project.json").get("lock_ttl_seconds", DEFAULT_LOCK_SECONDS)))).isoformat(timespec="seconds")
    with db_connect(root) as db:
        db.execute("""INSERT INTO runs(
          id, package_id, status, owner, worktree, branch, baseline_commit,
          branch_commit, evidence_status, started_at, heartbeat_at, ended_at,
          merge_commit, rollback_commit, maturity_status, governance_level,
          outcome_status, economics_status)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            args.run, args.package, "BUILDING", args.agent, worktree, branch, baseline,
            None, None, timestamp, timestamp, None, None, None, "INCOMPLETE",
            governance_level(contract), "NOT_STARTED", "NOT_RECORDED",
        ))
        db.execute("INSERT INTO locks VALUES(?,?,?,?,?,?,?)", (unit_id, args.run, args.agent, worktree, timestamp, timestamp, expires))
        db.execute("UPDATE work_packages SET status='BUILDING', current_run=?, updated_at=? WHERE id=?", (args.run, timestamp, args.package))
    code, transition_output = call_agent_shift(root, "transition", str(root), "CLAUDE_IMPLEMENTING", "--handoff-id", args.run, "--work-unit", unit_id, "--work-package", args.package, "--note", f"Agent OS Run {args.run} owns implementation")
    if code:
        raise ValueError(transition_output)
    append_event(root, args.run, "codex", "run_started", f"Started {args.run}", branch=branch, baseline_commit=baseline)
    print(json.dumps(created | {"run": args.run, "package": args.package, "lock_expires_at": expires}, ensure_ascii=False, indent=2))
    return 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
        ttl = int(read_json(os_dir(root) / "project.json").get("lock_ttl_seconds", DEFAULT_LOCK_SECONDS))
        timestamp = now_iso()
        expires = (now() + timedelta(seconds=ttl)).isoformat(timespec="seconds")
        updated = db.execute("UPDATE locks SET heartbeat_at=?, expires_at=? WHERE run_id=?", (timestamp, expires, args.run)).rowcount
        if not updated:
            raise ValueError(f"no active lock for {args.run}")
        db.execute("UPDATE runs SET heartbeat_at=? WHERE id=?", (timestamp, args.run))
    append_event(root, args.run, args.actor, "heartbeat", "Run heartbeat refreshed")
    print(expires)
    return 0


def cmd_rework_start(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
        if row["status"] != "REWORK":
            raise ValueError("rework-start requires REWORK Run")
        ttl = int(read_json(os_dir(root) / "project.json").get("lock_ttl_seconds", DEFAULT_LOCK_SECONDS))
        timestamp = now_iso()
        expires = (now() + timedelta(seconds=ttl)).isoformat(timespec="seconds")
        updated = db.execute("UPDATE locks SET heartbeat_at=?, expires_at=? WHERE run_id=?", (timestamp, expires, args.run)).rowcount
        if not updated:
            raise ValueError("rework requires the existing writer lock and worktree")
        db.execute("UPDATE runs SET status='BUILDING', evidence_status=NULL, heartbeat_at=? WHERE id=?", (timestamp, args.run))
        db.execute("UPDATE work_packages SET status='BUILDING', updated_at=? WHERE id=?", (timestamp, row["package_id"]))
    code, output = call_agent_shift(root, "transition", str(root), "CLAUDE_REWORK", "--handoff-id", args.run, "--note", f"Claude rework for Agent OS Run {args.run}")
    if code:
        raise ValueError(output)
    if routing_state_path(root, args.run).is_file():
        update_routing_state(
            root, args.run, status="REWORK_READY", mode="builder", active_profile=None,
            attempts=[], next_profile=None, last_launch_failure_category=None,
        )
    append_event(root, args.run, "codex", "rework_started", "Claude owns normal review rework")
    print(f"BUILDING {args.run}")
    return 0


def claude_prompt(root: Path, run_row: sqlite3.Row) -> str:
    package_id = str(run_row["package_id"])
    run_dir = os_dir(root) / "runs" / str(run_row["id"])
    return (
        "You are the Claude Code implementation lead for an Agent OS Run. "
        f"Read {package_path(root, package_id)}, {run_dir / 'context.json'}, the repository AGENTS.md, "
        "root CLAUDE.md, and .agent-shift state before editing. Work only inside this assigned worktree "
        "and Work Package scope. Commit coherent milestones on the Agent branch. Do not merge, push, "
        "deploy, publish, read credentials, or edit governance. Do not run verification commands separately; execute "
        f"agent-os verify {shlex.quote(str(root))} --run {shlex.quote(str(run_row['id']))}. "
        "Planning is owned by Codex: do not redesign or restate the task. Within the first 120 seconds, produce "
        "a concrete code location, diagnostic command, scoped edit, or explicit BLOCKED reason. After eight "
        "task-relevant code reads without an execution action, stop reading and take an action or report the blocker. "
        "If verification passes, stop for Codex review. If a product, architecture, permission, or "
        "irreversible decision is needed, record the blocker and stop."
    )


def claude_reviewer_prompt(root: Path, run_row: sqlite3.Row) -> str:
    package_id = str(run_row["package_id"])
    evidence = os_dir(root) / "runs" / str(run_row["id"]) / "evidence"
    return (
        "You are the read-only independent Reviewer for an Agent OS Run. "
        f"Read {package_path(root, package_id)}, {evidence / 'manifest.json'}, {evidence / 'change.diff'}, "
        "the repository AGENTS.md, and root CLAUDE.md. Inspect the accepted branch commit and evidence. "
        "Do not edit files, run implementation commands, commit, merge, push, deploy, publish, read credentials, "
        "or alter governance. Return only evidence-backed findings ordered by severity, then residual risks and a "
        "PASS or CHANGES_REQUESTED recommendation. Codex remains the final decision owner."
    )


def claude_allowed_tools(mode: str) -> list[str]:
    if mode == "reviewer":
        return ["Read", "Glob", "Grep"]
    if mode == "builder":
        return [
            "Read", "Glob", "Grep", "Edit", "Write",
            "Bash(git status *)", "Bash(git diff *)", "Bash(git add *)", "Bash(git commit *)",
            "Bash(git rev-parse *)", "Bash(agent-os verify *)", "Bash(agent-os heartbeat *)",
        ]
    raise ValueError(f"unsupported Claude Agent mode: {mode}")


def cmd_provider_list(args: argparse.Namespace) -> int:
    database = Path(args.database).expanduser().resolve() if args.database else default_cc_switch_db_path()
    print(json.dumps({"database": str(database), "providers": cc_switch_providers(database)}, ensure_ascii=False, indent=2))
    return 0


def cmd_route_resolve(args: argparse.Namespace) -> int:
    config_path = Path(args.routing_config).expanduser().resolve() if args.routing_config else None
    metadata, _ = resolve_execution_profile(args.profile, config_path)
    print(json.dumps(metadata or {"profile": "inherit", "credential_source": "claude-user-settings"}, ensure_ascii=False, indent=2))
    return 0


def cmd_claude_watch(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    config_path = Path(args.routing_config).expanduser().resolve() if args.routing_config else default_routing_config_path()
    route, _ = resolve_execution_profile(args.profile, config_path)
    if route is None:
        raise ValueError("claude-watch requires a routed execution profile")
    mode = str(route.get("mode", "builder"))
    chain = fallback_chain(config_path, mode, str(route["profile"]))
    current_profile = str(route["profile"])
    executable = shutil.which("claude")
    if not executable:
        mark_runtime_failed(root, args.run, "claude_executable_missing")
        return 1
    with db_connect(root) as db:
        row = active_run(db, args.run)
    worktree = Path(str(row["worktree"]))
    config = load_routing_config(config_path)
    supervision = config.get("supervision", {}) if isinstance(config.get("supervision", {}), dict) else {}
    poll_seconds = max(2, min(int(supervision.get("poll_seconds", 10)), 60))
    discovery_deadline = time.monotonic() + max(30, int(supervision.get("discovery_timeout_seconds", 90)))
    stall_key = "builder_suspected_stall_seconds" if mode == "builder" else "reviewer_suspected_stall_seconds"
    stall_seconds = max(60, int(supervision.get(stall_key, 300 if mode == "builder" else 900)))
    watch_started = time.monotonic()
    stall_reported = False
    update_routing_state(root, args.run, status="SUPERVISING", mode=mode, chain=chain, active_profile=current_profile)
    while True:
        name = f"agent-os-{args.run}-{current_profile}"
        activity_at: datetime | None = None
        state = read_json(routing_state_path(root, args.run)) if routing_state_path(root, args.run).is_file() else {}
        attempts = [str(item.get("profile")) for item in state.get("attempts", []) if isinstance(item, dict) and item.get("profile")]
        latest_attempt = state.get("attempts", [])[-1] if state.get("attempts") else {}
        launch_failed_for_current = (
            isinstance(latest_attempt, dict)
            and latest_attempt.get("profile") == current_profile
            and latest_attempt.get("outcome") == "LAUNCH_FAILED"
        )
        if launch_failed_for_current and state.get("active_profile") == current_profile:
            decision = runtime_recovery_decision(
                "failed", None, chain, current_profile, attempts,
                failure_category=str(state.get("last_launch_failure_category") or "runtime_unknown"),
            )
        else:
            try:
                agent = latest_named_agent(executable, worktree, name)
            except (OSError, ValueError):
                agent = None
            if agent is None:
                if time.monotonic() < discovery_deadline:
                    time.sleep(poll_seconds)
                    continue
                decision = runtime_recovery_decision(
                    "failed", "background session was not discoverable", chain, current_profile, attempts,
                )
            else:
                detail, activity_at = safe_agent_status(agent)
                decision = runtime_recovery_decision(
                    str(agent.get("state") or "unknown"), detail,
                    chain, current_profile, attempts,
                )
        action = str(decision["action"])
        if action == "wait":
            inactive_seconds = (
                max(0.0, (now() - activity_at).total_seconds())
                if activity_at is not None else time.monotonic() - watch_started
            )
            if not stall_reported and inactive_seconds >= stall_seconds:
                stall_reported = True
                update_routing_state(
                    root, args.run, status="SUSPECTED_STALL", active_profile=current_profile,
                    suspected_stall_at=now_iso(), suspected_stall_seconds=stall_seconds,
                    observed_inactivity_seconds=int(inactive_seconds),
                )
                append_event(
                    root, args.run, "system", "routing_suspected_stall",
                    "Claude session is still active but has exceeded the role time threshold; no second writer was started",
                    profile=current_profile, threshold_seconds=stall_seconds,
                )
            time.sleep(poll_seconds)
            continue
        if action == "complete":
            update_routing_state(root, args.run, status="COMPLETED", active_profile=current_profile, ended_at=now_iso())
            append_event(root, args.run, "system", "routing_complete", "Claude execution completed", profile=current_profile)
            return 0
        if action == "stop":
            update_routing_state(root, args.run, status="STOPPED", active_profile=current_profile, ended_at=now_iso())
            append_event(root, args.run, "system", "routing_stopped", "Claude execution stopped; automatic fallback suppressed", profile=current_profile)
            return 0
        if action == "fail":
            mark_runtime_failed(root, args.run, str(decision.get("category", "runtime_unknown")))
            return 1
        next_profile = str(decision["next_profile"])
        append_event(
            root, args.run, "system", "routing_fallback",
            "Claude execution failed; starting the next authorized provider profile",
            from_profile=current_profile, to_profile=next_profile, category=decision.get("category"),
        )
        update_routing_state(
            root, args.run, status="FALLBACK_STARTING", active_profile=current_profile,
            last_failure_category=decision.get("category"), next_profile=next_profile,
        )
        command = [
            sys.executable, str(Path(__file__).resolve()), "claude-start", str(root), "--run", args.run,
            "--profile", next_profile, "--routing-config", str(config_path), "--no-supervisor",
        ]
        code, _ = run(command, root, timeout=90)
        if code:
            failed_state = read_json(routing_state_path(root, args.run)) if routing_state_path(root, args.run).is_file() else {}
            if failed_state.get("last_launch_failure_category") == "provider_or_quota":
                current_profile = next_profile
                watch_started = time.monotonic()
                stall_reported = False
                continue
            mark_runtime_failed(root, args.run, f"fallback_launch_failed:{next_profile}")
            return 1
        current_profile = next_profile
        discovery_deadline = time.monotonic() + max(30, int(supervision.get("discovery_timeout_seconds", 90)))
        watch_started = time.monotonic()
        stall_reported = False
        update_routing_state(root, args.run, status="SUPERVISING", active_profile=current_profile, next_profile=None)


def cmd_claude_start(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
    automatic_profile = "reviewer" if row["status"] in {"READY_FOR_REVIEW", "CODEX_REVIEWING"} else None
    config_path = Path(args.routing_config).expanduser().resolve() if args.routing_config else None
    route, provider_env = resolve_execution_profile(args.profile or automatic_profile, config_path)
    mode = str(route.get("mode", "builder")) if route else "builder"
    if mode not in {"builder", "reviewer"}:
        raise ValueError(f"unsupported execution profile mode: {mode}")
    allowed_statuses = {"BUILDING", "REWORK"} if mode == "builder" else {"READY_FOR_REVIEW", "CODEX_REVIEWING"}
    if row["status"] not in allowed_statuses:
        raise ValueError(f"claude-start {mode} profile requires {sorted(allowed_statuses)}, found {row['status']}")
    executable = shutil.which("claude")
    if not executable:
        raise FileNotFoundError("claude executable not found")
    worktree = Path(str(row["worktree"]))
    contract = load_package(root, str(row["package_id"]))
    unit = work_unit(root, str(contract["work_unit"]))
    readable_dirs = {str(os_dir(root)), str(root / ".agent-shift")}
    for source in unit.get("canonical_sources", []):
        source_path = Path(str(source)).expanduser().resolve()
        readable_dirs.add(str(source_path if source_path.is_dir() else source_path.parent))
    if mode == "builder":
        allowed_tools = claude_allowed_tools(mode)
        permission_mode = "acceptEdits"
        prompt = claude_prompt(root, row)
    else:
        allowed_tools = claude_allowed_tools(mode)
        permission_mode = "dontAsk"
        prompt = claude_reviewer_prompt(root, row)
    command = [
        executable, "--background", "--name", f"agent-os-{args.run}-{route['profile'] if route else 'inherit'}",
        "--add-dir", *sorted(readable_dirs),
        "--allowedTools", *allowed_tools,
        "--permission-mode", permission_mode,
    ]
    if route and route.get("model"):
        command.extend(["--model", str(route["model"])])
    if route and route.get("effort"):
        command.extend(["--effort", str(route["effort"])])
    command.append(prompt)
    safe_launch = {
        "run": args.run, "mode": mode, "profile": route.get("profile") if route else "inherit",
        "provider": route.get("provider") if route else None,
        "provider_id": route.get("provider_id") if route else None,
        "model": route.get("model") if route else None,
        "effort": route.get("effort") if route else None,
        "credential_source": route.get("credential_source") if route else "claude-user-settings",
        "base_url_host": route.get("base_url_host") if route else None,
        "mutates_cc_switch": False, "writes_credentials": False,
    }
    if args.dry_run:
        print(json.dumps(safe_launch | {"result": "DRY_RUN"}, ensure_ascii=False, indent=2))
        return 0
    launch_failed = False
    failure_category = "runtime_unknown"
    with claude_launch_mutex(root, worktree):
        route_state = read_json(routing_state_path(root, args.run)) if routing_state_path(root, args.run).is_file() else {}
        if route:
            validate_routing_launch_authorization(route_state, mode, str(route["profile"]), args.no_supervisor)
        active_agents = active_routed_agents(executable, worktree, args.run)
        if active_agents:
            names = sorted({str(item.get("name")) for item in active_agents})
            raise ValueError(f"an Agent OS Claude session is already active for this Run: {', '.join(names)}")
        if route:
            new_role_cycle = not route_state or route_state.get("mode") != mode or route_state.get("status") == "REWORK_READY"
            attempts = [] if new_role_cycle else list(route_state.get("attempts", []))
            attempted_profiles = {str(item.get("profile")) for item in attempts if isinstance(item, dict)}
            chain = fallback_chain(Path(str(route["routing_config"])), mode, str(route["profile"]))
            if str(route["profile"]) in attempted_profiles or len(attempts) >= len(chain):
                raise ValueError("finite routing attempt limit reached; refusing to repeat a provider profile")
            attempts.append({
                "profile": route["profile"], "provider": route["provider"], "provider_id": route["provider_id"],
                "model": route["model"], "effort": route["effort"], "started_at": now_iso(), "outcome": "STARTING",
            })
            update_routing_state(
                root, args.run, status="STARTING", mode=mode, active_profile=str(route["profile"]),
                chain=chain, attempts=attempts,
            )
        code, output = run(command, worktree, timeout=60, env=provider_child_environment(provider_env))
        launch_failed = code != 0
        if launch_failed:
            failure_category = classify_runtime_failure(output)
            if route:
                attempts[-1]["outcome"] = "LAUNCH_FAILED"
                attempts[-1]["ended_at"] = now_iso()
                update_routing_state(
                    root, args.run, status="LAUNCH_FAILED", active_profile=str(route["profile"]),
                    attempts=attempts, last_launch_failure_category=failure_category,
                )
            append_event(
                root, args.run, "system", "claude_launch_failed", "Claude background start failed",
                profile=safe_launch["profile"], provider=safe_launch["provider"], category=failure_category,
            )
        else:
            append_event(
                root, args.run, "codex", "claude_started", f"Claude Code {mode} Agent started",
                profile=safe_launch["profile"], provider=safe_launch["provider"],
                model=safe_launch["model"], effort=safe_launch["effort"], credential_source=safe_launch["credential_source"],
            )
            if route:
                attempts[-1]["outcome"] = "STARTED"
                update_routing_state(root, args.run, status="STARTED", attempts=attempts)
    if launch_failed and (not route or failure_category != "provider_or_quota" or args.no_supervisor):
        raise ValueError(f"Claude background start failed (category={failure_category})")
    if route and not args.no_supervisor:
        supervisor_pid = start_route_supervisor(root, args.run, str(route["profile"]), Path(str(route["routing_config"])))
        append_event(
            root, args.run, "system", "routing_supervisor_started", "Finite model fallback supervisor started",
            pid=supervisor_pid, profile=route["profile"], recovering_launch_failure=launch_failed,
        )
    result = "RECOVERY_STARTED" if launch_failed else "STARTED"
    print(json.dumps(safe_launch | {"result": result}, ensure_ascii=False, indent=2))
    return 0


def cmd_claude_status(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
    executable = shutil.which("claude")
    if not executable:
        raise FileNotFoundError("claude executable not found")
    code, output = run([executable, "agents", "--json", "--all", "--cwd", str(row["worktree"])], Path(str(row["worktree"])), timeout=30)
    if code:
        raise ValueError(f"Claude Agent status failed: {output}")
    print(output or "[]")
    return 0


def allowed_path(path: str, allow: list[str], deny: list[str]) -> bool:
    normalized = path.lstrip("./").rstrip("/")
    denied = any(normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/") for item in deny)
    permitted = any(normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/") for item in allow)
    return permitted and not denied


def record_failure(
    root: Path, run_id: str, stage: str, category: str, blocker_class: str,
    symptom: str, root_cause: str, evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    if category not in FAILURE_CATEGORIES:
        raise ValueError(f"invalid failure category: {category}")
    if blocker_class not in BLOCKER_CLASSES:
        raise ValueError(f"invalid blocker class: {blocker_class}")
    with db_connect(root) as db:
        active_run(db, run_id)
        sequence = int(db.execute("SELECT COUNT(*) FROM failures WHERE run_id=?", (run_id,)).fetchone()[0]) + 1
        failure_id = f"failure-{run_id}-{sequence}"
        created = now_iso()
        db.execute(
            "INSERT INTO failures VALUES(?,?,?,?,?,?,?,?,?)",
            (failure_id, run_id, stage, category, blocker_class, "OPEN", root_cause, created, None),
        )
    path = artifact_path(root, run_id, "failures.json")
    document = read_json(path) if path.is_file() else {"agent_os_version": AGENT_OS_VERSION, "run_id": run_id, "failures": []}
    failure = {
        "id": failure_id, "stage": stage, "category": category,
        "blocker_class": blocker_class, "status": "OPEN", "symptom": symptom,
        "root_cause": root_cause, "evidence_refs": evidence_refs or [],
        "created_at": created, "resolved_at": None, "resolution": None,
    }
    document.setdefault("failures", []).append(failure)
    atomic_json(path, document)
    append_event(root, run_id, "system", "failure_recorded", symptom, failure_id=failure_id, category=category, blocker_class=blocker_class)
    return failure


def cmd_failure_record(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    failure = record_failure(
        root, args.run, args.stage, args.category, args.blocker_class,
        args.symptom, args.root_cause, args.evidence_ref,
    )
    print(json.dumps(failure, ensure_ascii=False, indent=2))
    return 0


def cmd_failure_resolve(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    path = artifact_path(root, args.run, "failures.json")
    document = read_json(path)
    failure = next((item for item in document.get("failures", []) if item.get("id") == args.id), None)
    if not failure:
        raise ValueError(f"unknown failure: {args.id}")
    if failure.get("status") == "RESOLVED":
        raise ValueError(f"failure already resolved: {args.id}")
    with db_connect(root) as db:
        row = active_run(db, args.run)
        current_commit = git(Path(str(row["worktree"])), "rev-parse", "HEAD")
        resolved = now_iso()
        db.execute("UPDATE failures SET status='RESOLVED', resolved_at=? WHERE id=? AND run_id=?", (resolved, args.id, args.run))
    failure.update({
        "status": "RESOLVED", "resolved_at": resolved,
        "resolution": args.resolution, "resolution_commit": current_commit,
    })
    atomic_json(path, document)
    append_event(root, args.run, "codex", "failure_resolved", args.resolution, failure_id=args.id, resolution_commit=current_commit)
    print(json.dumps(failure, ensure_ascii=False, indent=2))
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
    branch_commit = git(Path(str(row["worktree"])), "rev-parse", "HEAD")
    assessment: dict[str, Any] = {
        "work_package": str(row["package_id"]), "outcome": args.outcome,
        "observation": args.observation, "reason": args.reason,
        "branch_commit": branch_commit, "assessed_by": "codex", "assessed_at": now_iso(),
        "automatic_policy_adoption": False,
    }
    if args.outcome == "proposal":
        required = {
            "hypothesis": args.hypothesis, "proposed_change": args.proposed_change,
            "expected_effect": args.expected_effect, "metric": args.metric,
            "validation_window": args.validation_window,
        }
        missing = [key for key, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ValueError("proposal requires: " + ", ".join(missing))
        improvement_id = f"improvement-{args.run}"
        proposal = {
            "agent_os_version": AGENT_OS_VERSION, "id": improvement_id,
            "source_run": args.run, "status": "PROPOSED", "risk": args.risk,
            "observation": args.observation, "hypothesis": args.hypothesis,
            "proposed_change": args.proposed_change, "expected_effect": args.expected_effect,
            "metric": args.metric, "validation_window": args.validation_window,
            "adoption_authority": "codex-or-user-after-validation", "created_at": now_iso(),
        }
        proposal_path = os_dir(root) / "improvements" / f"{improvement_id}.json"
        atomic_json(proposal_path, proposal)
        with db_connect(root) as db:
            db.execute(
                "INSERT OR REPLACE INTO improvements VALUES(?,?,?,?,?,?)",
                (improvement_id, args.run, "PROPOSED", args.risk, str(proposal_path), now_iso()),
            )
        assessment["proposal"] = {"id": improvement_id, "path": str(proposal_path), "sha256": sha256(proposal_path)}
    write_run_artifact(root, args.run, "learning-assessment.json", assessment)
    append_event(root, args.run, "codex", "learning_assessed", args.reason, outcome=args.outcome)
    print(json.dumps(assessment, ensure_ascii=False, indent=2))
    return 0


def build_maturity_report(root: Path, run_id: str) -> tuple[dict[str, Any], list[str]]:
    with db_connect(root) as db:
        row = active_run(db, run_id)
        failures = [dict(item) for item in db.execute("SELECT * FROM failures WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()]
    required = {
        "decision_trace": artifact_path(root, run_id, "decision-trace.json"),
        "permission_manifest": artifact_path(root, run_id, "permission-manifest.json"),
        "rollback_plan": artifact_path(root, run_id, "rollback-plan.json"),
        "learning_assessment": artifact_path(root, run_id, "learning-assessment.json"),
        "evidence_manifest": artifact_path(root, run_id, "evidence/manifest.json"),
        "verifier": artifact_path(root, run_id, "evidence/verifier.json"),
    }
    problems = [f"missing {name}" for name, path in required.items() if not path.is_file()]
    loaded = {name: read_json(path) for name, path in required.items() if path.is_file()}
    branch_commit = str(row["branch_commit"] or "")
    contract = load_package(root, str(row["package_id"]))
    unit = work_unit(root, str(contract["work_unit"]))
    project = read_json(os_dir(root) / "project.json")
    for name in ("evidence_manifest", "verifier", "learning_assessment"):
        value = loaded.get(name, {})
        if value and value.get("branch_commit") != branch_commit:
            problems.append(f"{name} does not bind branch commit {branch_commit}")
    if loaded.get("evidence_manifest", {}).get("result") != "PASS":
        problems.append("Evidence Manifest is not PASS")
    if loaded.get("verifier", {}).get("result") != "PASS":
        problems.append("Verifier is not PASS")
    unresolved = [item for item in failures if item.get("status") != "RESOLVED"]
    if unresolved:
        problems.append("unresolved failures: " + ", ".join(str(item["id"]) for item in unresolved))
    decision = loaded.get("decision_trace", {})
    permissions = loaded.get("permission_manifest", {})
    rollback = loaded.get("rollback_plan", {})
    learning = loaded.get("learning_assessment", {})
    expected_denied = list(dict.fromkeys([
        *contract.get("scope", {}).get("deny", []),
        *project.get("protected_paths", []), *unit.get("director_owned_paths", []),
    ]))
    expected_decision = contract.get("decision", {})
    for key in ("selected_approach", "rationale", "alternatives_rejected", "key_tradeoffs"):
        if decision.get(key) != expected_decision.get(key):
            problems.append(f"Decision Trace {key} drifted from the approved Work Package")
    if permissions.get("granted_paths") != contract.get("scope", {}).get("allow", []):
        problems.append("Permission Manifest granted paths drifted from the Work Package")
    if permissions.get("denied_paths") != expected_denied:
        problems.append("Permission Manifest denied paths drifted from current policy")
    expected_actions = ["read", "edit-authorized-paths", "agent-branch-commit", "verify", "heartbeat"]
    if permissions.get("granted_actions") != expected_actions:
        problems.append("Permission Manifest granted actions drifted from runtime policy")
    if permissions.get("denied_actions") != project.get("high_risk_operations", []):
        problems.append("Permission Manifest denied actions drifted from project policy")
    if rollback.get("external_side_effects", []) != contract.get("recovery", {}).get("external_side_effects", []):
        problems.append("Rollback Plan external side effects drifted from the Work Package")
    if rollback.get("baseline_commit") != row["baseline_commit"]:
        problems.append("Rollback Plan baseline drifted from the Run")
    expected_rollback_checks = contract.get("recovery", {}).get("rollback_verification", [])
    if rollback.get("rollback_verification", []) != expected_rollback_checks:
        problems.append("Rollback Plan verification drifted from the Work Package")
    report = {
        "agent_os_version": AGENT_OS_VERSION, "run_id": run_id,
        "work_package": str(row["package_id"]), "branch_commit": branch_commit,
        "result": "PASS" if not problems else "FAIL", "checked_at": now_iso(),
        "answers": {
            "why_this_action": {
                "selected_approach": decision.get("selected_approach"),
                "rationale": decision.get("rationale"),
                "alternatives_rejected": decision.get("alternatives_rejected", []),
            },
            "permissions_used": {
                "granted_paths": permissions.get("granted_paths", []),
                "granted_actions": permissions.get("granted_actions", []),
                "denied_actions": permissions.get("denied_actions", []),
            },
            "failure_location": {"failures": failures, "unresolved_count": len(unresolved)},
            "rollback_path": {
                "strategy": rollback.get("strategy"),
                "baseline_commit": rollback.get("baseline_commit"),
                "external_side_effects": rollback.get("external_side_effects", []),
            },
            "next_time_improvement": learning,
        },
        "artifacts": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in required.items() if path.is_file()
        },
        "problems": problems,
    }
    return report, problems


def cmd_maturity_report(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    report, problems = build_maturity_report(root, args.run)
    write_run_artifact(root, args.run, "maturity-report.json", report)
    with db_connect(root) as db:
        db.execute("UPDATE runs SET maturity_status=? WHERE id=?", (report["result"], args.run))
    append_event(root, args.run, "codex", "maturity_report", f"Five-question maturity {report['result']}", problems=problems)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


def cmd_verify(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
        package_id = str(row["package_id"])
        db.execute("UPDATE runs SET status='VERIFYING' WHERE id=?", (args.run,))
        db.execute("UPDATE work_packages SET status='VERIFYING', updated_at=? WHERE id=?", (now_iso(), package_id))
    contract = load_package(root, package_id)
    unit = work_unit(root, str(contract["work_unit"]))
    worktree = Path(str(row["worktree"]))
    branch = str(row["branch"])
    evidence = os_dir(root) / "runs" / args.run / "evidence"
    checks: list[dict[str, Any]] = []
    branch_commit = git(worktree, "rev-parse", "HEAD")
    ahead = int(git(worktree, "rev-list", "--count", f"{row['baseline_commit']}..HEAD") or "0")
    checks.append({"id": "branch-ahead", "type": "git", "level": "verified", "result": "pass" if ahead else "fail", "detail": f"{ahead} commit(s)"})
    changed = [line for line in git(worktree, "diff", "--name-only", f"{row['baseline_commit']}...HEAD").splitlines() if line]
    deny = list(dict.fromkeys([*contract.get("scope", {}).get("deny", []), *read_json(os_dir(root) / "project.json").get("protected_paths", []), *unit.get("director_owned_paths", [])]))
    allow = [str(value) for value in contract.get("scope", {}).get("allow", [])]
    disallowed = [path for path in changed if not allowed_path(path, allow, deny)]
    checks.append({"id": "path-scope", "type": "git", "level": "verified", "result": "pass" if not disallowed else "fail", "detail": disallowed or changed})
    clean = not git(worktree, "status", "--porcelain")
    checks.append({"id": "worktree-clean", "type": "git", "level": "verified", "result": "pass" if clean else "fail", "detail": str(worktree)})
    diff_path = evidence / "change.diff"
    diff_path.write_text(git(worktree, "diff", "--binary", f"{row['baseline_commit']}...HEAD") + "\n", encoding="utf-8")
    artifacts: list[dict[str, Any]] = [{"id": "git-diff", "type": "git_diff", "level": "verified", "result": "pass", "path": str(diff_path), "sha256": sha256(diff_path)}]
    commands = contract.get("verify_commands") or unit.get("verify_commands", [])
    for index, command in enumerate(commands, 1):
        started = time.monotonic()
        code, output = run([verification_shell(), "-c", str(command)], worktree, timeout=600)
        duration_seconds = round(time.monotonic() - started, 3)
        log = evidence / f"verify-{index:02d}.log"
        log.write_text(output + "\n", encoding="utf-8")
        result = "pass" if code == 0 else "fail"
        checks.append({"id": f"verify-{index:02d}", "type": "command", "level": "verified", "result": result, "command": command, "exit_code": code, "duration_seconds": duration_seconds, "path": str(log), "sha256": sha256(log)})
    overall = "PASS" if all(item["result"] == "pass" for item in checks) else "FAIL"
    manifest = {
        "agent_os_version": AGENT_OS_VERSION, "run_id": args.run, "work_package": package_id,
        "baseline_commit": str(row["baseline_commit"]), "branch": branch, "branch_commit": branch_commit,
        "result": overall, "captured_at": now_iso(), "changed_paths": changed,
        "checks": checks, "artifacts": artifacts, "unverified_claims": contract.get("success_criteria", {}).get("observed", []),
    }
    manifest_path = evidence / "manifest.json"
    atomic_json(manifest_path, manifest)
    with db_connect(root) as db:
        target = "READY_FOR_REVIEW" if overall == "PASS" else "EVIDENCE_INCOMPLETE"
        db.execute("UPDATE runs SET status=?, branch_commit=?, evidence_status=?, heartbeat_at=? WHERE id=?", (target, branch_commit, overall, now_iso(), args.run))
        db.execute("UPDATE work_packages SET status=?, updated_at=? WHERE id=?", (target, now_iso(), package_id))
    append_event(root, args.run, "claude", "evidence_collected", f"Evidence {overall}", branch_commit=branch_commit)
    if overall == "PASS":
        code, output = call_agent_shift(root, "transition", str(root), "READY_FOR_REVIEW", "--handoff-id", args.run, "--note", f"Agent OS evidence PASS for {args.run}", "--actor", "claude")
        if code:
            raise ValueError(output)
    else:
        failed = [str(item.get("id")) for item in checks if item.get("result") == "fail"]
        record_failure(
            root, args.run, "VERIFYING", "verification", "model-fixable",
            "Verification failed: " + ", ".join(failed),
            "One or more verification checks failed; detailed diagnosis is pending.",
            [str(manifest_path), *[str(item.get("path")) for item in checks if item.get("result") == "fail" and item.get("path")]],
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if overall == "PASS" else 1


def cmd_verifier(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
    manifest_path = os_dir(root) / "runs" / args.run / "evidence" / "manifest.json"
    manifest = read_json(manifest_path)
    findings: list[str] = []
    if manifest.get("result") != "PASS":
        findings.append("Evidence Manifest is not PASS")
    current_commit = git(Path(str(row["worktree"])), "rev-parse", "HEAD")
    if current_commit != manifest.get("branch_commit"):
        findings.append("Branch changed after evidence capture")
    for item in [*manifest.get("checks", []), *manifest.get("artifacts", [])]:
        path = item.get("path")
        expected = item.get("sha256")
        if path and (not Path(path).is_file() or (expected and sha256(Path(path)) != expected)):
            findings.append(f"Missing or changed evidence: {path}")
    result = "PASS" if not findings else "FAIL"
    report = {"run_id": args.run, "result": result, "checked_at": now_iso(), "branch_commit": current_commit, "findings": findings, "verifier": args.actor}
    report_path = os_dir(root) / "runs" / args.run / "evidence" / "verifier.json"
    atomic_json(report_path, report)
    append_event(root, args.run, args.actor, "verifier", f"Verifier {result}", findings=findings)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result == "PASS" else 1


def cmd_review(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    if args.decision not in DECISIONS:
        raise ValueError(f"invalid decision: {args.decision}")
    if args.decision == "CHANGES_REQUESTED" and not args.required_change:
        raise ValueError("CHANGES_REQUESTED requires at least one --required-change")
    with db_connect(root) as db:
        row = active_run(db, args.run)
        allowed_statuses = {"READY_FOR_REVIEW", "CODEX_REVIEWING"}
        if row["status"] not in allowed_statuses:
            raise ValueError(f"review requires {sorted(allowed_statuses)}, found {row['status']}")
    package_id = str(row["package_id"])
    contract = load_package(root, package_id)
    manifest_path = os_dir(root) / "runs" / args.run / "evidence" / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    verifier_path = os_dir(root) / "runs" / args.run / "evidence" / "verifier.json"
    verifier = read_json(verifier_path) if verifier_path.is_file() else {}
    branch_commit = git(Path(str(row["worktree"])), "rev-parse", "HEAD")
    with db_connect(root) as db:
        review_round = int(db.execute("SELECT COUNT(*) FROM reviews WHERE run_id=?", (args.run,)).fetchone()[0]) + 1
        changes_rounds = int(db.execute("SELECT COUNT(*) FROM reviews WHERE run_id=? AND decision='CHANGES_REQUESTED'", (args.run,)).fetchone()[0])
    if args.decision == "CHANGES_REQUESTED" and changes_rounds >= int(contract.get("budget", {}).get("max_rework_rounds", 3)):
        raise ValueError("maximum rework rounds reached; structural diagnosis or user decision required")
    shift_state = read_json(root / ".agent-shift" / "state.json")
    if shift_state.get("status") == "READY_FOR_REVIEW":
        code, output = call_agent_shift(root, "transition", str(root), "CODEX_REVIEWING", "--handoff-id", args.run, "--note", f"Codex reviewing Agent OS Run {args.run}")
        if code:
            raise ValueError(output)
    gate: dict[str, Any] = {}
    maturity: dict[str, Any] = {}
    level = governance_level(contract)
    if args.decision == "ACCEPTED":
        if manifest.get("result") != "PASS" or verifier.get("result") != "PASS":
            raise ValueError("ACCEPTED requires PASS evidence and verifier")
        if manifest.get("branch_commit") != branch_commit or verifier.get("branch_commit") != branch_commit:
            raise ValueError("ACCEPTED requires exact commit match")
        with db_connect(root) as db:
            unresolved = [
                dict(item) for item in db.execute(
                    "SELECT * FROM failures WHERE run_id=? AND status!='RESOLVED'", (args.run,)
                ).fetchall()
            ]
        if unresolved:
            raise ValueError("ACCEPTED requires all failures resolved: " + ", ".join(str(item["id"]) for item in unresolved))
        revision = int(contract.get("schema_revision", 1))
        if revision >= 4:
            outcome_path = artifact_path(root, args.run, "outcome-contract.json")
            outcome = read_json(outcome_path) if outcome_path.is_file() else {}
            if outcome.get("contract") != contract.get("outcome_contract", {}):
                raise ValueError("ACCEPTED requires the frozen Outcome Contract to match the Work Package")
        if level == "L2":
            if revision >= 4:
                challenge = read_json(artifact_path(root, args.run, "director-challenge.json"))
                latest = challenge.get("latest", {})
                if latest.get("decision") != "PASS" or latest.get("contract_digest") != contract_digest(contract):
                    raise ValueError("L2 ACCEPTED requires a matching PASS Director Challenge")
            maturity, maturity_problems = build_maturity_report(root, args.run)
            write_run_artifact(root, args.run, "maturity-report.json", maturity)
            with db_connect(root) as db:
                db.execute("UPDATE runs SET maturity_status=? WHERE id=?", (maturity["result"], args.run))
            if maturity_problems:
                raise ValueError("L2 ACCEPTED requires five-question maturity PASS: " + "; ".join(maturity_problems))
        elif level != "L2":
            maturity = {"result": "NOT_REQUIRED", "governance_level": level}
            with db_connect(root) as db:
                db.execute("UPDATE runs SET maturity_status='NOT_REQUIRED' WHERE id=?", (args.run,))
        code, output = call_agent_shift(root, "merge-gate", str(root), "--work-unit", str(contract["work_unit"]))
        if code:
            raise ValueError(output)
        gate = json.loads(output)
        if gate.get("result") != "PASS" or gate.get("branch_commit") != branch_commit:
            raise ValueError("ACCEPTED requires exact passing merge gate")
    review = {
        "agent_os_version": AGENT_OS_VERSION, "id": f"review-{args.run}-r{review_round}",
        "round": review_round,
        "work_package": package_id, "run_id": args.run, "reviewer": "codex",
        "decision": args.decision, "summary": args.summary, "required_changes": args.required_change,
        "governance_level": level,
        "director_context": contract.get("director_context", {}),
        "branch_commit": branch_commit,
        "evidence_manifest_sha256": sha256(manifest_path) if manifest_path.is_file() else None,
        "verifier_result": verifier.get("result"), "maturity_result": maturity.get("result"),
        "maturity_report_sha256": sha256(artifact_path(root, args.run, "maturity-report.json")) if maturity.get("result") not in {None, "NOT_REQUIRED"} else None,
        "merge_gate_result": gate.get("result"), "reviewed_at": now_iso(),
    }
    review_json = os_dir(root) / "reviews" / f"{args.run}-r{review_round}.json"
    atomic_json(review_json, review)
    review_md = os_dir(root) / "reviews" / f"{args.run}-r{review_round}.md"
    review_md.write_text(
        f"# Review: {args.run}\n\n## Work Package\n\n{package_id}\n\n## Strategic Context\n\n"
        f"- Mission alignment: {contract.get('director_context', {}).get('mission_alignment', 'legacy package')}\n"
        f"- Priority: {contract.get('director_context', {}).get('priority', 'legacy')}\n"
        f"- Expected gain: {contract.get('director_context', {}).get('expected_gain', 'legacy package')}\n\n"
        f"## Evidence\n\nManifest: `{review.get('evidence_manifest_sha256')}`\n\n"
        f"## Five Questions\n\nMaturity: `{review.get('maturity_result')}`  \nReport: `{review.get('maturity_report_sha256')}`\n\n"
        f"## Decision\n\n{args.decision}\n\n## Summary\n\n{args.summary}\n\n## Required Changes\n\n" + ("\n".join(f"- {item}" for item in args.required_change) or "None") + "\n",
        encoding="utf-8",
    )
    control_git_code, _ = run(["git", "rev-parse", "--verify", "HEAD"], root, timeout=30)
    if control_git_code == 0:
        expected = {str(review_json.relative_to(root)), str(review_md.relative_to(root))}
        learning_path = artifact_path(root, args.run, "learning-assessment.json")
        if learning_path.is_file():
            proposal = read_json(learning_path).get("proposal", {})
            proposal_path = Path(str(proposal.get("path", ""))) if proposal else None
            if proposal_path and proposal_path.is_file() and root in proposal_path.resolve().parents:
                expected.add(str(proposal_path.resolve().relative_to(root)))
        status = git(root, "status", "--porcelain", "--untracked-files=all")
        changed = {line[3:] for line in status.splitlines() if len(line) > 3}
        unexpected = sorted(changed - expected)
        if unexpected:
            raise ValueError(f"control worktree has unrelated changes; review not committed: {unexpected}")
        git(root, "add", *sorted(expected))
        environment = os.environ.copy()
        environment["AGENT_SHIFT_ALLOW_MAIN_COMMIT"] = "1"
        code, output = run(["git", "commit", "-m", f"review: {args.decision.lower()} {args.run}"], root, timeout=120, env=environment)
        if code:
            raise ValueError(f"failed to commit Codex Review: {output}")
    if args.decision == "ACCEPTED":
        code, output = call_agent_shift(root, "merge-gate", str(root), "--work-unit", str(contract["work_unit"]))
        if code:
            raise ValueError(f"post-review Merge Gate failed: {output}")
        gate = json.loads(output)
        if gate.get("result") != "PASS" or gate.get("branch_commit") != branch_commit:
            raise ValueError("post-review Merge Gate must bind the accepted branch commit")
    with db_connect(root) as db:
        db.execute(
            """INSERT INTO reviews(id, package_id, run_id, decision, branch_commit, evidence_sha256, summary, created_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET decision=excluded.decision,
              branch_commit=excluded.branch_commit, evidence_sha256=excluded.evidence_sha256,
              summary=excluded.summary, created_at=excluded.created_at""",
            (review["id"], package_id, args.run, args.decision, branch_commit, review.get("evidence_manifest_sha256") or "", args.summary, now_iso()),
        )
        package_status = "REWORK" if args.decision == "CHANGES_REQUESTED" else args.decision
        db.execute("UPDATE runs SET status=? WHERE id=?", (package_status, args.run))
        db.execute("UPDATE work_packages SET status=?, updated_at=? WHERE id=?", (package_status, now_iso(), package_id))
    code, output = call_agent_shift(root, "transition", str(root), args.decision, "--handoff-id", args.run, "--note", args.summary)
    if code:
        raise ValueError(output)
    append_event(root, args.run, "codex", "review", f"Review {args.decision}", required_changes=args.required_change)
    if args.decision == "CHANGES_REQUESTED":
        record_failure(
            root, args.run, "CODEX_REVIEWING", "implementation", "model-fixable",
            "Codex requested changes: " + ("; ".join(args.required_change) or args.summary),
            "The delivered behavior did not yet meet the frozen acceptance criteria.",
            [str(review_json)],
        )
    print(str(review_json))
    return 0


def load_run_events(root: Path, run_id: str) -> list[dict[str, Any]]:
    path = run_dir(root, run_id) / "events.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def build_run_economics(root: Path, run_id: str) -> dict[str, Any]:
    with db_connect(root) as db:
        row = active_run(db, run_id)
        reviews = [dict(item) for item in db.execute("SELECT * FROM reviews WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()]
        failures = [dict(item) for item in db.execute("SELECT * FROM failures WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()]
    contract = load_package(root, str(row["package_id"]))
    events = load_run_events(root, run_id)
    started = parse_iso(str(row["started_at"]))
    ended = parse_iso(str(row["ended_at"])) or now()
    total_seconds = round(max(0.0, (ended - started).total_seconds()), 3) if started else None
    evidence_times = [parse_iso(str(item.get("timestamp"))) for item in events if item.get("event") == "evidence_collected"]
    evidence_times = [value for value in evidence_times if value is not None]
    merged_times = [parse_iso(str(item.get("timestamp"))) for item in events if item.get("event") == "merged"]
    merged_times = [value for value in merged_times if value is not None]
    first_evidence = min(evidence_times) if evidence_times else None
    last_evidence = max(evidence_times) if evidence_times else None
    merged_at = max(merged_times) if merged_times else None
    implementation_elapsed = round(max(0.0, (first_evidence - started).total_seconds()), 3) if started and first_evidence else None
    review_elapsed = round(max(0.0, (merged_at - last_evidence).total_seconds()), 3) if merged_at and last_evidence else None
    overhead_ratio = round(review_elapsed / total_seconds, 4) if review_elapsed is not None and total_seconds else None
    manifest_path = artifact_path(root, run_id, "evidence/manifest.json")
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    verification_checks = [item for item in manifest.get("checks", []) if item.get("type") == "command"]
    verification_duration = round(sum(float(item.get("duration_seconds", 0) or 0) for item in verification_checks), 3)
    routing_path = routing_state_path(root, run_id)
    routing = read_json(routing_path) if routing_path.is_file() else {}
    attempts = [item for item in routing.get("attempts", []) if isinstance(item, dict)]
    economics = {
        "agent_os_version": AGENT_OS_VERSION, "run_id": run_id,
        "work_package": str(row["package_id"]), "governance_level": governance_level(contract),
        "delivery_status": str(row["status"]), "outcome_status": str(row["outcome_status"] or "NOT_RECORDED"),
        "measured_at": now_iso(), "measurement_status": "PARTIAL",
        "timing": {
            "started_at": row["started_at"], "delivery_ended_at": row["ended_at"],
            "total_wall_clock_seconds": total_seconds,
            "time_to_first_evidence_seconds": implementation_elapsed,
            "last_evidence_to_merge_seconds": review_elapsed,
            "observed_governance_wall_clock_ratio": overhead_ratio,
        },
        "counts": {
            "events": len(events), "verification_runs": len(evidence_times),
            "verification_commands": len(verification_checks), "review_rounds": len(reviews),
            "rework_rounds": sum(1 for item in reviews if item.get("decision") == "CHANGES_REQUESTED"),
            "failures": len(failures), "resolved_failures": sum(1 for item in failures if item.get("status") == "RESOLVED"),
            "model_attempts": len(attempts),
            "provider_fallbacks": sum(1 for item in events if item.get("event") == "routing_fallback"),
        },
        "verification_command_seconds": verification_duration,
        "token_usage": {"input_tokens": None, "output_tokens": None, "source": "unavailable-from-runtime"},
        "measurement_limits": [
            "Wall-clock phase intervals include human wait time and are not labor-time measurements.",
            "The governance ratio is emitted only when both evidence and merge timestamps exist.",
            "Token usage remains null unless a future runtime exposes trustworthy per-Run usage.",
        ],
    }
    return economics


def write_run_economics(root: Path, run_id: str) -> Path:
    economics = build_run_economics(root, run_id)
    path = write_run_artifact(root, run_id, "run-economics.json", economics)
    with db_connect(root) as db:
        db.execute("UPDATE runs SET economics_status='RECORDED' WHERE id=?", (run_id,))
    return path


def cmd_economics(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    path = write_run_economics(root, args.run)
    print(json.dumps(read_json(path), ensure_ascii=False, indent=2))
    return 0


def cmd_outcome_check(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
    contract = load_package(root, str(row["package_id"]))
    if governance_level(contract) == "L0":
        raise ValueError("L0 uses delivery acceptance and does not enter the post-merge Outcome loop")
    if row["status"] not in {"OUTCOME_PENDING", "OUTCOME_INCONCLUSIVE"}:
        raise ValueError(f"outcome-check requires OUTCOME_PENDING or OUTCOME_INCONCLUSIVE, found {row['status']}")
    evidence = [hashed_evidence(root, value) for value in args.evidence_file]
    status = f"OUTCOME_{args.result}"
    outcome_contract = contract.get("outcome_contract", {})
    receipt = {
        "agent_os_version": AGENT_OS_VERSION, "run_id": args.run,
        "work_package": str(row["package_id"]), "governance_level": governance_level(contract),
        "status": status, "merge_commit": row["merge_commit"],
        "contract": outcome_contract, "contract_sha256": hashlib.sha256(
            json.dumps(outcome_contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "observed_value": args.observed_value, "evidence": evidence,
        "note": args.note, "decision_owner": "codex", "recorded_at": now_iso(),
    }
    local_path = write_run_artifact(root, args.run, "outcome-result.json", receipt)
    with db_connect(root) as db:
        db.execute("UPDATE runs SET status=?, outcome_status=? WHERE id=?", (status, status, args.run))
        db.execute("UPDATE work_packages SET status=?, updated_at=? WHERE id=?", (status, now_iso(), row["package_id"]))
        db.execute(
            "INSERT OR REPLACE INTO outcomes VALUES(?,?,?,?)",
            (args.run, status, str(local_path), now_iso()),
        )
    append_event(root, args.run, "codex", "outcome_checked", status, observed_value=args.observed_value)
    write_run_economics(root, args.run)
    print(json.dumps(receipt | {"local_artifact": str(local_path)}, ensure_ascii=False, indent=2))
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
        if row["status"] != "ACCEPTED":
            raise ValueError("merge requires ACCEPTED Run")
        package_id = str(row["package_id"])
    contract = load_package(root, package_id)
    level = governance_level(contract)
    unit_id = str(contract["work_unit"])
    code, output = call_agent_shift(root, "merge", str(root), "--work-unit", unit_id)
    if code:
        raise ValueError(output)
    merged = json.loads(output)
    code, remove_output = call_agent_shift(root, "worktree-remove", str(root), "--work-unit", unit_id)
    if code:
        raise ValueError(remove_output)
    post_merge_outcome = int(contract.get("schema_revision", 1)) >= 4 and level in {"L1", "L2"}
    run_status = "OUTCOME_PENDING" if post_merge_outcome else "MERGED"
    outcome_status = "OUTCOME_PENDING" if post_merge_outcome else ("NOT_REQUIRED" if level == "L0" else "LEGACY")
    with db_connect(root) as db:
        db.execute("DELETE FROM locks WHERE run_id=?", (args.run,))
        db.execute(
            "UPDATE runs SET status=?, merge_commit=?, ended_at=?, outcome_status=? WHERE id=?",
            (run_status, merged.get("merge_commit"), now_iso(), outcome_status, args.run),
        )
        db.execute("UPDATE work_packages SET status=?, updated_at=? WHERE id=?", (run_status, now_iso(), package_id))
    code, baseline_output = call_agent_shift(root, "baseline", str(root), "--work-unit", unit_id)
    if code:
        raise ValueError(baseline_output)
    append_event(root, args.run, "codex", "merged", f"Merged {row['branch']}", merge_commit=merged.get("merge_commit"))
    economics_path = write_run_economics(root, args.run)
    print(json.dumps(merged | {
        "run_status": run_status, "outcome_status": outcome_status,
        "economics_artifact": str(economics_path),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        row = active_run(db, args.run)
    rollback_ready_states = {"MERGED", "OUTCOME_PENDING", "OUTCOME_CONFIRMED", "OUTCOME_REFUTED", "OUTCOME_INCONCLUSIVE"}
    if row["status"] not in rollback_ready_states:
        raise ValueError("rollback requires a delivered Run with no prior rollback")
    if row["rollback_commit"]:
        raise ValueError(f"Run already rolled back at {row['rollback_commit']}")
    merge_commit = str(row["merge_commit"] or "")
    if not merge_commit:
        raise ValueError("rollback requires a recorded merge commit")
    contract = load_package(root, str(row["package_id"]))
    unit_id = str(contract["work_unit"])
    unit = work_unit(root, unit_id)
    repo = repo_root(root, unit)
    base_branch = str(unit.get("git_policy", {}).get("baseline_branch", "main"))
    external = contract.get("recovery", {}).get("external_side_effects", [])
    plan = {
        "agent_os_version": AGENT_OS_VERSION, "run_id": args.run,
        "mutated": False, "reason": args.reason, "repo": str(repo),
        "base_branch": base_branch, "merge_commit": merge_commit,
        "strategy": "git-revert-merge-commit", "external_side_effects": external,
        "requires_external_followup": bool(external),
    }
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if external and not args.ack_external:
        raise ValueError("external side effects exist; pass --ack-external after planning their separate recovery")
    if git(repo, "branch", "--show-current") != base_branch:
        raise ValueError(f"rollback base worktree must be on {base_branch}")
    if git(repo, "status", "--porcelain"):
        raise ValueError("rollback base worktree must be clean")
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
    incomplete = [name for name in ("MERGE_HEAD", "REVERT_HEAD", "CHERRY_PICK_HEAD") if (git_dir / name).exists()]
    if incomplete:
        raise ValueError("rollback refused during incomplete Git operation: " + ", ".join(incomplete))
    with db_connect(root) as db:
        if db.execute("SELECT 1 FROM locks WHERE work_unit=?", (unit_id,)).fetchone():
            raise ValueError("rollback requires no active writer lock for the work unit")
    registry = read_json(root / ".agent-shift" / "worktrees.json")
    registered = [branch for branch, value in registry.get("branches", {}).items() if value.get("work_unit") == unit_id]
    if registered:
        raise ValueError("rollback requires no registered Agent worktree for the work unit: " + ", ".join(registered))
    current_head = git(repo, "rev-parse", "HEAD")
    if current_head != merge_commit:
        raise ValueError(f"safe rollback requires HEAD to equal recorded merge commit {merge_commit}; found {current_head}")
    parents = git(repo, "rev-list", "--parents", "-n", "1", merge_commit).split()
    if len(parents) != 3:
        raise ValueError("recorded merge commit must have exactly two parents; automatic rollback is refused")
    first_parent, second_parent = parents[1], parents[2]
    if second_parent != str(row["branch_commit"]):
        raise ValueError("merge second parent does not match the accepted branch commit")
    ancestor_code, _ = run(["git", "merge-base", "--is-ancestor", str(row["baseline_commit"]), first_parent], repo, timeout=30)
    if ancestor_code:
        raise ValueError("Run baseline is not an ancestor of the merge first parent")
    shift_state = read_json(root / ".agent-shift" / "state.json")
    if shift_state.get("merge_commit") != merge_commit:
        raise ValueError("Agent Shift and Agent OS merge commits do not match")
    manifest = read_json(artifact_path(root, args.run, "evidence/manifest.json"))
    verifier = read_json(artifact_path(root, args.run, "evidence/verifier.json"))
    if manifest.get("result") != "PASS" or verifier.get("result") != "PASS":
        raise ValueError("rollback requires the accepted PASS evidence and verifier")
    if manifest.get("branch_commit") != row["branch_commit"] or verifier.get("branch_commit") != row["branch_commit"]:
        raise ValueError("rollback evidence does not bind the recorded branch commit")
    environment = os.environ.copy()
    environment["AGENT_SHIFT_ALLOW_MAIN_COMMIT"] = "1"
    code, output = run(["git", "revert", "-m", "1", "--no-edit", merge_commit], repo, timeout=120, env=environment)
    if code:
        run(["git", "revert", "--abort"], repo, timeout=30, env=environment)
        failed_receipt = {
            **plan, "mutated": False, "result": "FAIL", "failed_at": now_iso(),
            "failure_stage": "git-revert", "detail": output,
        }
        write_run_artifact(root, args.run, "rollback-receipt.json", failed_receipt)
        record_failure(root, args.run, "ROLLBACK", "merge", "contradiction", "Git revert failed", "The merge commit could not be reverted cleanly.", [str(artifact_path(root, args.run, "rollback-receipt.json"))])
        print(json.dumps(failed_receipt, ensure_ascii=False, indent=2))
        return 1
    rollback_commit = git(repo, "rev-parse", "HEAD")
    evidence = run_dir(root, args.run) / "evidence" / "rollback"
    evidence.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    commands = contract.get("recovery", {}).get("rollback_verification") or unit.get("verify_commands", [])
    for index, command in enumerate(commands, 1):
        code, command_output = run([verification_shell(), "-c", str(command)], repo, timeout=600)
        log = evidence / f"verify-{index:02d}.log"
        log.write_text(command_output + "\n", encoding="utf-8")
        checks.append({
            "command": command, "exit_code": code, "result": "pass" if code == 0 else "fail",
            "path": str(log), "sha256": sha256(log),
        })
    result = "PASS" if all(item["result"] == "pass" for item in checks) else "FAIL"
    receipt = {
        **plan, "mutated": True, "result": result,
        "rollback_commit": rollback_commit, "executed_at": now_iso(),
        "checks": checks,
        "external_recovery_status": "NOT_VERIFIED" if external else "NOT_APPLICABLE",
        "note": "Git rollback does not prove that external side effects were reversed." if external else "No external side effects were declared.",
    }
    write_run_artifact(root, args.run, "rollback-receipt.json", receipt)
    run_status = "CODE_REVERTED_EXTERNAL_PENDING" if external else ("ROLLED_BACK" if result == "PASS" else "ROLLBACK_FAILED")
    code, shift_output = call_agent_shift(
        root, "rollback-record", str(root), "--merge-commit", merge_commit,
        "--rollback-commit", rollback_commit, "--status", run_status, "--note", args.reason,
    )
    if code:
        raise ValueError(f"Git rollback completed but Agent Shift synchronization failed: {shift_output}")
    rollback_review_json = os_dir(root) / "reviews" / f"{args.run}-rollback.json"
    rollback_review_md = os_dir(root) / "reviews" / f"{args.run}-rollback.md"
    atomic_json(rollback_review_json, receipt)
    rollback_review_md.write_text(
        f"# Rollback Receipt: {args.run}\n\n- Result: {result}\n- Merge commit: `{merge_commit}`\n"
        f"- Revert commit: `{rollback_commit}`\n- External recovery: {receipt['external_recovery_status']}\n\n"
        f"## Reason\n\n{args.reason}\n",
        encoding="utf-8",
    )
    control_git_code, _ = run(["git", "rev-parse", "--verify", "HEAD"], root, timeout=30)
    if control_git_code == 0:
        expected = {str(rollback_review_json.relative_to(root)), str(rollback_review_md.relative_to(root))}
        changed = {line[3:] for line in git(root, "status", "--porcelain", "--untracked-files=all").splitlines() if len(line) > 3}
        unexpected = sorted(changed - expected)
        if unexpected:
            raise ValueError(f"rollback succeeded but control worktree has unrelated changes: {unexpected}")
        git(root, "add", *sorted(expected))
        code, output = run(["git", "commit", "-m", f"review: record rollback {args.run}"], root, timeout=120, env=environment)
        if code:
            raise ValueError(f"rollback succeeded but receipt commit failed: {output}")
    with db_connect(root) as db:
        db.execute(
            "UPDATE runs SET status=?, rollback_commit=?, ended_at=?, outcome_status='CANCELLED_BY_ROLLBACK' WHERE id=?",
            (run_status, rollback_commit, now_iso(), args.run),
        )
        db.execute(
            "UPDATE work_packages SET status=?, updated_at=? WHERE id=?",
            (run_status, now_iso(), row["package_id"]),
        )
    code, baseline_output = call_agent_shift(root, "baseline", str(root), "--work-unit", unit_id)
    if code:
        raise ValueError(f"rollback completed but baseline refresh failed: {baseline_output}")
    append_event(root, args.run, "codex", "rolled_back", args.reason, rollback_commit=rollback_commit, result=result)
    write_run_economics(root, args.run)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if result == "PASS" else 1


def cmd_lock_release(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        lock = db.execute("SELECT * FROM locks WHERE work_unit=?", (args.work_unit,)).fetchone()
        if not lock:
            raise ValueError(f"no lock for {args.work_unit}")
        db.execute("DELETE FROM locks WHERE work_unit=?", (args.work_unit,))
        db.execute("UPDATE runs SET status='LOCK_EXPIRED' WHERE id=?", (lock["run_id"],))
        package_id = db.execute("SELECT package_id FROM runs WHERE id=?", (lock["run_id"],)).fetchone()[0]
        db.execute("UPDATE work_packages SET status='LOCK_EXPIRED', updated_at=? WHERE id=?", (now_iso(), package_id))
    append_event(root, str(lock["run_id"]), "codex", "lock_released", args.reason, work_unit=args.work_unit)
    print(f"released {args.work_unit}")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    findings: list[dict[str, Any]] = []
    with db_connect(root) as db:
        known_worktrees = {str(row["worktree"]): str(row["id"]) for row in db.execute("SELECT id, worktree FROM runs").fetchall()}
        for lock in db.execute("SELECT * FROM locks").fetchall():
            expired = datetime.fromisoformat(lock["expires_at"]) < now()
            worktree = Path(str(lock["worktree"]))
            dirty = worktree.is_dir() and bool(git(worktree, "status", "--porcelain"))
            findings.append({"work_unit": lock["work_unit"], "run_id": lock["run_id"], "expired": expired, "worktree_exists": worktree.is_dir(), "dirty": dirty})
        for run_row in db.execute("SELECT * FROM runs WHERE status NOT IN ('MERGED','OUTCOME_PENDING','OUTCOME_CONFIRMED','OUTCOME_REFUTED','OUTCOME_INCONCLUSIVE','ROLLED_BACK','CODE_REVERTED_EXTERNAL_PENDING','ROLLBACK_FAILED','CANCELLED')").fetchall():
            has_lock = db.execute("SELECT 1 FROM locks WHERE run_id=?", (run_row["id"],)).fetchone() is not None
            worktree = Path(str(run_row["worktree"]))
            if not has_lock or not worktree.is_dir():
                findings.append({"run_id": run_row["id"], "issue": "missing_lock" if not has_lock else "missing_worktree", "worktree": str(worktree)})
    registry_path = root / ".agent-shift" / "worktrees.json"
    if registry_path.is_file():
        for branch, record in read_json(registry_path).get("branches", {}).items():
            path = str(record.get("path") or "")
            if path and path not in known_worktrees:
                worktree = Path(path)
                findings.append({"branch": branch, "issue": "orphan_registered_worktree", "worktree": path, "worktree_exists": worktree.is_dir(), "dirty": worktree.is_dir() and bool(git(worktree, "status", "--porcelain"))})
    print(json.dumps({"project": str(root), "mutated": False, "findings": findings}, ensure_ascii=False, indent=2))
    return 1 if any(item.get("issue") or item.get("expired") or item.get("worktree_exists") is False for item in findings) else 0


def cmd_status(args: argparse.Namespace) -> int:
    root = root_path(args.project)
    with db_connect(root) as db:
        packages = [dict(row) for row in db.execute("SELECT * FROM work_packages ORDER BY created_at").fetchall()]
        runs = [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY started_at").fetchall()]
        locks = [dict(row) for row in db.execute("SELECT * FROM locks").fetchall()]
    print(json.dumps({"packages": packages, "runs": runs, "locks": locks}, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    requested = Path(args.project).expanduser().resolve()
    root = root_path(args.project)
    checks: list[tuple[str, str]] = []
    if requested != root:
        try:
            adapter = read_json(requested / ".agent-os" / "project.json")
            control = read_json(os_dir(root) / "project.json")
            checks.append(("PASS" if adapter.get("adapter") is True else "FAIL", "adapter marker"))
            checks.append(("PASS" if Path(str(adapter.get("control_root"))).expanduser().resolve() == root else "FAIL", "adapter control root"))
            unit_ids = {str(item.get("id")) for item in shift_config(root).get("work_units", [])}
            identity_ok = adapter.get("project_id") == control.get("id") and str(adapter.get("work_unit")) in unit_ids
            checks.append(("PASS" if identity_ok else "FAIL", "adapter project and work-unit identity"))
        except Exception as error:
            checks.append(("FAIL", f"adapter config: {error}"))
    for relative in (".agent-os/project.json", ".agent-os/policy/evidence-review.json", ".agent-os/policy/director-principles.json", ".agent-os/policy/five-question-maturity.json", ".agent-os/policy/proportional-governance.json", ".agent-os/state.db", ".claude/settings.json", ".claude/agents/verifier.md", "AGENTS.md", "CLAUDE.md"):
        checks.append(("PASS" if (root / relative).is_file() else "FAIL", relative))
    try:
        config = read_json(os_dir(root) / "project.json")
        checks.append(("PASS" if config.get("agent_os_version") == AGENT_OS_VERSION else "FAIL", "Agent OS version"))
        checks.append(("PASS" if Path(str(config.get("control_root"))).resolve() == root else "FAIL", "canonical control root"))
    except Exception as error:
        checks.append(("FAIL", f"project config: {error}"))
    try:
        with db_connect(root) as db:
            run_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(runs)").fetchall()}
            checks.append(("PASS" if {"merge_commit", "rollback_commit", "maturity_status", "governance_level", "outcome_status", "economics_status"} <= run_columns else "FAIL", "v0.4 Run database schema"))
            tables = {str(row[0]) for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            checks.append(("PASS" if {"failures", "improvements", "outcomes"} <= tables else "FAIL", "v0.4 failure, learning, and outcome tables"))
            for package in db.execute("SELECT * FROM work_packages").fetchall():
                problems = validate_contract(root, load_package(root, package["id"]))
                checks.append(("PASS" if not problems else "FAIL", f"package {package['id']}: {problems or package['status']}"))
            for lock in db.execute("SELECT * FROM locks").fetchall():
                expired = datetime.fromisoformat(lock["expires_at"]) < now()
                checks.append(("WARN" if expired else "PASS", f"lock {lock['work_unit']} for {lock['run_id']} {'expired' if expired else 'active'}"))
                checks.append(("PASS" if Path(lock["worktree"]).is_dir() else "FAIL", f"lock worktree {lock['worktree']}"))
            for run_row in db.execute("SELECT * FROM runs WHERE status IN ('READY_FOR_REVIEW','CODEX_REVIEWING','ACCEPTED','MERGED','OUTCOME_PENDING','OUTCOME_CONFIRMED','OUTCOME_REFUTED','OUTCOME_INCONCLUSIVE')").fetchall():
                manifest = os_dir(root) / "runs" / run_row["id"] / "evidence" / "manifest.json"
                checks.append(("PASS" if manifest.is_file() else "FAIL", f"run {run_row['id']} Evidence Manifest"))
                contract = load_package(root, str(run_row["package_id"]))
                if int(contract.get("schema_revision", 1)) >= SCHEMA_REVISION:
                    for filename in ("decision-trace.json", "permission-manifest.json", "rollback-plan.json", "outcome-contract.json"):
                        checks.append(("PASS" if artifact_path(root, run_row["id"], filename).is_file() else "FAIL", f"run {run_row['id']} {filename}"))
                    level = governance_level(contract)
                    if level == "L2" and run_row["status"] in {"ACCEPTED", "MERGED", "OUTCOME_PENDING", "OUTCOME_CONFIRMED", "OUTCOME_REFUTED", "OUTCOME_INCONCLUSIVE"}:
                        checks.append(("PASS" if run_row["maturity_status"] == "PASS" else "FAIL", f"run {run_row['id']} five-question maturity"))
                    if run_row["status"] in {"MERGED", "OUTCOME_PENDING", "OUTCOME_CONFIRMED", "OUTCOME_REFUTED", "OUTCOME_INCONCLUSIVE"}:
                        checks.append(("PASS" if run_row["economics_status"] == "RECORDED" else "FAIL", f"run {run_row['id']} governance economics"))
    except Exception as error:
        checks.append(("FAIL", f"state database: {error}"))
    code, output = call_agent_shift(root, "doctor", str(root))
    checks.append(("PASS" if code == 0 else "FAIL", "Agent Shift doctor"))
    for level, message in checks:
        print(f"{level:4} {message}")
    failures = sum(level == "FAIL" for level, _ in checks)
    warnings = sum(level == "WARN" for level, _ in checks)
    print(f"SUMMARY failures={failures} warnings={warnings} checks={len(checks)}")
    if args.verbose:
        print(output)
    return 1 if failures or (args.strict and warnings) else 0


def extract_tool_path(payload: dict[str, Any]) -> str | None:
    tool_input = payload.get("tool_input") or {}
    for key in ("file_path", "path", "notebook_path"):
        if tool_input.get(key):
            return str(tool_input[key])
    return None


def cmd_hook(args: argparse.Namespace) -> int:
    payload = json.load(sys.stdin)
    cwd = Path(str(payload.get("cwd") or os.getcwd())).resolve()
    try:
        root = find_runtime_root(cwd)
    except Exception:
        return 0
    tool_name = str(payload.get("tool_name") or "")
    with db_connect(root) as db:
        lock = db.execute("SELECT * FROM locks WHERE worktree=?", (str(cwd),)).fetchone()
        if not lock:
            lock = next((row for row in db.execute("SELECT * FROM locks").fetchall() if cwd == Path(row["worktree"]) or Path(row["worktree"]) in cwd.parents), None)
        if args.phase == "pre" and tool_name in WRITE_TOOLS | {"Bash"}:
            command = str((payload.get("tool_input") or {}).get("command") or "").strip().lower()
            read_only_prefixes = (
                "pwd", "ls", "find ", "rg ", "grep ", "sed -n", "cat ", "head ", "tail ", "wc ",
                "git status", "git diff", "git log", "git show", "git rev-parse", "git branch --show-current",
                "node --check", "python3 -m json.tool", "agent-os status", "agent-os doctor", "agent-os recover",
                "agent-os claude-status", "agent-shift status", "agent-shift doctor",
            )
            if not lock:
                if tool_name in WRITE_TOOLS or not command.startswith(read_only_prefixes):
                    print("Agent OS blocked: no active single-writer lock for this workspace", file=sys.stderr)
                    return 2
                append_event(root, None, "claude", "hook_pre", "read-only Bash without lock", command_redacted=True)
                return 0
            if datetime.fromisoformat(lock["expires_at"]) < now():
                print("Agent OS blocked: writer lock expired", file=sys.stderr)
                return 2
            run_row = active_run(db, str(lock["run_id"]))
            contract = load_package(root, str(run_row["package_id"]))
            if tool_name in WRITE_TOOLS:
                target = extract_tool_path(payload)
                if target:
                    target_path = Path(target).expanduser().resolve()
                    worktree = Path(str(lock["worktree"])).resolve()
                    if target_path != worktree and worktree not in target_path.parents:
                        print("Agent OS blocked: write is outside assigned worktree", file=sys.stderr)
                        return 2
                    relative = str(target_path.relative_to(worktree))
                    project = read_json(os_dir(root) / "project.json")
                    deny = [*contract.get("scope", {}).get("deny", []), *project.get("protected_paths", [])]
                    if not allowed_path(relative, contract.get("scope", {}).get("allow", []), deny):
                        print(f"Agent OS blocked: path outside Work Package scope: {relative}", file=sys.stderr)
                        return 2
            if tool_name == "Bash":
                if any(fragment in command for fragment in HIGH_RISK_FRAGMENTS):
                    print("Agent OS blocked: high-risk command requires Codex/user decision", file=sys.stderr)
                    return 2
                governance = (".agent-os", ".agent-shift", ".githooks", "agents.md", "claude.md", ".claude/settings")
                safe_control = command.strip().startswith(("agent-os verify", "agent-os heartbeat", "agent-os status", "agent-os claude-status", "agent-shift log"))
                if any(fragment in command for fragment in governance) and not safe_control:
                    print("Agent OS blocked: governance mutation is director-owned", file=sys.stderr)
                    return 2
        run_id = str(lock["run_id"]) if lock else None
    append_event(
        root, run_id, "claude", f"hook_{args.phase}",
        tool_name or payload.get("hook_event_name", "event"),
        failure_input_redacted=args.phase == "failure",
    )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init"); init.add_argument("project"); init.add_argument("--id", required=True); init.add_argument("--name", required=True); init.add_argument("--mission", required=True); init.set_defaults(func=cmd_init)
    upgrade = sub.add_parser("upgrade"); upgrade.add_argument("project"); upgrade.set_defaults(func=cmd_upgrade)
    package = sub.add_parser("package-create"); package.add_argument("project"); package.add_argument("--id", required=True); package.add_argument("--work-unit", required=True); package.add_argument("--governance-level", choices=sorted(GOVERNANCE_LEVELS), default="L1"); package.add_argument("--risk-factor", action="append", default=[]); package.add_argument("--goal", required=True); package.add_argument("--objective"); package.add_argument("--mission-alignment"); package.add_argument("--priority", choices=("P0", "P1", "P2", "P3")); package.add_argument("--expected-gain", required=True); package.add_argument("--external-signal", action="append", default=[]); package.add_argument("--frontline-signal", action="append", default=[]); package.add_argument("--first-principles", action="append", default=[]); package.add_argument("--selected-approach"); package.add_argument("--rationale"); package.add_argument("--alternative", action="append", default=[]); package.add_argument("--tradeoff", action="append", default=[]); package.add_argument("--external-side-effect", action="append", default=[]); package.add_argument("--rollback-check", action="append", default=[]); package.add_argument("--outcome-metric"); package.add_argument("--outcome-baseline"); package.add_argument("--outcome-target"); package.add_argument("--outcome-validation-window"); package.add_argument("--outcome-evidence-source"); package.add_argument("--allow", nargs="*", default=[]); package.add_argument("--deny", nargs="*", default=[]); package.add_argument("--verify", nargs="*", default=[]); package.add_argument("--verified", action="append", default=[]); package.add_argument("--reviewed", action="append", default=[]); package.add_argument("--observed", action="append", default=[]); package.add_argument("--assumption", action="append", default=[]); package.add_argument("--constraint", action="append", default=[]); package.add_argument("--stop", action="append", default=["scope expansion", "credential or irreversible action", "three failed rework rounds"]); package.add_argument("--max-runs", type=int, default=4); package.add_argument("--max-rework", type=int, default=3); package.set_defaults(func=cmd_package_create)
    challenge = sub.add_parser("director-challenge"); challenge.add_argument("project"); challenge.add_argument("--package", required=True); challenge.add_argument("--reviewer", required=True); challenge.add_argument("--decision", choices=("PASS", "CHANGES_REQUESTED"), required=True); challenge.add_argument("--summary", required=True); challenge.add_argument("--finding", action="append", default=[]); challenge.add_argument("--review-file", required=True); challenge.set_defaults(func=cmd_challenge_record)
    ready = sub.add_parser("package-ready"); ready.add_argument("project"); ready.add_argument("--id", required=True); ready.set_defaults(func=cmd_package_ready)
    start = sub.add_parser("run-start"); start.add_argument("project"); start.add_argument("--package", required=True); start.add_argument("--run", required=True); start.add_argument("--agent", choices=("claude", "claude-subagent", "codex-subagent"), default="claude"); start.set_defaults(func=cmd_run_start)
    heartbeat = sub.add_parser("heartbeat"); heartbeat.add_argument("project"); heartbeat.add_argument("--run", required=True); heartbeat.add_argument("--actor", default="claude", choices=("claude", "codex", "system")); heartbeat.set_defaults(func=cmd_heartbeat)
    rework = sub.add_parser("rework-start"); rework.add_argument("project"); rework.add_argument("--run", required=True); rework.set_defaults(func=cmd_rework_start)
    providers = sub.add_parser("provider-list"); providers.add_argument("--database"); providers.set_defaults(func=cmd_provider_list)
    route = sub.add_parser("route-resolve"); route.add_argument("--profile"); route.add_argument("--routing-config"); route.set_defaults(func=cmd_route_resolve)
    claude_start = sub.add_parser("claude-start"); claude_start.add_argument("project"); claude_start.add_argument("--run", required=True); claude_start.add_argument("--profile"); claude_start.add_argument("--routing-config"); claude_start.add_argument("--dry-run", action="store_true"); claude_start.add_argument("--no-supervisor", action="store_true", help=argparse.SUPPRESS); claude_start.set_defaults(func=cmd_claude_start)
    claude_watch = sub.add_parser("claude-watch"); claude_watch.add_argument("project"); claude_watch.add_argument("--run", required=True); claude_watch.add_argument("--profile", required=True); claude_watch.add_argument("--routing-config"); claude_watch.set_defaults(func=cmd_claude_watch)
    claude_status = sub.add_parser("claude-status"); claude_status.add_argument("project"); claude_status.add_argument("--run", required=True); claude_status.set_defaults(func=cmd_claude_status)
    verify = sub.add_parser("verify"); verify.add_argument("project"); verify.add_argument("--run", required=True); verify.set_defaults(func=cmd_verify)
    verifier = sub.add_parser("verifier"); verifier.add_argument("project"); verifier.add_argument("--run", required=True); verifier.add_argument("--actor", default="codex-subagent", choices=("codex", "codex-subagent", "claude-verifier")); verifier.set_defaults(func=cmd_verifier)
    failure = sub.add_parser("failure-record"); failure.add_argument("project"); failure.add_argument("--run", required=True); failure.add_argument("--stage", required=True); failure.add_argument("--category", choices=sorted(FAILURE_CATEGORIES), required=True); failure.add_argument("--blocker-class", choices=sorted(BLOCKER_CLASSES), required=True); failure.add_argument("--symptom", required=True); failure.add_argument("--root-cause", required=True); failure.add_argument("--evidence-ref", action="append", default=[]); failure.set_defaults(func=cmd_failure_record)
    resolve = sub.add_parser("failure-resolve"); resolve.add_argument("project"); resolve.add_argument("--run", required=True); resolve.add_argument("--id", required=True); resolve.add_argument("--resolution", required=True); resolve.set_defaults(func=cmd_failure_resolve)
    learn = sub.add_parser("learn"); learn.add_argument("project"); learn.add_argument("--run", required=True); learn.add_argument("--outcome", choices=("no-change", "proposal"), required=True); learn.add_argument("--observation", required=True); learn.add_argument("--reason", required=True); learn.add_argument("--hypothesis"); learn.add_argument("--proposed-change"); learn.add_argument("--risk", choices=("L1", "L2", "L3"), default="L1"); learn.add_argument("--expected-effect"); learn.add_argument("--metric"); learn.add_argument("--validation-window"); learn.set_defaults(func=cmd_learn)
    maturity = sub.add_parser("maturity-report"); maturity.add_argument("project"); maturity.add_argument("--run", required=True); maturity.set_defaults(func=cmd_maturity_report)
    review = sub.add_parser("review"); review.add_argument("project"); review.add_argument("--run", required=True); review.add_argument("--decision", choices=sorted(DECISIONS), required=True); review.add_argument("--summary", required=True); review.add_argument("--required-change", action="append", default=[]); review.set_defaults(func=cmd_review)
    merge = sub.add_parser("merge"); merge.add_argument("project"); merge.add_argument("--run", required=True); merge.set_defaults(func=cmd_merge)
    outcome = sub.add_parser("outcome-check"); outcome.add_argument("project"); outcome.add_argument("--run", required=True); outcome.add_argument("--result", choices=sorted(OUTCOME_RESULTS), required=True); outcome.add_argument("--observed-value", required=True); outcome.add_argument("--evidence-file", action="append", required=True); outcome.add_argument("--note", required=True); outcome.set_defaults(func=cmd_outcome_check)
    economics = sub.add_parser("economics"); economics.add_argument("project"); economics.add_argument("--run", required=True); economics.set_defaults(func=cmd_economics)
    rollback = sub.add_parser("rollback"); rollback.add_argument("project"); rollback.add_argument("--run", required=True); rollback.add_argument("--reason", required=True); rollback.add_argument("--execute", action="store_true"); rollback.add_argument("--ack-external", action="store_true"); rollback.set_defaults(func=cmd_rollback)
    release = sub.add_parser("lock-release"); release.add_argument("project"); release.add_argument("--work-unit", required=True); release.add_argument("--reason", required=True); release.set_defaults(func=cmd_lock_release)
    recover = sub.add_parser("recover"); recover.add_argument("project"); recover.set_defaults(func=cmd_recover)
    status = sub.add_parser("status"); status.add_argument("project"); status.set_defaults(func=cmd_status)
    doctor = sub.add_parser("doctor"); doctor.add_argument("project"); doctor.add_argument("--strict", action="store_true"); doctor.add_argument("--verbose", action="store_true"); doctor.set_defaults(func=cmd_doctor)
    hook = sub.add_parser("hook"); hook.add_argument("phase", choices=("pre", "post", "failure", "stop")); hook.set_defaults(func=cmd_hook)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error, subprocess.TimeoutExpired) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
