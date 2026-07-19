# Agent OS v0.3 governed delivery protocol

## Truth sources

| Concern | Truth |
|---|---|
| Project rules | `AGENTS.md` |
| Claude execution rules | root `CLAUDE.md` |
| Goal, scope, permissions, success | `.agent-os/work-packages/<id>.json` |
| Active cross-Agent handoff | `.agent-shift/state.json` |
| Code reality | Git commit, branch, worktree, diff |
| Run and lock index | `.agent-os/state.db` |
| Execution trace | `.agent-os/runs/<run>/events.jsonl` |
| Per-Run model role | user routing config plus read-only CC Switch provider metadata |
| Factual proof | Evidence Manifest and referenced artifacts |
| Explainability and recovery | Run-local five-question artifacts |
| Acceptance | Five-question Maturity Report plus `.agent-os/reviews/<run>.json` and `.md` |

Human-readable handoff and return files are views. Detect drift; never treat them as a second state store.

## Roles

- User: mission, irreversible action, production, credentials, privacy, finance, and L3 policy decisions.
- Codex main: scope, package approval, architecture, delegation, independent review, rework order, and acceptance.
- Claude: authorized implementation, branch commits, verification, return, and ordinary rework.
- Verifier: adversarial, non-writing verification. It cannot fix or accept.
- Subagents: one bounded output, one owner, and independent review. Write-capable subagents need separate registered worktrees.

CC Switch owns provider storage and credentials. Agent OS may resolve an existing provider read-only and inject it into one child process. It may not change the globally current provider, mutate the CC Switch database, or persist credentials in governance or evidence artifacts. Terminal quota/provider failures may advance only through the finite, pre-authorized role chain; exhaustion becomes `RUNTIME_FAILED`.

## State mapping

Work Package and Run states use `DRAFT`, `READY`, `BUILDING`, `VERIFYING`, `READY_FOR_REVIEW`, `CODEX_REVIEWING`, `CHANGES_REQUESTED`, `REWORK`, `BLOCKED_DECISION`, `EVIDENCE_INCOMPLETE`, `RUNTIME_FAILED`, `LOCK_EXPIRED`, `ACCEPTED`, `MERGED`, `ROLLED_BACK`, `CODE_REVERTED_EXTERNAL_PENDING`, `ROLLBACK_FAILED`, or `CANCELLED`.

Agent Shift remains the active handoff transport. Agent OS synchronizes only supported transitions and records richer package/run states in SQLite.

## Acceptance invariant

An accepted Run must bind the same tuple everywhere:

```text
work_package_id
run_id
baseline_commit
agent_branch
branch_commit
evidence_manifest_sha256
verifier_result
review_decision
merge_gate_result
maturity_report_sha256
learning_outcome
```

If any commit changes after verification, rerun evidence collection, Verifier, and merge gate.
If a director-owned Review commit changes the protected branch after a preliminary gate, rerun the merge gate before acceptance and require the merge command to match its exact base commit.

## Locks and recovery

- One active writer lock per work unit.
- A lock contains owner, Run, worktree, heartbeat, and expiry.
- Hooks reject writes without a matching non-expired lock.
- `recover` reports expired locks, missing worktrees, dirty worktrees, branch drift, and incomplete evidence without mutating them.
- Forced release requires a reason and an activity record. Never auto-remove dirty worktrees.

## Evidence

Mechanical evidence includes full logs, exit codes, hashes, diff, paths, commit, and timestamps. Verifier results are independent evidence, not acceptance.

Research packages also record source URI or path, publisher, access time, version or hash, claim, precise locator, and conflicts. UI packages add desktop/mobile render, console, overflow, and interaction evidence.

## Protected actions

Block production deployment, publishing, credential access, payment/financial action, private-data access, database migration, deletion, destructive Git, protected-branch writes, push, and governance mutation unless the package and user authorization explicitly allow them.

Claude may commit on the authorized Agent branch because audit and merge require commits. It may not commit on the protected base, merge, push, deploy, or alter governance.
