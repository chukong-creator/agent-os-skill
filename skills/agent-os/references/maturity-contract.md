# Agent OS v0.4 five-question maturity contract

## Scope

The five-question contract is mandatory for new `L2` Runs and preserved for legacy v0.3 Runs. `L0` and `L1` still retain delivery evidence, permissions, failures, and recovery data, but do not need to synthesize a full Maturity Report before acceptance.

## The five required answers

An `L2` Run answers five questions from inspectable artifacts bound to one `run_id` and accepted `branch_commit`.

| Question | Truth artifact | Minimum content |
|---|---|---|
| Why did it act this way? | `decision-trace.json` | selected approach, rationale, rejected alternatives, tradeoffs, first-principles basis |
| What permission did it use? | `permission-manifest.json` | worktree, branch, lock, granted paths/actions, denied paths/actions, authority source |
| Where did it fail? | `failures.json` plus SQLite `failures` | stage, category, symptom, honest root cause, blocker class, evidence, resolution |
| How can it roll back? | `rollback-plan.json` and optional `rollback-receipt.json` | baseline, merge commit, strategy, checks, external effects, executed result |
| Why will next time be better? | `learning-assessment.json` and optional Improvement Proposal | observation, reason, no-change or falsifiable proposal, metric, validation window |

`maturity-report.json` binds these artifacts by SHA-256 and restates their answers. It is a computed view, not a second source of authority.

## Failure taxonomy

Use one category: `goal_contract`, `context`, `permission`, `implementation`, `verification`, `dependency`, `runtime`, `merge`, `external_service`, `governance`, or `unknown`.

Use one blocker class:

- `model-fixable`: normal implementation or process rework can resolve it.
- `contradiction`: requirements or states conflict; diagnose before more patching.
- `unverifiable`: the claimed result lacks an honest feedback oracle.
- `new-authority-required`: credentials, production, privacy, finance, irreversible action, or scope expansion requires the user or another authority.

Automatic failure capture may state that diagnosis is pending. It must not invent a root cause. `ACCEPTED` requires every recorded failure to be explicitly resolved with the resolution commit retained.

## Rollback invariant

Automatic rollback is intentionally narrow. It accepts a delivered Run in `MERGED` or an outcome state, and still requires the recorded merge commit, clean protected base, `HEAD == merge_commit`, exactly two merge parents, second parent equal to the accepted branch commit, consistent Agent Shift state, no active writer, passing accepted evidence, explicit `--execute`, and a reason.

Rollback uses `git revert -m 1`; destructive reset is forbidden. A failed revert is aborted and recorded. A successful code revert is not proof of external recovery. Declared external effects require acknowledgement and remain pending until separately verified.

## Learning lifecycle

Use `Observation -> Hypothesis -> Proposal -> Experiment -> Adopt or Reject` for `L2` Runs or whenever a lighter Run reveals a durable governance defect.

- `no-change` is valid only with a reason explaining why the Run did not reveal a repeatable defect.
- A proposal begins at `PROPOSED` and declares risk `L1`, `L2`, or `L3`, expected effect, metric, and validation window.
- One Run may propose a rule; it may not automatically alter durable Policy, Skill, production configuration, or user authority.
- Adoption requires later evidence and Codex or user decision appropriate to the risk.

## Acceptance invariant

Every level requires Evidence Manifest PASS, Verifier PASS, exact commit match, no open failure, Codex Review, and a Merge Gate rerun after any director-owned Review commit changes the protected branch.

Before an `L2` Run reaches `ACCEPTED`, additionally require a valid Director Challenge, Learning Assessment, and Maturity Report PASS. Lighter levels may generate these artifacts voluntarily, but their absence is not a failed gate.
