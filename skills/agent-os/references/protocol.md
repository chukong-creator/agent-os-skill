# Agent OS v0.4 governed delivery protocol

## Truth sources

| Concern | Truth |
|---|---|
| Project rules | `AGENTS.md` |
| Claude execution rules | root `CLAUDE.md` |
| Goal, scope, permissions, success, governance level | `.agent-os/work-packages/<id>.json` |
| Active cross-Agent handoff | `.agent-shift/state.json` |
| Code reality | Git commit, branch, worktree, diff |
| Run, lock, outcome, and economics index | `.agent-os/state.db` |
| Execution trace | `.agent-os/runs/<run>/events.jsonl` |
| Per-Run model role | user routing config plus read-only CC Switch provider metadata |
| Factual proof | Evidence Manifest and referenced artifacts |
| L2 explainability and recovery | Run-local five-question artifacts |
| Delivery acceptance | Evidence, Verifier, Review, and Merge Gate bound to one commit |
| Outcome | frozen Outcome Contract plus hashed post-merge observation |
| Governance cost | computed Run Economics artifact |

Human-readable handoff and return files are views. Detect drift; never treat them as a second state store.

## Proportional governance

Use the lightest level that honestly contains the risk:

| Level | Intended use | Additional gates |
|---|---|---|
| `L0` | small, local, reversible change with no external effect | compact package; outcome follow-up and five-question maturity are not required |
| `L1` | ordinary product or code delivery with measurable expected gain | frozen Outcome Contract and post-merge outcome check |
| `L2` | production, privacy, credentials, migrations, deletion, payment, irreversible or external-side-effect work | full decision context, independent Director Challenge, Outcome Contract, learning, and five-question maturity |

Declared high-risk factors or external side effects force `L2`. Urgency never lowers the governance level. Every level retains the same deterministic safety floor: one writer, isolated worktree, path allowlist, exact commit, independent verifier, Codex decision, and merge gate.

## Roles

- User: mission, irreversible action, production, credentials, privacy, finance, and durable policy decisions.
- Codex main: scope, level selection, package approval, architecture, delegation, independent review, rework order, and acceptance.
- Claude: authorized implementation, branch commits, verification, return, and ordinary rework.
- Verifier: adversarial, non-writing verification. It cannot fix or accept.
- Director Challenger: for `L2`, independently tests the scope, alternatives, assumptions, reversibility, and evidence plan before work starts. It cannot approve its own package as Codex/director.
- Subagents: one bounded output, one owner, and independent review. Write-capable subagents need separate registered worktrees.

CC Switch owns provider storage and credentials. Agent OS may resolve an existing provider read-only and inject it into one child process. It may not change the globally current provider, mutate the CC Switch database, or persist credentials in governance or evidence artifacts. Terminal quota/provider failures may advance only through the finite, pre-authorized role chain; exhaustion becomes `RUNTIME_FAILED`.

## State mapping

Work Package and Run states use `DRAFT`, `READY`, `BUILDING`, `VERIFYING`, `READY_FOR_REVIEW`, `CODEX_REVIEWING`, `CHANGES_REQUESTED`, `REWORK`, `BLOCKED_DECISION`, `EVIDENCE_INCOMPLETE`, `RUNTIME_FAILED`, `LOCK_EXPIRED`, `ACCEPTED`, `MERGED`, `OUTCOME_PENDING`, `OUTCOME_CONFIRMED`, `OUTCOME_REFUTED`, `OUTCOME_INCONCLUSIVE`, `ROLLED_BACK`, `CODE_REVERTED_EXTERNAL_PENDING`, `ROLLBACK_FAILED`, or `CANCELLED`.

`L0` ends delivery at `MERGED`. New `L1` and `L2` Runs enter `OUTCOME_PENDING`; a hashed observation moves them to a terminal or revisitable outcome state. Delivery acceptance and outcome confirmation remain separate claims.

Agent Shift remains the active handoff transport. Agent OS synchronizes only supported transitions and records richer package/run states in SQLite.

## Acceptance invariant

Every accepted Run binds the same delivery tuple everywhere:

```text
work_package_id
run_id
governance_level
baseline_commit
agent_branch
branch_commit
evidence_manifest_sha256
verifier_result
review_decision
merge_gate_result
```

An `L2` Run also binds `director_challenge_sha256`, `maturity_report_sha256`, and `learning_outcome`. An `L1` or `L2` outcome claim binds the frozen metric, baseline, target, validation window, evidence source, observed value, evidence SHA-256, and result.

If any commit changes after verification, rerun evidence collection, Verifier, and merge gate. If a director-owned Review commit changes the protected branch after a preliminary gate, rerun the merge gate before acceptance and require the merge command to match its exact base commit.

## Locks and recovery

- One active writer lock per work unit.
- A lock contains owner, Run, worktree, heartbeat, and expiry.
- Hooks reject writes without a matching non-expired lock.
- `recover` reports expired locks, missing worktrees, dirty worktrees, branch drift, and incomplete evidence without mutating them.
- Forced release requires a reason and an activity record. Never auto-remove dirty worktrees.

## Evidence and economics

Mechanical evidence includes full logs, exit codes, hashes, diff, paths, commit, and timestamps. Verifier results are independent evidence, not acceptance.

Research packages also record source URI or path, publisher, access time, version or hash, claim, precise locator, and conflicts. UI packages add desktop/mobile render, console, overflow, and interaction evidence.

Run Economics measures observed wall-clock time, time to first evidence, verification time, event and retry counts, routing attempts, fallbacks, and observable governance overhead. Token usage remains `null` when the runtime does not expose trusted usage; Agent OS never invents it.

## Protected actions

Block production deployment, publishing, credential access, payment/financial action, private-data access, database migration, deletion, destructive Git, protected-branch writes, push, and governance mutation unless the package and user authorization explicitly allow them. These risk factors require `L2`.

Claude may commit on the authorized Agent branch because audit and merge require commits. It may not commit on the protected base, merge, push, deploy, or alter governance.
