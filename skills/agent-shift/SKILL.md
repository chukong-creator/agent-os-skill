---
name: agent-shift
description: Initialize, operate, inspect, and evolve governed Codex-Claude Code multi-agent collaboration across software projects. Use when Codex should act as product or technical director, Claude Code should implement and rework, either system should delegate to subagents or background agents, work must hand off around Codex limits, or a project needs Git baselines, isolated Agent worktrees, merge gates, observable state, activity logs, and collaboration health checks.
---

# Agent Shift

Run Codex and Claude Code as a governed delivery team on a Git control plane. Keep product judgment and final acceptance with Codex, implementation and normal rework with Claude, and bounded independent work with subagents in isolated worktrees.

When `.agent-os/project.json` exists, use the `$agent-os` Work Package, lock, evidence, Verifier, and Review gates above this Git transport. Agent Shift must not accept a commit that differs from the exact gated branch commit.

## Start with project truth

1. Read the nearest `AGENTS.md`, `CLAUDE.md`, and `.agent-shift/project.json`.
2. Run the doctor before delegating implementation:

```bash
agent-shift doctor <project-root>
```

3. Treat missing Git HEAD, baseline records, or protocol mismatches as blockers. Treat warnings as explicit risk, not proof of readiness.
4. Use `.agent-shift/state.json` as runtime truth. Treat collaboration retrospectives as history, not live state.

For detailed roles, transitions, delegation rules, and escalation policy, read [references/protocol.md](references/protocol.md).

## Initialize a project

Use the deterministic initializer, then patch the generated `project.json` to reflect real work units and verification commands:

```bash
agent-shift init <project-root> --name "Project name"
```

The initializer preserves existing files. It creates missing collaboration artifacts but never overwrites `AGENTS.md` or an existing `CLAUDE.md`.

## Route work by responsibility

- Keep goal, scope, architecture, product tradeoffs, acceptance criteria, review, and `ACCEPTED` with the Codex main agent.
- Give implementation and all ordinary review rework to Claude Code.
- Give Codex subagents bounded research, code-location, independent QA, risk review, or evidence gathering.
- Give Claude subagents independent implementation, test, or investigation packages only when file ownership does not overlap.
- Keep one owner per work package and one writer per repo root. Use Git worktrees for concurrent writers in Git repositories.
- Never let an implementation agent approve its own work.

## Use Git as the execution control plane

1. Establish a reviewed baseline commit on each work unit's protected base branch.
   Install the local protected-main hooks during project setup:

```bash
agent-shift protect-main <project-root> --work-unit <id>
```
2. Record it after the base worktree is clean:

```bash
agent-shift baseline <project-root> --work-unit <id>
```

3. Create a branch and externalized worktree before assigning any write-capable Agent:

```bash
agent-shift worktree-create <project-root> --work-unit <id> --handoff-id H-001 --agent claude
```

The recorded baseline must still equal the protected base HEAD. If governance changed, review it and record a fresh baseline before creating the Worktree.

4. Give Claude the emitted worktree path, branch, baseline commit, and canonical handoff path. Never ask Claude to write in the protected base worktree.
   Additional write-capable subagents receive separate registered worktrees. Their reviewed commits flow into the primary Agent branch, never directly into `main`.
5. Run the merge gate after Claude returns and Codex begins review. If a director-owned Review commit changes the protected base, rerun the gate before acceptance:

```bash
agent-shift merge-gate <project-root> --work-unit <id>
```

6. Set `ACCEPTED` only after the gate passes and independent review passes. Merge through the guarded command, then remove the clean worktree:

```bash
agent-shift merge <project-root> --work-unit <id>
agent-shift worktree-remove <project-root> --work-unit <id>
```

The merge command rejects both Agent-branch drift and base-branch drift after the final gate. Agent OS v0.3 owns rollback validation and execution; after a verified revert it uses `rollback-record` to synchronize Agent Shift to `ROLLED_BACK`. Do not call that mechanical command as a substitute for Agent OS rollback gates.

## Run the delivery loop

1. Codex writes `HANDOFF.md` and `WORK_QUEUE.md`, records the baseline, creates the Agent worktree, then transitions to `CLAUDE_IMPLEMENTING`.
2. Claude implements one authorized package, logs material actions, writes `RETURN.md`, and transitions to `READY_FOR_REVIEW`.
3. Codex or a Codex QA subagent verifies the Agent branch diff, path allowlist, merge conflicts, build, tests, render, and project-specific gates.
4. Codex transitions to:
   - `ACCEPTED` when all gates pass;
   - `CHANGES_REQUESTED` with a review file when implementation needs improvement;
   - `BLOCKED_DECISION` when product, architecture, safety, credential, budget, or irreversible-action judgment is required.
5. Claude owns `CLAUDE_REWORK` in the same Agent branch/worktree; Codex re-verifies afterward. Codex does not normally fix Claude's implementation findings itself.

Use the CLI for auditable transitions and logs:

```bash
agent-shift status <project-root>
agent-shift transition <project-root> CLAUDE_IMPLEMENTING --handoff-id H-001 --note "Package ready"
agent-shift log <project-root> --actor claude --event build --summary "npm run build passed"
```

## Handoff around Codex limits

- At about 70% of the active Codex window, refresh the handoff after every atomic milestone.
- At about 80%, do not start a new large package. Complete the current atomic step, verify it, and transfer ownership.
- At about 90%, stop implementation and preserve state immediately.
- Treat local Codex session `rate_limits` fields as a useful current signal, not a stable public API. Preserve a manual handoff command as fallback.
- Return to Codex only at an atomic checkpoint. Claude must finish or safely pause its current package before ownership changes.

## Evolve the protocol safely

- Measure handoff success, rework rounds, verification failures, role violations, stale sessions, and user interventions.
- Propose protocol changes from repeated evidence, not one unusual run.
- Canary workflow changes in one project before promoting them globally.
- Forward-test workflow changes only in disposable clones or temporary worktrees. Never use a live protected `main` as a skill evaluation surface.
- Auto-adopt low-risk logging or template improvements. Require explicit user approval for changes to safety, permissions, destructive actions, credentials, deployment authority, or role ownership.
- Keep schema and protocol versions in project state. Make migrations explicit and reversible.

## Resources

- `scripts/agent_shift.py`: initialize projects, validate health, inspect state, transition ownership, and append activity.
- `references/protocol.md`: canonical role, state-machine, subagent, evidence, and escalation protocol.
- `assets/*.template`: project-local collaboration templates used by the initializer.
