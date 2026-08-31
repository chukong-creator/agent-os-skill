# Agent OS v0.6 Project Intelligence

## Purpose

Delivery evidence proves one change. Project Intelligence determines whether a
failure leaves the repository safer for the next change. It does not replace
project-native architecture, tests, Rules, ADRs, or Skills, and it does not
force every project into the same directory tree.

## Work types and maintenance cost

Every new v0.6 Work Package declares one work type: `feature`, `bugfix`,
`maintenance`, `refactor`, `research`, or `release`.

Declare each lasting maintenance increase with:

```text
--maintenance-delta CATEGORY::DESCRIPTION
--maintenance-owner OWNER
--maintenance-rationale WHY_NEEDED
--maintenance-removal EXIT_CONDITION
--maintenance-rollback RECOVERY_PATH
```

Categories are dependency, permission, background work, setting/flag,
persisted state, and external service. Permission, persisted-state, and
external-service deltas cannot use L0. This is a cost declaration, not proof
that the design is worthwhile; Codex still judges the tradeoff.

## Bug to Knowledge

A bug-fix package freezes the reproducible pre-fix symptom. After PASS Evidence
is bound to the exact candidate commit, Codex records:

```text
reproduction -> root cause -> regression evidence -> sibling-risk search
             -> test | rule | skill | adr | none
```

Use `test` by default for executable behavior. Promote to `rule` only for a
non-derivable product, safety, or architecture boundary; to `skill` for a
repeatable multi-step procedure; and to `adr` for a durable structural choice.
`none` is valid with a concrete reason for a local or non-repeatable defect.
One Run never changes durable policy automatically.

`knowledge-record` writes an ignored exact-Run assessment. At ACCEPTED review,
Agent OS adds the sanitized entry to the tracked failure corpus and commits it
with the Codex Review. Raw logs, credentials, and private payloads do not belong
in the corpus.

## Knowledge health

Projects declare `project_intelligence` in `.agent-os/project.json`:

- architecture sources with role and `last_validated` date;
- knowledge sources with the same metadata;
- one or more work-unit verify entrypoints;
- a project-local failure corpus path;
- a freshness budget in days.

Run:

```bash
agent-os knowledge-doctor <project-root> --strict
```

The audit is read-only. It checks missing or stale sources, incomplete metadata,
broken verify executables, corpus shape, duplicate Run identities, and invalid
dispositions. It does not resolve semantic conflicts; Codex or the user must
reconcile meaning before removing a load-bearing rule.
