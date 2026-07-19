---
name: agent-os
description: Build and operate Agent OS v0.3 for explainable, permission-bounded, diagnosable, recoverable, and learning multi-agent delivery. Use when Codex directs Claude Code or subagents through structured work packages, Git worktrees, single-writer locks, evidence, independent verification, five-question maturity reports, safe rollback, improvement proposals, or Agent OS health checks.
---

# Agent OS

Use Agent OS as the governance and evidence layer above Agent Shift. Keep Git reality, branches, worktrees, and merges in Agent Shift; keep work contracts, runs, locks, evidence, and review in `.agent-os/`.

## Establish project truth

1. Read the nearest `AGENTS.md`, root `CLAUDE.md`, `.agent-shift/project.json`, and `.agent-os/project.json`.
2. Run both doctors before starting a work package:

```bash
agent-shift doctor <project-root>
agent-os doctor <project-root>
```

3. Treat the root `CLAUDE.md` as the only durable Claude instruction source. Keep `.claude/settings.json` and `.claude/agents/verifier.md` as mechanical runtime adapters, not duplicate policy.
4. Treat Work Package JSON as goal and permission truth, Agent Shift state as active handoff truth, Git as file-state truth, and the Evidence Manifest plus Five-question Maturity Report and Review as acceptance truth.

Read [references/protocol.md](references/protocol.md) for state, evidence, recovery, and role rules.
Read [references/director-principles.md](references/director-principles.md) before scoping strategic, ambiguous, or high-impact work.
Read [references/maturity-contract.md](references/maturity-contract.md) for the five required questions, failure taxonomy, rollback safety, and learning lifecycle.

## Operate as the Codex director

- Start from mission and durable user or industry value. Use AI and computation to expand intelligence, creativity, and experience, not merely to automate activity.
- Set ambitious outcomes, then select the smallest high-leverage package that advances them. Make priority and expected gain explicit.
- Maintain an external and frontline view. Ask what changed outside the organization and what direct product, user, code, or operational evidence says.
- State the first-principles hypothesis and the evidence that could disprove it. Avoid vague confidence.
- Give the Builder context, outcome, boundaries, and evidence standards. Do not prescribe every implementation step.
- Communicate findings and tradeoffs directly. Protect the mission and result, not organizational territory or personal ownership.
- Judge acceptance by substantive user, product, technical, or business gain. Completion of activity is not the result.

## Initialize a project

```bash
agent-os init <project-root> --id <project-id> --name "Project name" --mission "Mission"
```

The initializer preserves existing files and derives work units from `.agent-shift/project.json`. Review `.agent-os/project.json` and `.agent-os/policy/evidence-review.json` before committing the governance baseline.

Upgrade an existing v0.2 control root explicitly. Normal commands never migrate the database implicitly:

```bash
agent-os upgrade <project-root>
agent-os doctor <project-root> --strict
```

The upgrade refuses active writer locks, creates an SQLite online backup, validates integrity, migrates adapters, and is idempotent.

## Create and approve a work package

```bash
agent-os package-create <project-root> \
  --id wp-001 --work-unit <unit-id> \
  --goal "Observable goal" --objective "Bounded objective" \
  --mission-alignment "Why this advances the mission" \
  --priority P1 --expected-gain "Expected user or business gain" \
  --frontline-signal "Direct product or user evidence" \
  --selected-approach "Chosen execution approach" \
  --rationale "Why this approach best fits the evidence and boundaries" \
  --alternative "Rejected option::Reason it was rejected" \
  --tradeoff "Important cost accepted" \
  --external-side-effect "Declared non-Git side effect, if any" \
  --rollback-check "Command that proves rollback health" \
  --allow app.js styles.css \
  --verified "npm run build passes" \
  --reviewed "Product intent remains clear"

agent-os package-ready <project-root> --id wp-001
```

Commit the approved Work Package and project governance on protected `main` through the director-owned path before starting the Run. Never create a Run against a dirty or unrecorded base.

## Run the delivery loop

```bash
agent-os run-start <project-root> --package wp-001 --run run-wp-001-r1 --agent claude
agent-os claude-start <project-root> --run run-wp-001-r1
agent-os claude-status <project-root> --run run-wp-001-r1
agent-os heartbeat <project-root> --run run-wp-001-r1
agent-os verify <project-root> --run run-wp-001-r1
agent-os verifier <project-root> --run run-wp-001-r1
agent-os learn <project-root> --run run-wp-001-r1 \
  --outcome no-change --observation "..." --reason "..."
agent-os maturity-report <project-root> --run run-wp-001-r1
agent-os review <project-root> --run run-wp-001-r1 --decision ACCEPTED --summary "..."
agent-os merge <project-root> --run run-wp-001-r1
```

- Claude owns implementation and ordinary rework in the assigned Agent branch.
- When `~/.config/agent-os/model-routing.json` exists, `claude-start` resolves the Run role from the user's CC Switch database and injects that provider only into the Claude child process. It never changes CC Switch's current provider or writes credentials into commands, files, Work Packages, events, or logs.
- Without a routing config, `claude-start` remains backward compatible and inherits the user's existing Claude Code provider. Use `--profile inherit` to request that behavior explicitly when routing is configured.
- `BUILDING` and `REWORK` automatically use the default `builder` profile. `READY_FOR_REVIEW` and `CODEX_REVIEWING` automatically use `reviewer` with only `Read`, `Glob`, and `Grep`. A detached supervisor advances through the finite, unique role-specific fallback chain only after an explicit terminal quota/provider failure; unknown failures, manual stops, repeated profiles, and exhausted chains never loop. Long-running sessions become observable as `SUSPECTED_STALL` without starting a second writer.
- Inspect secret-safe routing metadata with `agent-os provider-list` and `agent-os route-resolve [--profile <name>]`.
- Claude may commit coherent milestones on the authorized Agent branch. It may not commit to protected `main`, merge, push, deploy, or alter governance.
- The mechanical verifier never fixes implementation and never accepts its own output.
- Run start freezes `decision-trace.json`, `permission-manifest.json`, and `rollback-plan.json` from the approved Work Package and current policy.
- Codex submits the Review. `ACCEPTED` requires passing Evidence, Verifier, exact commit, no unresolved failures, Learning Assessment, Five-question Maturity Report, and a post-Review Agent Shift merge gate.
- Use `CHANGES_REQUESTED` to return the same worktree to Claude. Do not make Codex perform normal rework.

Record and close failures without erasing history:

```bash
agent-os failure-record <project-root> --run <run-id> --stage VERIFYING \
  --category verification --blocker-class model-fixable \
  --symptom "..." --root-cause "..."
agent-os failure-resolve <project-root> --run <run-id> \
  --id <failure-id> --resolution "What changed and why it resolves the failure"
```

Use `learn --outcome proposal` with hypothesis, proposed change, expected effect, metric, and validation window when a repeatable process improvement is justified. Proposals start at `PROPOSED`; never auto-edit Policy or Skill from one Run.

## Roll back safely

Inspect first, then execute only with explicit authority:

```bash
agent-os rollback <project-root> --run <run-id> --reason "Why rollback is needed"
agent-os rollback <project-root> --run <run-id> --reason "..." --execute
```

The v0.3 automatic path only reverts the latest recorded no-ff merge on a clean protected branch, verifies commit parentage and evidence identity, creates a new revert commit, runs rollback checks, writes a tracked Receipt, synchronizes Agent Shift, and refreshes the baseline. If external side effects were declared, `--ack-external` is required and the result remains `CODE_REVERTED_EXTERNAL_PENDING`; Git never claims external recovery.

## Recover safely

```bash
agent-os recover <project-root>
agent-os lock-release <project-root> --work-unit <unit-id> --reason "Verified stale owner"
```

`recover` is read-only. Forced lock release is a Codex or user action and requires a reason. Never delete a dirty worktree during recovery.

## Evidence discipline

- Save full command output, exit code, SHA-256, Git diff, changed paths, branch commit, and capture time.
- Classify evidence as `verified`, `reviewed`, `observed`, or `assumed`.
- Never convert an assumption into an observation.
- Keep raw run files local and ignored; keep Work Packages, policy, and Reviews reviewable in Git.
- Do not count disposable tests or migrated legacy work as real v0.3 acceptance packages.

## Resources

- `scripts/agent_os.py`: deterministic control plane and Claude hook endpoint.
- `references/protocol.md`: canonical Phase 0 contracts, states, evidence, and recovery rules.
- `references/director-principles.md`: Codex management doctrine and behavioral gates.
- `references/maturity-contract.md`: five-question artifact, failure, rollback, and learning contract.
- `references/model-routing.md`: CC Switch-backed per-Run routing, isolation, and finite fallback.
- `assets/verifier.md`: project-local independent Verifier role.
