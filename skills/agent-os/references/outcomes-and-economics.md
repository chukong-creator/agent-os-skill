# Agent OS v0.4 outcomes and governance economics

## Delivery is not the outcome

L1 and L2 Work Packages freeze:

```text
metric
baseline
target
validation_window
evidence_source
```

Merge proves delivery and changes the Run to `OUTCOME_PENDING`. It does not claim the expected gain happened.

Record an outcome only with at least one readable evidence file:

```bash
agent-os outcome-check <project-root> \
  --run run-wp-001-r1 \
  --result CONFIRMED \
  --observed-value "Observed metric value" \
  --evidence-file /path/to/evidence.json \
  --note "How the evidence relates to the target"
```

The result becomes `OUTCOME_CONFIRMED`, `OUTCOME_REFUTED`, or `OUTCOME_INCONCLUSIVE`. An inconclusive Run may be checked again; confirmed and refuted results are terminal. The receipt binds the frozen contract, merge commit, observed value, evidence SHA-256, and Codex decision. It stays in the ignored Run evidence directory and SQLite so it cannot add a metadata commit above the recorded merge and silently disable exact-head rollback.

Outcome evidence supports a decision; it does not make causal attribution automatic. Agent OS never changes durable Policy from one result.

## Governance economics

`agent-os merge` automatically writes `run-economics.json`. Recompute it with:

```bash
agent-os economics <project-root> --run run-wp-001-r1
```

The artifact records:

- total wall-clock delivery time;
- time to first Evidence and last Evidence to Merge;
- observed governance wall-clock ratio when timestamps exist;
- Event, verification, Review, rework, failure, model-attempt, and fallback counts;
- measured verification-command duration;
- current Outcome status.

Wall-clock phases include human wait time and are not labor measurements. Token input/output remain `null` with source `unavailable-from-runtime` unless a future runtime supplies trustworthy per-Run usage. Agent OS must not estimate missing usage and label it verified.

Economics and Outcome artifacts are local Run evidence by default. Teams that export them to a durable store must preserve hashes, privacy boundaries, and the exact Run identity.
