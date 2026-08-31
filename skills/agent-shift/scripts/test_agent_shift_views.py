#!/usr/bin/env python3
"""Focused regression tests for Agent Shift derived runtime views."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("agent_shift.py")
SPEC = importlib.util.spec_from_file_location("agent_shift", SCRIPT)
assert SPEC and SPEC.loader
agent_shift = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_shift)


class WorkQueueViewTests(unittest.TestCase):
    def state(self, **updates: object) -> dict[str, object]:
        value: dict[str, object] = {
            "protocol_version": 2,
            "handoff_id": "run-v2-r2",
            "status": "CLAUDE_IMPLEMENTING",
            "owner": "claude",
            "active_work_unit": "app",
            "active_work_package": "wp-v2-r2",
            "agent_branch": "agent/claude/app/run-v2-r2",
            "worktree_path": "/tmp/worktree",
            "merge_commit": None,
            "updated_at": "2026-07-22T12:00:00+08:00",
        }
        value.update(updates)
        return value

    def test_active_queue_is_derived_from_state(self) -> None:
        rendered = agent_shift.render_work_queue(self.state())
        self.assertIn("`CLAUDE_IMPLEMENTING`", rendered)
        self.assertIn("`wp-v2-r2`", rendered)
        self.assertIn(agent_shift.WORK_QUEUE_MARKER, rendered)

    def test_terminal_state_has_no_active_package(self) -> None:
        rendered = agent_shift.render_work_queue(
            self.state(status="ACCEPTED", owner="codex", merge_commit="abc123")
        )
        self.assertIn("None. Current state is `ACCEPTED`.", rendered)
        self.assertIn("- Merge commit: `abc123`", rendered)

    def test_sync_and_drift_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.state()
            path = agent_shift.sync_work_queue(root, state)
            self.assertEqual(agent_shift.read_work_queue_metadata(path), agent_shift.work_queue_metadata(state))

            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if line.startswith(f"<!-- {agent_shift.WORK_QUEUE_MARKER} "):
                    marker = json.loads(line.split(" ", 2)[2][:-4])
                    marker["status"] = "SCOPED"
                    lines[index] = (
                        f"<!-- {agent_shift.WORK_QUEUE_MARKER} "
                        f"{json.dumps(marker, ensure_ascii=False, separators=(',', ':'), sort_keys=True)} -->"
                    )
                    break
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertNotEqual(agent_shift.read_work_queue_metadata(path), agent_shift.work_queue_metadata(state))

    def test_active_execution_requires_one_live_session(self) -> None:
        live = [{"name": "builder", "state": "working"}]
        self.assertEqual(
            agent_shift.evaluate_active_execution(self.state(), live, False),
            ("PASS", "active Claude state has exactly one live worktree session"),
        )
        level, message = agent_shift.evaluate_active_execution(self.state(), [], True)
        self.assertEqual(level, "FAIL")
        self.assertIn("partial changes", message)
        level, message = agent_shift.evaluate_active_execution(
            self.state(agent_branch="agent/codex-subagent/app/run-v2-r2"), live, True,
        )
        self.assertEqual(level, "FAIL")
        self.assertIn("executor identity", message)

    def test_active_execution_query_uses_recorded_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree = Path(temporary)
            state = self.state(worktree_path=str(worktree))
            with (
                mock.patch.object(
                    agent_shift,
                    "query_claude_sessions",
                    return_value=("PASS", "ok", [{"state": "working"}]),
                ) as query,
                mock.patch.object(agent_shift, "run_command", return_value=(0, "")),
            ):
                result = agent_shift.check_active_execution(state)
            self.assertEqual(result, ("PASS", "active Claude state has exactly one live worktree session"))
            query.assert_called_once_with(worktree)


if __name__ == "__main__":
    unittest.main()
