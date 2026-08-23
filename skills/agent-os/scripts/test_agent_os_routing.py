#!/usr/bin/env python3
"""Focused tests for CC Switch-backed Agent OS execution routing."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("agent_os.py")
SPEC = importlib.util.spec_from_file_location("agent_os_routing_test_target", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
AGENT_OS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT_OS)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="agent-os-routing-")
        self.root = Path(self.temp.name)
        self.database = self.root / "cc-switch.db"
        db = sqlite3.connect(self.database)
        try:
            db.execute(
                """CREATE TABLE providers(
                   id TEXT NOT NULL, app_type TEXT NOT NULL, name TEXT NOT NULL,
                   settings_config TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0,
                   sort_index INTEGER, PRIMARY KEY(id, app_type))"""
            )
            db.execute(
                "INSERT INTO providers VALUES(?,?,?,?,?,?)",
                ("glm", "claude", "Zhipu GLM", json.dumps({"env": {
                    "ANTHROPIC_AUTH_TOKEN": "secret-glm",
                    "ANTHROPIC_BASE_URL": "https://glm.example/anthropic",
                    "ANTHROPIC_MODEL": "glm-old",
                }}), 1, 1),
            )
            db.execute(
                "INSERT INTO providers VALUES(?,?,?,?,?,?)",
                ("kimi", "claude", "Kimi For Coding", json.dumps({"env": {
                    "ANTHROPIC_AUTH_TOKEN": "secret-kimi",
                    "ANTHROPIC_BASE_URL": "https://kimi.example/coding/",
                    "ANTHROPIC_MODEL": "k3",
                }}), 0, 2),
            )
            db.commit()
        finally:
            db.close()
        self.config = self.root / "routing.json"
        self.config.write_text(json.dumps({
            "schema_version": 1,
            "cc_switch_database": str(self.database),
            "default_profile": "builder",
            "profiles": {
                "builder": {"mode": "builder", "provider": "Zhipu GLM", "model": "glm-5.2", "effort": "medium"},
                "fallback": {"mode": "builder", "provider": "Kimi For Coding", "model": "kimi-for-coding"},
                "reviewer": {"mode": "reviewer", "provider": "Kimi For Coding", "model": "k3", "effort": "high"},
            },
            "fallback_chains": {"builder": ["builder", "fallback"], "reviewer": ["reviewer"]},
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_profiles_resolve_without_mutating_cc_switch(self) -> None:
        before = digest(self.database)
        builder, builder_env = AGENT_OS.resolve_execution_profile(None, self.config)
        fallback, fallback_env = AGENT_OS.resolve_execution_profile("fallback", self.config)
        reviewer, reviewer_env = AGENT_OS.resolve_execution_profile("reviewer", self.config)
        self.assertEqual(digest(self.database), before)
        self.assertEqual((builder["provider"], builder["model"], builder["effort"]), ("Zhipu GLM", "glm-5.2", "medium"))
        self.assertEqual((fallback["provider"], fallback["model"], fallback["mode"]), ("Kimi For Coding", "kimi-for-coding", "builder"))
        self.assertEqual((reviewer["provider"], reviewer["model"], reviewer["effort"], reviewer["mode"]), ("Kimi For Coding", "k3", "high", "reviewer"))
        self.assertEqual(builder_env["ANTHROPIC_MODEL"], "glm-5.2")
        self.assertEqual(fallback_env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "kimi-for-coding")
        self.assertEqual(reviewer_env["CLAUDE_CODE_SUBAGENT_MODEL"], "k3")

    def test_routing_config_on_disk_does_not_opt_in_provider_spend(self) -> None:
        with mock.patch.dict(os.environ, {"AGENT_OS_ROUTING_CONFIG": str(self.config)}):
            metadata, provider_env = AGENT_OS.resolve_execution_profile(None, None)
        self.assertIsNone(metadata)
        self.assertIsNone(provider_env)

    def test_base_url_userinfo_never_enters_safe_metadata(self) -> None:
        db = sqlite3.connect(self.database)
        try:
            row = db.execute(
                "SELECT settings_config FROM providers WHERE id='glm' AND app_type='claude'"
            ).fetchone()
            settings = json.loads(row[0])
            settings["env"]["ANTHROPIC_BASE_URL"] = "https://url-secret@glm.example/anthropic"
            db.execute(
                "UPDATE providers SET settings_config=? WHERE id='glm' AND app_type='claude'",
                (json.dumps(settings),),
            )
            db.commit()
        finally:
            db.close()
        metadata, _ = AGENT_OS.resolve_execution_profile("builder", self.config)
        self.assertEqual(metadata["base_url_host"], "glm.example")
        self.assertNotIn("url-secret", json.dumps(metadata))

    def test_safe_metadata_and_child_environment_do_not_leak_other_provider(self) -> None:
        metadata, provider_env = AGENT_OS.resolve_execution_profile("reviewer", self.config)
        rendered = json.dumps(metadata, sort_keys=True)
        self.assertNotIn("secret-kimi", rendered)
        self.assertNotIn("secret-glm", rendered)
        original_api_key = os.environ.get("ANTHROPIC_API_KEY")
        try:
            os.environ["ANTHROPIC_API_KEY"] = "wrong-global-secret"
            child = AGENT_OS.provider_child_environment(provider_env)
            self.assertNotIn("ANTHROPIC_API_KEY", child)
            self.assertEqual(child["ANTHROPIC_AUTH_TOKEN"], "secret-kimi")
            self.assertEqual(child["ANTHROPIC_MODEL"], "k3")
        finally:
            if original_api_key is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = original_api_key

    def test_missing_provider_fails_explicitly(self) -> None:
        value = json.loads(self.config.read_text(encoding="utf-8"))
        value["profiles"]["builder"]["provider"] = "Missing Provider"
        self.config.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provider not found"):
            AGENT_OS.resolve_execution_profile("builder", self.config)

    def test_missing_optional_config_preserves_inherit_behavior(self) -> None:
        metadata, provider_env = AGENT_OS.resolve_execution_profile(None, self.root / "absent.json")
        self.assertIsNone(metadata)
        self.assertIsNone(provider_env)
        with self.assertRaises(FileNotFoundError):
            AGENT_OS.resolve_execution_profile("builder", self.root / "absent.json")

    def test_routing_config_rejects_embedded_credentials(self) -> None:
        value = json.loads(self.config.read_text(encoding="utf-8"))
        value["profiles"]["builder"]["api_key"] = "must-not-be-here"
        self.config.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "cannot contain credentials"):
            AGENT_OS.resolve_execution_profile("builder", self.config)

    def test_quota_failure_uses_finite_fallback_chain(self) -> None:
        chain = AGENT_OS.fallback_chain(self.config, "builder", "builder")
        self.assertEqual(chain, ["builder", "fallback"])
        first = AGENT_OS.runtime_recovery_decision(
            "failed", "HTTP 429 rate_limit_error: quota exhausted", chain, "builder",
        )
        self.assertEqual(first, {
            "action": "fallback", "state": "failed", "category": "provider_or_quota", "next_profile": "fallback",
        })
        exhausted = AGENT_OS.runtime_recovery_decision(
            "failed", "insufficient balance", chain, "fallback",
        )
        self.assertEqual(exhausted["action"], "fail")
        self.assertEqual(exhausted["category"], "provider_or_quota_chain_exhausted")
        stopped = AGENT_OS.runtime_recovery_decision("stopped", "stopped", chain, "builder")
        self.assertEqual(stopped["action"], "stop")

    def test_environment_failure_does_not_burn_other_model_quota(self) -> None:
        chain = ["builder", "fallback"]
        decision = AGENT_OS.runtime_recovery_decision(
            "failed", "working directory no longer exists", chain, "builder",
        )
        self.assertEqual(decision["action"], "fail")
        self.assertEqual(decision["category"], "environment")

    def test_unknown_failure_does_not_switch_provider(self) -> None:
        decision = AGENT_OS.runtime_recovery_decision(
            "failed", "unexpected local process error", ["builder", "fallback"], "builder",
        )
        self.assertEqual(decision["action"], "fail")
        self.assertEqual(decision["category"], "runtime_unknown")

    def test_provider_compatibility_failures_are_classified_for_finite_fallback(self) -> None:
        for detail in (
            "API Error: Unable to connect to API (ConnectionRefused)",
            "API Error: 400 模型不存在，请检查模型代码",
            "HTTP 503 provider service unavailable",
        ):
            with self.subTest(detail=detail):
                self.assertEqual(AGENT_OS.classify_runtime_failure(detail), "provider_or_quota")

    def test_provider_warning_does_not_interrupt_an_active_session(self) -> None:
        detail = '"glm-5.2" is not a model this version of Claude Code recognizes'
        decision = AGENT_OS.runtime_recovery_decision(
            "working", detail, ["builder", "fallback"], "builder",
        )
        self.assertEqual(decision, {"action": "wait", "state": "working"})
        execution = AGENT_OS.execution_classification(
            "RESPONSIVE", detail, {"implementation_started": False},
        )
        self.assertEqual(execution["classification"], "ACTIVE_NO_IMPLEMENTATION_EVIDENCE")
        self.assertIsNone(execution["failure_category"])

    def test_real_claude_nonterminal_states_keep_supervisor_waiting(self) -> None:
        for state in (
            "working", "busy", "idle", "queued", "pending", "waiting",
            "blocked", "needs input", "awaiting-input",
        ):
            with self.subTest(state=state):
                decision = AGENT_OS.runtime_recovery_decision(
                    state, None, ["builder", "fallback"], "builder",
                )
                self.assertEqual(decision["action"], "wait")

    def test_permission_prompt_blocked_state_keeps_the_same_writer(self) -> None:
        agent = {
            "id": "permission-wait-session-id",
            "state": "blocked",
            "waitingFor": "permission prompt",
        }
        detail, _ = AGENT_OS.safe_agent_status(agent)
        self.assertEqual(detail, "permission prompt")
        decision = AGENT_OS.runtime_recovery_decision(
            agent["state"], detail, ["builder", "fallback"], "builder",
        )
        self.assertEqual(decision, {"action": "wait", "state": "blocked"})
        self.assertEqual(
            AGENT_OS.permission_wait_status(agent["state"], detail),
            "WAITING_FOR_PERMISSION",
        )
        self.assertIsNone(AGENT_OS.permission_wait_status("working", detail))
        self.assertIsNone(AGENT_OS.permission_wait_status("blocked", "waiting for tests"))

    def test_runtime_failure_record_is_honest_when_cause_is_unknown(self) -> None:
        blocker, symptom, root_cause = AGENT_OS.runtime_failure_fields("runtime_unknown")
        self.assertEqual(blocker, "unverifiable")
        self.assertIn("unsupported", symptom)
        self.assertIn("diagnosis is pending", root_cause)
        blocker, _, root_cause = AGENT_OS.runtime_failure_fields("provider_or_quota_chain_exhausted")
        self.assertEqual(blocker, "new-authority-required")
        self.assertIn("provider chain", root_cause)

    def test_duplicate_or_repeated_profiles_cannot_loop(self) -> None:
        value = json.loads(self.config.read_text(encoding="utf-8"))
        value["fallback_chains"]["builder"] = ["builder", "fallback", "builder"]
        self.config.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate profiles"):
            AGENT_OS.fallback_chain(self.config, "builder", "builder")
        repeated = AGENT_OS.runtime_recovery_decision(
            "failed", "HTTP 429", ["builder", "fallback"], "builder", ["builder", "fallback"],
        )
        self.assertEqual(repeated["action"], "fail")
        self.assertEqual(repeated["category"], "routing_attempt_repeated")

    def test_any_active_worktree_agent_blocks_a_second_writer(self) -> None:
        payload = json.dumps([
            {"name": "agent-os-run-1-builder", "state": "running"},
            {"name": "agent-os-run-2-builder", "state": "running"},
            {"name": "agent-os-run-1-old", "state": "done"},
        ])
        with mock.patch.object(AGENT_OS, "run", return_value=(0, payload)):
            active = AGENT_OS.active_routed_agents("claude", self.root, "run-1")
        self.assertEqual(
            [item["name"] for item in active],
            ["agent-os-run-1-builder", "agent-os-run-2-builder"],
        )

    def test_reviewer_tools_are_strictly_read_only(self) -> None:
        self.assertEqual(AGENT_OS.claude_allowed_tools("reviewer"), ["Read", "Glob", "Grep"])
        self.assertIn("Write", AGENT_OS.claude_allowed_tools("builder"))
        self.assertFalse(any(tool.startswith("Bash") for tool in AGENT_OS.claude_allowed_tools("reviewer")))

    def test_status_failure_fails_closed_before_launch(self) -> None:
        with mock.patch.object(AGENT_OS, "run", return_value=(1, "provider unavailable")):
            with self.assertRaisesRegex(ValueError, "refusing a second writer"):
                AGENT_OS.active_routed_agents("claude", self.root, "run-1")
        with mock.patch.object(AGENT_OS, "run", return_value=(0, "not-json")):
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                AGENT_OS.active_routed_agents("claude", self.root, "run-1")
        for state in (None, "unknown", "queued", "pending"):
            payload = json.dumps([{"name": "unclassified", "state": state}])
            with mock.patch.object(AGENT_OS, "run", return_value=(0, payload)):
                self.assertEqual(len(AGENT_OS.active_routed_agents("claude", self.root, "run-1")), 1)

    def test_launch_mutex_is_keyed_by_worktree_not_run(self) -> None:
        worktree = self.root / "shared-worktree"
        worktree.mkdir()
        with mock.patch.object(AGENT_OS, "os_dir", return_value=self.root / ".agent-os"):
            with AGENT_OS.claude_launch_mutex(self.root, worktree):
                with self.assertRaisesRegex(ValueError, "already in progress"):
                    with AGENT_OS.claude_launch_mutex(self.root, worktree / "."):
                        pass

    def test_preclassified_quota_failure_is_not_classified_twice(self) -> None:
        decision = AGENT_OS.runtime_recovery_decision(
            "failed", None, ["builder", "fallback"], "builder", ["builder"],
            failure_category="provider_or_quota",
        )
        self.assertEqual(decision["action"], "fallback")
        self.assertEqual(decision["next_profile"], "fallback")

    def test_activity_time_parser_supports_claude_job_formats(self) -> None:
        iso = AGENT_OS.parse_agent_activity("2026-07-18T10:00:00.000Z")
        millis = AGENT_OS.parse_agent_activity(1_768_000_000_000)
        self.assertIsNotNone(iso)
        self.assertIsNotNone(millis)
        self.assertIsNone(AGENT_OS.parse_agent_activity("not-a-time"))

    def test_inherited_runtime_metadata_reports_model_without_credentials(self) -> None:
        jobs = self.root / "jobs"
        state = jobs / "abc123" / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({
            "providerEnv": {
                "ANTHROPIC_AUTH_TOKEN": "must-not-appear",
                "ANTHROPIC_BASE_URL": "https://provider.example/anthropic",
                "ANTHROPIC_MODEL": "deepseek-v4-pro",
            },
        }), encoding="utf-8")
        metadata = AGENT_OS.safe_agent_runtime_metadata({"id": "abc123"}, jobs)
        self.assertEqual(metadata, {"model": "deepseek-v4-pro"})
        self.assertNotIn("must-not-appear", json.dumps(metadata))
        self.assertNotIn("provider.example", json.dumps(metadata))

    def test_supervision_health_distinguishes_stall_unresponsive_and_permission(self) -> None:
        self.assertEqual(
            AGENT_OS.supervision_health("working", "reading files", 299, 300, 900),
            "RESPONSIVE",
        )
        self.assertEqual(
            AGENT_OS.supervision_health("working", "reading files", 300, 300, 900),
            "SUSPECTED_STALL",
        )
        self.assertEqual(
            AGENT_OS.supervision_health("working", "reading files", 900, 300, 900),
            "UNRESPONSIVE",
        )
        self.assertEqual(
            AGENT_OS.supervision_health("blocked", "permission prompt", 1200, 300, 900),
            "WAITING_FOR_PERMISSION",
        )

    def test_execution_classification_separates_activity_from_implementation(self) -> None:
        no_progress = {"implementation_started": False}
        partial = {"implementation_started": True}
        self.assertEqual(
            AGENT_OS.execution_classification("RESPONSIVE", "reading", no_progress)["classification"],
            "ACTIVE_NO_IMPLEMENTATION_EVIDENCE",
        )
        self.assertEqual(
            AGENT_OS.execution_classification("RESPONSIVE", "editing", partial)["classification"],
            "ACTIVE_IMPLEMENTING",
        )
        self.assertEqual(
            AGENT_OS.execution_classification("NOT_DISCOVERED", None, partial)["classification"],
            "ORPHANED_PARTIAL_WORK",
        )
        provider = AGENT_OS.execution_classification(
            "FAILED", "HTTP 429 quota exhausted", partial,
        )
        self.assertEqual(provider["classification"], "PROVIDER_FAILED")
        self.assertEqual(provider["failure_category"], "provider_or_quota")
        permission = AGENT_OS.execution_classification(
            "WAITING_FOR_PERMISSION", "permission prompt", no_progress,
        )
        self.assertEqual(permission["classification"], "WAITING_FOR_PERMISSION")

    def test_worktree_evidence_distinguishes_clean_diff_and_commit(self) -> None:
        worktree = self.root / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
        (worktree / "app.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.txt"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Agent OS Tests", "-c", "user.email=agent-os@example.invalid", "commit", "-qm", "base"],
            cwd=worktree,
            check=True,
        )
        baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip()
        clean = AGENT_OS.worktree_implementation_evidence(worktree, baseline)
        self.assertFalse(clean["implementation_started"])
        self.assertEqual(clean["changed_path_count"], 0)

        (worktree / "app.txt").write_text("changed\n", encoding="utf-8")
        dirty = AGENT_OS.worktree_implementation_evidence(worktree, baseline)
        self.assertTrue(dirty["implementation_started"])
        self.assertTrue(dirty["worktree_dirty"])

        subprocess.run(["git", "add", "app.txt"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Agent OS Tests", "-c", "user.email=agent-os@example.invalid", "commit", "-qm", "change"],
            cwd=worktree,
            check=True,
        )
        committed = AGENT_OS.worktree_implementation_evidence(worktree, baseline)
        self.assertTrue(committed["implementation_started"])
        self.assertFalse(committed["worktree_dirty"])
        self.assertEqual(committed["commits_ahead"], 1)

    def test_inherit_profile_keeps_a_single_non_fallback_chain(self) -> None:
        decision = AGENT_OS.runtime_recovery_decision(
            "failed", "API Error: Unable to connect to API (ConnectionRefused)",
            ["inherit"], "inherit", ["inherit"],
        )
        self.assertEqual(decision["action"], "fail")
        self.assertEqual(decision["category"], "provider_or_quota_chain_exhausted")

    def test_inherit_supervisor_command_omits_routing_config(self) -> None:
        process = mock.Mock(pid=4321)
        run_root = self.root / ".agent-os" / "runs" / "run-inherit"
        run_root.mkdir(parents=True)
        with (
            mock.patch.object(AGENT_OS, "run_dir", return_value=run_root),
            mock.patch.object(AGENT_OS, "update_routing_state"),
            mock.patch.object(AGENT_OS.subprocess, "Popen", return_value=process) as popen,
        ):
            pid = AGENT_OS.start_route_supervisor(
                self.root, "run-inherit", "inherit", None, "builder",
            )
        self.assertEqual(pid, 4321)
        command = popen.call_args.args[0]
        self.assertIn("--profile", command)
        self.assertIn("inherit", command)
        self.assertIn("--mode", command)
        self.assertNotIn("--routing-config", command)

    def test_verification_shell_is_portable_and_configurable(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_OS_SHELL", None)
            self.assertTrue(Path(AGENT_OS.verification_shell()).name.endswith("sh"))
        with mock.patch.dict(os.environ, {"AGENT_OS_SHELL": "/definitely/missing/shell"}):
            with self.assertRaisesRegex(FileNotFoundError, "not executable"):
                AGENT_OS.verification_shell()

    def test_only_supervisor_state_can_advance_an_existing_cycle(self) -> None:
        for status in ("STARTING", "STARTED", "SUPERVISING", "SUSPECTED_STALL", "COMPLETED"):
            with self.assertRaisesRegex(ValueError, "routing cycle already exists"):
                AGENT_OS.validate_routing_launch_authorization(
                    {"status": status, "mode": "builder", "next_profile": None},
                    "builder", "fallback", False,
                )
        with self.assertRaisesRegex(ValueError, "Supervisor authorization"):
            AGENT_OS.validate_routing_launch_authorization(
                {"status": "STARTED", "mode": "builder", "next_profile": "fallback"},
                "builder", "fallback", True,
            )
        AGENT_OS.validate_routing_launch_authorization(
            {"status": "FALLBACK_STARTING", "mode": "builder", "next_profile": "fallback"},
            "builder", "fallback", True,
        )
        AGENT_OS.validate_routing_launch_authorization(
            {"status": "REWORK_READY", "mode": "builder"}, "builder", "builder", False,
        )
        AGENT_OS.validate_routing_launch_authorization(
            {"status": "RUNTIME_RECOVERY_READY", "mode": "builder"}, "builder", "builder", False,
        )

    def test_worktree_path_does_not_look_like_governance_mutation(self) -> None:
        worktree = self.root / ".agent-shift" / "worktrees" / "run-1"
        command = f'cd "{worktree}" && git status --short'
        self.assertFalse(AGENT_OS.command_references_governance(command, worktree))
        self.assertTrue(AGENT_OS.command_references_governance("cat .agent-os/state.db", worktree))
        self.assertTrue(AGENT_OS.command_references_governance("git add CLAUDE.md", worktree))


if __name__ == "__main__":
    unittest.main(verbosity=2)
