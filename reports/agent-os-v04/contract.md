# Agent OS v0.4 Governed Delivery Contract

## Objective

Upgrade Agent OS from uniformly heavy v0.3 governance to a proportional v0.4 system that preserves deterministic safety while matching ceremony to risk, verifies expected gain after delivery, and measures its own operating cost.

## Context

- Files, systems, and source material: `skills/agent-os/scripts/agent_os.py`, Agent OS policy assets and references, existing routing and v0.3 end-to-end tests, public README.
- Prior decisions: Codex owns scope, architecture, governance, review, and acceptance; Claude owns ordinary implementation; one canonical worktree has one writer; provider fallback remains finite and process-local.
- Frontline evidence inspected: v0.3 parser, package schema, acceptance gate, maturity builder, merge and rollback path, Run database schema, routing tests, and v0.3 end-to-end suite.
- Core assumptions: risk and urgency are different; low-risk work still needs exact Git and verification truth; delayed product outcomes cannot always block merge.
- Disconfirming evidence to watch for: a lighter lane weakens single-writer or exact-commit safety; outcome states make rollback unsafe; cost metrics require invented token or labor data; migration mutates active Runs.

## Critical boundaries

- In scope: Agent OS v0.4 schema revision, CLI, policies, migration, tests, documentation, and repository release.
- Requires separate authority: changing CC Switch credentials or global provider selection, running production deployments, mutating user projects before their explicit `agent-os upgrade`.
- Safety, privacy, production, or external-state limits: never persist credentials; never infer unavailable token usage; keep fallback finite; keep automatic rollback limited to a clean exact recorded merge HEAD; refuse migration with active writer locks.

## Frozen acceptance criteria

1. **AC-1 — Proportional governance:** New Work Packages support L0, L1, and L2 governance levels whose validation and acceptance gates are observably different, while every level retains single-writer isolation, scoped paths, exact commit evidence, mechanical verification, Codex review, and Merge Gate.
2. **AC-2 — Outcome loop:** L1/L2 packages freeze metric, baseline, target, validation window, and evidence source; merge enters `OUTCOME_PENDING`; a new evidence-backed command records `OUTCOME_CONFIRMED`, `OUTCOME_REFUTED`, or `OUTCOME_INCONCLUSIVE` without rewriting delivery evidence.
3. **AC-3 — Governance economics:** Each delivered Run can produce a deterministic economics artifact containing elapsed timing, verification/review/rework/failure/model-attempt counts and explicit unknown token fields; no unavailable cost is estimated or presented as verified.
4. **AC-4 — Safe evolution:** Explicit v0.2/v0.3 to v0.4 migration creates an SQLite backup, refuses active locks, preserves finite fallback and narrow rollback, and remains idempotent.
5. **AC-5 — Usable release:** Focused v0.4 tests and prior routing/end-to-end regression tests pass; Skill references, examples, metadata, and README describe the shipped behavior without private paths, credentials, or unsupported claims.

## Verification plan

| Criterion | Evidence type | Real path to exercise | Required observation | Evidence path | Role |
|---|---|---|---|---|---|
| AC-1 | executable | create and deliver L0/L1/L2 disposable packages | distinct required fields and gates; shared deterministic safety remains | `reports/agent-os-v04/evidence.md` | gating |
| AC-2 | executable | merge L1 fixture, run outcome checks with hashed evidence | pending then confirmed/refuted/inconclusive state bound to merge and contract | `reports/agent-os-v04/evidence.md` | gating |
| AC-3 | executable + inspection | generate economics after disposable delivery | honest timings/counts, `null` tokens, documented measurement limits | `reports/agent-os-v04/evidence.md` | gating |
| AC-4 | executable | migrate disposable v0.2 and v0.3 databases; exercise rollback and routing | backup, schema 4, idempotence, all prior safety scenarios pass | `reports/agent-os-v04/evidence.md` | gating |
| AC-5 | executable + review | run compile, focused tests, full regressions, link/privacy scans | all commands exit 0 and final review has no open P0/P1 | `reports/agent-os-v04/final-review.md` | gating |

## Non-goals

- Automatically reverting arbitrary historical merges.
- Automatically changing policy from one Outcome or Learning result.
- Estimating token cost when a runtime does not expose trustworthy usage.
- Solving semantic conflicts between unrelated work units through file-path inference alone.
- Replacing user authority for production, privacy, credentials, finance, or irreversible actions.

## Assumed scope

- L0 is for reversible, repository-local changes with no external side effects.
- L1 is the default for normal product development and requires delayed or explicit outcome follow-up.
- L2 is for high-impact work and requires a separately recorded Director Challenge plus full five-question maturity.
- Existing schema revision 3 packages remain governed as L2 until recreated or explicitly migrated by project owners.

## Mutable implementation checklist

- [x] Add v0.4 constants, schema migration, policies, and governance-level validation.
- [x] Add Director Challenge record and L2 readiness gate.
- [x] Make acceptance requirements level-aware.
- [x] Add Outcome Contract, post-merge states, and evidence-bound `outcome-check`.
- [x] Add Run Economics generation and `economics` command.
- [x] Preserve rollback and routing invariants across new states.
- [x] Add focused v0.4 and migration tests; run all regressions.
- [x] Update Skill, references, examples, metadata, and README.
- [x] Record evidence and final criterion review.

## Evidence log

| Time | Classification | Command or action | Exit status | Observation | Artifact |
|---|---|---|---|---|---|
| 2026-07-19 | reviewed | inspected v0.3 parser, schema, gates, maturity, merge, rollback, and tests | 0 | priority does not alter gates; expected gain has no post-merge state; existing safety boundaries are explicit | this contract |
| 2026-07-19 23:14 +0800 | verified | ran v0.4, v0.3, and routing suites plus compile and diff checks | 0 | all frozen acceptance criteria have executable evidence and no open P0/P1 gaps | `evidence.md`, `final-review.md` |
| 2026-07-19 23:16 +0800 | observed | inspected system Skill after user reported stale version | 0 | `~/.codex/skills/agent-os` was a v0.3 copied directory, so repository changes could not propagate | system installation |

## Contract changes

| Time | Change | Trigger | Reason | User confirmation or direct evidence |
|---|---|---|---|---|
| | | user direction / contradiction | | |
| 2026-07-19 23:16 +0800 | add safe legacy-copy migration to installer | direct installation defect | required for AC-5 usable upgrade path; changes installation HOW, not frozen product outcome | user reported system Skill remained v0.3 |
