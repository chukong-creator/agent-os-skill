#!/usr/bin/env python3
"""Regression tests for Agent OS v0.5 context engineering on v0.6."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


AGENT_OS = Path(__file__).with_name("agent_os.py")
AGENT_SHIFT = AGENT_OS.parents[2] / "agent-shift" / "scripts" / "agent_shift.py"


def call(*args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(AGENT_OS), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"expected exit {expected}, got {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(
            f"command failed: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def test_clean_context_passes(root: Path) -> None:
    project = root / "clean"
    project.mkdir()
    write(
        project / "AGENTS.md",
        "# Project context\n\n"
        "- Preserve the signed fixture because tests cannot reconstruct it.\n"
        "- Use [verification](references/verification.md) for release checks.\n",
    )
    write(project / "references" / "verification.md", "# Verification\n\nRun the project test suite.\n")
    skill = project / "skills" / "demo" / "SKILL.md"
    write(skill, "# Demo\n\nRead [details](references/details.md) only when this Skill applies.\n")
    write(skill.parent / "references" / "details.md", "# Details\n")

    result = call(
        "context-doctor", str(project), "--skill", str(skill), "--strict", "--json"
    )
    report = json.loads(result.stdout)
    assert report["agent_os_version"] == "0.6"
    assert report["mutated"] is False
    assert report["status"] == "PASS"
    assert report["summary"]["files"] == 2


def test_duplicates_and_budget_are_strict_warnings(root: Path) -> None:
    project = root / "warnings"
    project.mkdir()
    global_agents = root / "global" / "AGENTS.md"
    repeated = "Never expose credentials, tokens, private keys, or environment secrets."
    write(global_agents, f"# Global\n\n- {repeated}\n")
    write(
        project / "AGENTS.md",
        "# Project\n\n"
        f"- {repeated}\n"
        "- This line deliberately pushes the configured test budget.\n",
    )

    result = call(
        "context-doctor", str(project),
        "--include-global", "--global-agents", str(global_agents),
        "--max-project-lines", "3", "--json",
    )
    report = json.loads(result.stdout)
    codes = {item["code"] for item in report["findings"]}
    assert report["status"] == "WARN"
    assert {"DUPLICATE_INSTRUCTION", "CONTEXT_BUDGET_EXCEEDED"} <= codes

    call(
        "context-doctor", str(project),
        "--include-global", "--global-agents", str(global_agents),
        "--max-project-lines", "3", "--strict",
        expected=1,
    )


def test_broken_reference_fails_closed(root: Path) -> None:
    project = root / "broken"
    project.mkdir()
    write(
        project / "AGENTS.md",
        "# Project\n\nRead [the missing release policy](references/release.md).\n",
    )
    result = call("context-doctor", str(project), "--json", expected=1)
    report = json.loads(result.stdout)
    assert report["status"] == "FAIL"
    assert report["findings"][0]["code"] == "BROKEN_CONTEXT_REFERENCE"

    result = call(
        "context-doctor", str(project),
        "--skill", str(project / "missing-skill" / "SKILL.md"),
        "--json", expected=1,
    )
    report = json.loads(result.stdout)
    assert "MISSING_CONTEXT_INPUT" in {item["code"] for item in report["findings"]}


def test_v04_project_upgrades_explicitly(root: Path) -> None:
    project = root / "upgrade"
    project.mkdir()
    run(["git", "init", "-b", "main"], project)
    run(["git", "config", "user.name", "Agent OS Test"], project)
    run(["git", "config", "user.email", "agent-os@example.test"], project)
    write(project / "README.md", "# Upgrade fixture\n")
    run(["git", "add", "README.md"], project)
    run(["git", "commit", "-m", "baseline"], project)
    run([sys.executable, str(AGENT_SHIFT), "init", str(project), "--name", "Upgrade fixture"], project)
    call("init", str(project), "--id", "upgrade-fixture", "--name", "Upgrade fixture", "--mission", "Test v0.4 migration")

    config_path = project / ".agent-os" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["agent_os_version"] = "0.4"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    result = call("upgrade", str(project))
    report = json.loads(result.stdout)
    assert report["from"] == "0.4"
    assert report["to"] == "0.6"
    assert report["database_backup"]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-os-v05-") as temporary:
        root = Path(temporary)
        test_clean_context_passes(root)
        test_duplicates_and_budget_are_strict_warnings(root)
        test_broken_reference_fails_closed(root)
        test_v04_project_upgrades_explicitly(root)
    print("Agent OS v0.5 context regressions passed on v0.6: 4 scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
