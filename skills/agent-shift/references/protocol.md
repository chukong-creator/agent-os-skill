# Agent Shift protocol

## Contents

- Role model
- State machine
- Subagent routing
- Evidence contract
- Review and rework
- Escalation and exceptions
- Evolution governance
- Git baseline, Agent worktree, and merge gate

## Role model

### Codex main agent: product and technical director

- Own goals, scope, product and architecture decisions, work decomposition, risk, review, and final acceptance.
- Dispatch bounded tasks to Codex subagents and consolidate their evidence.
- Write structured review findings instead of taking over routine implementation.
- Be the only role allowed to set `ACCEPTED`.

### Claude Code: implementation lead

- Own authorized implementation and all ordinary rework.
- Read project rules and the current handoff before editing.
- Run declared verification commands and return evidence.
- Escalate product, architecture, safety, credential, budget, and irreversible-action decisions.

### Subagents

- Codex subagents: research, repository mapping, independent QA, security/risk review, or bounded analysis.
- Claude subagents: independent implementation, tests, or investigation within disjoint file ownership.
- Give every subagent one owner, one output contract, a bounded context, allowed actions, a feedback oracle, and a stop condition.
- Keep producer and reviewer separate. A subagent cannot accept its own output.
- Do not parallelize dependent work or allow two writers in the same repo root without worktree isolation.

## Git baseline, Agent worktree, and merge gate

- Treat the protected base branch as accepted organizational memory, not an implementation workspace.
- Install tracked protected-main hooks. Normal Agent commits, merge commits, and pushes on `main` must fail closed; only the Codex main agent's guarded commands may explicitly unlock the required operation.
- Require one reviewed baseline commit per work unit before delegation.
- Give every write-capable Agent a dedicated branch and worktree. Read-only agents may inspect the base tree without changing it.
- Register every worktree in runtime `worktrees.json`. Keep `state.json` pointed at the primary delivery branch while retaining additional bounded subagent branches in the registry.
- Merge or cherry-pick reviewed subagent commits into the primary Agent branch first. Subagent branches never merge directly to protected `main`; the final primary branch passes one aggregate merge gate.
- Bind every package to exactly one `repo_root`, baseline commit, Agent branch, worktree, path allowlist, and verification set.
- Keep runtime state and logs outside tracked Agent branches. Track stable protocol and product truth; ignore live state, activity, worktrees, and gate output.
- Require the merge gate to prove: branch has commits, diff has no whitespace errors, merge is conflict-free, changed paths stay in the allowlist, worktree is clean, and declared checks pass.
- Require independent Codex review after the mechanical gate. A passing build is not product acceptance.
- Permit only Codex main agent to set `ACCEPTED` and merge the exact gated commit. If either the Agent branch or protected base moves afterward, invalidate the gate.
- Preserve branches and commits as audit history. Remove only clean worktrees after merge; never force-remove user work.
- Record `ROLLED_BACK` only after Agent OS verifies commit identity, explicit authority, revert result, rollback checks, Receipt, and external-side-effect status. Agent Shift never performs the revert itself.

## State machine

| State | Owner | Required artifact |
| --- | --- | --- |
| `SCOPED` | Codex | handoff, queue, acceptance criteria |
| `CLAUDE_IMPLEMENTING` | Claude | activity and implementation evidence |
| `READY_FOR_REVIEW` | Codex | return report and verification results |
| `CODEX_REVIEWING` | Codex | independent review evidence |
| `CHANGES_REQUESTED` | Claude | structured review file |
| `CLAUDE_REWORK` | Claude | rework evidence and regression checks |
| `BLOCKED_DECISION` | Codex | decision question, options, impact |
| `ACCEPTED` | Codex | final acceptance and evidence links |
| `ROLLED_BACK` | Codex | Agent OS verified revert commit and receipt |
| `CODE_REVERTED_EXTERNAL_PENDING` | Codex | code revert verified; declared external recovery is still unverified |
| `ROLLBACK_FAILED` | Codex | code revert exists but rollback verification or synchronization failed |

Allowed transitions are enforced by `scripts/agent_shift.py`.

## Evidence contract

Do not infer collaboration health from the final artifact alone. Require:

1. Rules: project `AGENTS.md`, `CLAUDE.md`, and `project.json` agree.
2. Ownership: `state.json` identifies one current owner and work package.
3. Session: Claude background or transcript state can be located when Claude owns work.
4. Trace: activity records tool use, verification, failure, stop, and handoff events.
5. Change: a recorded baseline, Agent branch, isolated worktree, and Git diff show what changed.
6. Return: Claude supplies changes, checks, risks, and unresolved decisions.
7. Gate: mechanical merge checks pass for the exact Agent commit.
8. Review: Codex supplies independent findings and the next state.

## Review and rework

Each review finding must contain:

- stable finding id and severity;
- observed evidence;
- expected behavior;
- allowed files or work unit;
- required verification commands;
- pass condition.

When review fails, set `CHANGES_REQUESTED` and give the finding back to Claude. Codex may directly edit implementation only for immediate safety containment, user-authorized emergency takeover when Claude is unavailable, or files owned exclusively by Codex. Log every exception.

## Escalation and exceptions

Keep the user out of routine operation. Escalate only when:

- product direction or scope materially changes;
- an irreversible, production, credential, privacy, security, or financial action is required;
- the same finding fails three review cycles;
- required infrastructure remains unavailable after bounded recovery attempts;
- user-owned dirty work cannot be safely isolated.

## Evolution governance

Track handoff success, first-pass verification rate, rework count, role violations, stale locks, agent failures, time to acceptance, and user interventions. Generate improvement candidates from repeated patterns. Test in one project, compare evidence, then promote or roll back. Never silently expand permissions or deployment authority.

Run protocol forward tests only in disposable clones or temporary worktrees. A validation agent must never modify, commit, baseline, merge, or migrate a live protected `main`.
