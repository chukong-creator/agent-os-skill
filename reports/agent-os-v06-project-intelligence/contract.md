# Agent OS v0.6 Project Intelligence Contract

## Objective

Upgrade Agent OS and every currently enrolled control root so verified delivery
also improves the repository's future correctness: bug fixes become bounded
knowledge, maintenance cost is explicit, project knowledge sources are
auditable, and the Agent OS repository is re-verified in clean GitHub runners.

## Context

- Files and systems: Agent OS control-plane code, Skill references, tests,
  GitHub Actions, and the enrolled Vitality Demo, Understand Things, and World
  Now control roots.
- Prior decisions: retain proportional governance, one writer per worktree,
  exact-commit Evidence, independent verification, Codex acceptance, honest
  rollback, and Context Diet.
- Frontline evidence: the current Agent OS repository has local regression
  suites but no GitHub Actions workflow; current learning is Run-local and does
  not mechanically route a bug into test, rule, Skill, ADR, or justified
  no-change; context-doctor does not check project knowledge freshness.
- Core assumption: repository intelligence should be a thin deterministic
  contract above project-native tests and architecture, not a universal folder
  template or a new permanent Agent hierarchy.
- Disconfirming evidence: the upgrade requires unrelated product edits, makes
  small non-bug work heavier, mutates user-owned dirty files, or permits a Run
  to pass without exact-commit delivery evidence.

## Critical boundaries

- In scope: Agent OS v0.6 control plane, documentation, tests, CI, installed
  Skill, and governance-only migration of the three enrolled control roots.
- Requires separate authority: product feature changes, production releases,
  credentials, destructive Git, or publishing project repositories not already
  authorized by this request.
- Preserve all unrelated branches, worktrees, untracked files, World Now's
  active README/site work, and Understand Things' untracked Stories material.

## Frozen acceptance criteria

1. **AC-1 — Bug to Knowledge:** a new bug-fix Work Package cannot be accepted
   without a structured, exact-Run knowledge assessment that records
   reproduction, root cause, regression evidence, sibling-risk search, and one
   justified disposition: test, rule, Skill, ADR, or no durable change.
2. **AC-2 — Complexity honesty:** declared new dependency, permission,
   background work, setting/flag, persisted state/schema, or external service
   requires owner, rationale, removal, and rollback information frozen in the
   Work Package.
3. **AC-3 — Knowledge health:** a read-only project knowledge audit checks
   declared architecture and knowledge sources, source metadata, broken paths,
   validation freshness, verify entrypoints, and failure-corpus structure
   without pretending to resolve semantic conflicts.
4. **AC-4 — Regression-safe release:** v0.3, v0.4, v0.5, routing, Agent Shift,
   and new v0.6 suites pass; strict context audit, compile, diff, install smoke,
   and a clean GitHub Actions workflow are present.
5. **AC-5 — Enrolled migration:** Vitality Demo, Understand Things, and World
   Now report v0.6 configuration and pass Agent OS integrity checks without
   absorbing or overwriting unrelated user work; unsupported product claims
   remain explicit warnings or blockers.

## Verification plan

| Criterion | Evidence type | Real path to exercise | Required observation | Evidence path | Role |
|---|---|---|---|---|---|
| AC-1 | executable | disposable bug-fix Run | missing knowledge blocks review; valid assessment passes and is queryable | `reports/agent-os-v06-project-intelligence/evidence.md` | gating |
| AC-2 | executable | create invalid and valid maintenance-delta packages | incomplete delta fails; complete fields freeze in contract | same | gating |
| AC-3 | executable | disposable sources plus three real control roots | missing/stale/malformed inputs are reported honestly | same | gating |
| AC-4 | executable/review | all repository checks and GitHub workflow review | all local commands exit 0 and workflow covers clean runners | same | gating |
| AC-5 | executable/review | explicit upgrade and doctor on each real project | v0.6 integrity passes and unrelated Git state is unchanged | same | gating |

## Non-goals

- Mandating identical `rules/`, `skills/`, or `docs/` directories in every repo.
- Requiring a separate Test, Review, Product, and Release Agent for every task.
- Automatically adopting a durable rule from one failure.
- Measuring test quality by raw test count or production/test line ratio.

## Assumed scope

- “同步更新到 GitHub” authorizes pushing the Agent OS repository release after
  local acceptance. Project remotes, if any, are handled only when their clean
  governance-only commit can be isolated and verified.

## Mutable implementation checklist

- [x] Add v0.6 schema, package fields, knowledge assessment, and audit command.
- [x] Add regression tests and GitHub Actions.
- [x] Update Skill, references, README, examples, and release visuals.
- [x] Canary the Skill and migrate three enrolled control roots.
- [ ] Record evidence, review, merge, install, push, and verify remote HEAD/content.

## Evidence log

| Time | Classification | Command or action | Exit status | Observation | Artifact |
|---|---|---|---|---|---|
| 2026-08-31 19:13 +0800 | verified | live project doctors and Git status inspection | mixed | Vitality clean; Understand Things has preserved untracked material; World Now has pre-existing tracked drift; Agent OS has no workflow | this contract |
| 2026-08-31 19:44 +0800 | verified | v0.3-v0.6, routing, Agent Shift, compile, context and install regressions | 0 | all local suites and strict context audit passed | `evidence.md` |
| 2026-08-31 19:53 +0800 | verified | migrate and audit all enrolled control roots | mixed by design | Vitality and Understand Things are clean; World Now retains only pre-existing README drift | `evidence.md` |

## Contract changes

| Time | Change | Trigger | Reason | User confirmation or direct evidence |
|---|---|---|---|---|
