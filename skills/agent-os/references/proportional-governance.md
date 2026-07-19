# Agent OS v0.4 proportional governance

Governance level expresses delivery risk, not urgency. Priority remains `P0` to `P3`; it never lowers the required controls.

## Shared invariants

Every level preserves:

- one writer per canonical worktree;
- Git baseline, isolated Agent branch, and scoped paths;
- exact branch commit, Evidence Manifest, and Mechanical Verifier;
- no unresolved failures before acceptance;
- Codex Review and Agent Shift Merge Gate;
- finite provider fallback and narrow exact-head rollback.

## Levels

| Level | Use when | Additional requirements | Deliberately omitted |
|---|---|---|---|
| `L0` | reversible, repository-local, no risk factors or external effects | delivery-level expected gain | mandatory Learning, Maturity Report, post-merge Outcome |
| `L1` | normal product or technical delivery | mission, rationale, explicit Outcome Contract, Run Economics | mandatory Director Challenge and five-question maturity |
| `L2` | production, privacy, credentials, migration, deletion, payment, irreversible or external effects | first principles, rejected alternative, tradeoff, rollback check, independent Director Challenge, Learning, five-question maturity | nothing from the full governed path |

The deterministic validator rejects L0 with any risk factor or external side effect. It rejects non-L2 packages with production, privacy, credentials, database migration, data deletion, payment, irreversible, or external-side-effect risk factors.

## L2 Director Challenge

The challenge occurs while a package is `DRAFT`:

```bash
agent-os director-challenge <project-root> \
  --package wp-001 \
  --reviewer independent-reviewer \
  --decision PASS \
  --summary "Why the Director decision survives challenge" \
  --finding "Residual risk" \
  --review-file /path/to/review.md
```

The command hashes the review file and binds the result to a digest of the current Work Package. `package-ready` rejects a missing, non-PASS, self-labelled Codex, unhashed, or stale challenge. This proves artifact separation and package identity; it does not prove the real-world identity or quality of the reviewer.

## Legacy behavior

Schema revision 3 packages continue as full-maturity legacy L2 packages after explicit upgrade. They do not retroactively require a v0.4 Director Challenge or post-merge Outcome Contract. New packages use schema revision 4.
