---
name: agent-os
description: Build and operate Agent OS v0.4 for proportional, permission-bounded, outcome-aware multi-agent delivery. Use when Codex directs Claude Code or subagents through risk-tiered work packages, Git worktrees, single-writer locks, evidence, review, finite model fallback, outcomes, governance economics, safe rollback, or Agent OS health checks.
---

# Agent OS

Use Agent OS as the governance and evidence layer above Agent Shift. Keep Git reality, branches, worktrees, and merges in Agent Shift; keep work contracts, Runs, locks, evidence, review, Outcome, and Economics in `.agent-os/`.

## Establish project truth

1. Read the nearest `AGENTS.md`, root `CLAUDE.md`, `.agent-shift/project.json`, and `.agent-os/project.json`.
2. Run both doctors before starting a Work Package:

```bash
agent-shift doctor <project-root>
agent-os doctor <project-root>
```

3. Treat root `CLAUDE.md` as the only durable Claude instruction source. Keep `.claude/settings.json` and `.claude/agents/verifier.md` as runtime adapters, not duplicate policy.
4. Treat Work Package JSON as goal, risk, permission, and Outcome truth; Agent Shift as handoff truth; Git as file-state truth; Evidence plus Codex Review as delivery truth; post-merge Outcome Receipt as gain truth.

Read [references/proportional-governance.md](references/proportional-governance.md) before selecting L0, L1, or L2.
Read [references/protocol.md](references/protocol.md) for states, evidence, roles, and recovery.
Read [references/outcomes-and-economics.md](references/outcomes-and-economics.md) for post-merge validation and cost accounting.
Read [references/director-principles.md](references/director-principles.md) before strategic, ambiguous, or high-impact work.
Read [references/maturity-contract.md](references/maturity-contract.md) for the L2 five-question gate.

## Operate as the Codex Director

- Start from mission and durable user, product, technical, or industry value.
- Separate urgency from risk. Priority never lowers governance level.
- Select the lightest level that honestly covers impact, reversibility, external effects, and authority.
- Give the Builder context, outcome, boundaries, and evidence standards. Do not prescribe every implementation step.
- Inspect live products, code paths, logs, users, and sources; do not accept Agent self-report as result evidence.
- Return ordinary implementation findings to Claude. Keep scope, architecture, governance, and acceptance with Codex.
- Judge delivery and Outcome separately. A merge is not proof that expected gain happened.

## Initialize or upgrade

```bash
agent-os init <project-root> --id <project-id> --name "Project name" --mission "Mission"
```

The initializer preserves existing files and derives work units from `.agent-shift/project.json`. Review `.agent-os/project.json` and `.agent-os/policy/` before committing the governance baseline.

Upgrade v0.2 or v0.3 explicitly:

```bash
agent-os upgrade <project-root>
agent-os doctor <project-root> --strict
```

Upgrade refuses active writer locks, creates an SQLite online backup, validates integrity, updates adapters and policy, and is idempotent. Normal commands never migrate implicitly. Schema revision 3 packages retain legacy full-maturity behavior without retroactive v0.4 Challenge or Outcome requirements.

## Choose governance level

Shared invariants at every level: one writer, isolated worktree, scoped paths, exact commit Evidence, Mechanical Verifier, resolved failures, Codex Review, Merge Gate, finite fallback, and narrow rollback.

- `L0`: reversible repository-local work, no risk factors or external effects. Learning, Maturity, and post-merge Outcome are not mandatory.
- `L1`: normal delivery. Requires mission, decision rationale, and an explicit post-merge Outcome Contract.
- `L2`: high-impact or external-effect delivery. Adds first principles, alternative, tradeoff, rollback check, independent Director Challenge, Learning, and five-question maturity.

High-risk factors such as production, privacy, credentials, migration, deletion, payment, irreversible action, and external effects require L2.

## Create a Work Package

Minimal L0:

```bash
agent-os package-create <project-root> \
  --id wp-001 --work-unit <unit-id> --governance-level L0 \
  --goal "Small observable goal" --expected-gain "Delivery-level gain" \
  --allow app.js --verify "npm test" --rollback-check "npm test"
agent-os package-ready <project-root> --id wp-001
```

Standard L1 adds the decision and Outcome Contract:

```bash
agent-os package-create <project-root> \
  --id wp-001 --work-unit <unit-id> --governance-level L1 \
  --goal "Observable goal" --objective "Bounded objective" \
  --mission-alignment "Why this advances the mission" \
  --priority P1 --expected-gain "Expected user or business gain" \
  --selected-approach "Chosen execution approach" \
  --rationale "Why it fits the evidence and boundaries" \
  --outcome-metric "Metric name" --outcome-baseline "Current value" \
  --outcome-target "Target value" --outcome-validation-window "7 days" \
  --outcome-evidence-source "Analytics export or user study" \
  --allow app.js --verify "npm test" --rollback-check "npm test"
agent-os package-ready <project-root> --id wp-001
```

For L2, add `--risk-factor`, `--first-principles`, `--alternative OPTION::REASON`, `--tradeoff`, and any `--external-side-effect`, then record an independent challenge before `package-ready`:

```bash
agent-os director-challenge <project-root> \
  --package wp-001 --reviewer independent-reviewer --decision PASS \
  --summary "Evidence-backed challenge conclusion" \
  --review-file /path/to/review.md
```

Commit the approved Work Package, Challenge when present, and governance on protected `main` before starting a Run.

## Run the delivery loop

```bash
agent-os run-start <project-root> --package wp-001 --run run-wp-001-r1 --agent claude
agent-os claude-start <project-root> --run run-wp-001-r1
agent-os claude-status <project-root> --run run-wp-001-r1
agent-os verify <project-root> --run run-wp-001-r1
agent-os verifier <project-root> --run run-wp-001-r1
agent-os review <project-root> --run run-wp-001-r1 --decision ACCEPTED --summary "..."
agent-os merge <project-root> --run run-wp-001-r1
```

L2 additionally requires before acceptance:

```bash
agent-os learn <project-root> --run run-wp-001-r1 \
  --outcome no-change --observation "..." --reason "..."
agent-os maturity-report <project-root> --run run-wp-001-r1
```

- Claude owns implementation and ordinary rework in the assigned Agent branch.
- Run start freezes Decision Trace, Permission Manifest, Rollback Plan, and Outcome Contract; L2 also freezes the Director Challenge.
- Mechanical Verifier checks Manifest PASS, exact commit, and evidence hashes. It never fixes or accepts.
- `CHANGES_REQUESTED` returns the same worktree to Claude through `rework-start`.
- L0 merge ends at `MERGED`; L1/L2 merge ends at `OUTCOME_PENDING` and writes Run Economics.

## Route models without losing the writer

When `~/.config/agent-os/model-routing.json` exists, `claude-start` resolves the Run role from read-only CC Switch metadata and injects provider configuration only into that Claude child process. It never mutates the global Provider or stores credentials.

Builder and Reviewer use separate profiles. Only explicit terminal quota/provider failures advance through a finite unique chain. Unknown failures, manual stops, repeated profiles, and exhausted chains never loop. `SUSPECTED_STALL` observes inactivity without starting a second writer.

## Validate Outcome and economics

L1/L2 Outcome requires a hashed evidence file:

```bash
agent-os outcome-check <project-root> --run run-wp-001-r1 \
  --result CONFIRMED --observed-value "Observed value" \
  --evidence-file /path/to/evidence.json --note "Why it supports the result"
agent-os economics <project-root> --run run-wp-001-r1
```

Outcome results are `OUTCOME_CONFIRMED`, `OUTCOME_REFUTED`, or `OUTCOME_INCONCLUSIVE`. Economics records timestamps and counts; unavailable token usage remains `null` and is never estimated.

## Record failures and learning

```bash
agent-os failure-record <project-root> --run <run-id> --stage VERIFYING \
  --category verification --blocker-class model-fixable \
  --symptom "..." --root-cause "..."
agent-os failure-resolve <project-root> --run <run-id> \
  --id <failure-id> --resolution "What changed and why"
```

Use `learn --outcome proposal` only for a repeatable process improvement with hypothesis, effect, metric, and validation window. One Run may propose a rule; it may not auto-edit Policy or Skill.

## Roll back and recover

```bash
agent-os rollback <project-root> --run <run-id> --reason "Why rollback is needed"
agent-os rollback <project-root> --run <run-id> --reason "..." --execute
agent-os recover <project-root>
```

Automatic rollback remains narrow: latest recorded no-ff merge, clean protected branch, exact HEAD, matching accepted commit and Evidence, explicit execute and reason. Outcome metadata does not add a Git commit above the merge. External effects require `--ack-external` and remain `CODE_REVERTED_EXTERNAL_PENDING` until separately verified.

## Evidence discipline

- Save command output, exit code, duration, SHA-256, diff, paths, commit, and timestamp.
- Classify claims as `verified`, `reviewed`, `observed`, or `assumed`; never promote assumptions.
- Keep raw Runs, Outcome Receipts, Economics, SQLite, and routing state local and ignored.
- Keep Work Packages, Policy, Reviews, Challenges, and Improvement Proposals reviewable in Git.
- Do not count disposable tests or migrated legacy work as real v0.4 acceptance packages.

## Resources

- `scripts/agent_os.py`: deterministic control plane and Claude hook endpoint.
- `references/proportional-governance.md`: L0/L1/L2 routing and Challenge rules.
- `references/outcomes-and-economics.md`: post-merge gain and governance-cost contract.
- `references/protocol.md`: canonical states, evidence, and recovery rules.
- `references/director-principles.md`: Codex management doctrine and behavioral gates.
- `references/maturity-contract.md`: L2 five-question contract.
- `references/model-routing.md`: CC Switch-backed finite role routing.
