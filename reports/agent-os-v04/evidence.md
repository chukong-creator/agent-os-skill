# Agent OS v0.4 Evidence

Recorded at `2026-07-19 23:14:07 +0800` on branch `codex/agent-os-v04`, based on `b139cc2`.

## Executable gates

| Command | Exit | Classification | Observed result |
|---|---:|---|---|
| `python3 skills/agent-os/scripts/test_agent_os_v04.py` | 0 | verified | 12 scenarios PASS: L0 lightweight; high risk forces L2; L1 frozen Outcome Contract; inconclusive, confirmed, and refuted outcomes; outcome-safe rollback; L2 Challenge and maturity; honest economics; v0.3 migration; active-lock migration refusal. |
| `python3 skills/agent-os/scripts/test_agent_os_v03.py` | 0 | verified | 11 regression scenarios PASS, including v0.2 migration, failure resolution, rework, exact merge-gate refresh, rollback, external recovery honesty, and runtime fallback. |
| `python3 skills/agent-os/scripts/test_agent_os_routing.py` | 0 | verified | 18/18 routing and security tests PASS: finite unique fallback, unknown failure fail-closed, one writer, read-only Reviewer, and no credential persistence. |
| `python3 -m py_compile skills/agent-os/scripts/agent_os.py skills/agent-os/scripts/test_agent_os_v04.py skills/agent-os/scripts/test_agent_os_v03.py` | 0 | verified | CLI and focused tests compile. |
| `git diff --check` | 0 | verified | No whitespace errors. |
| system Skill path + `agent-os --help` | 0 | verified | `~/.codex/skills/agent-os` resolves to this Git checkout; SKILL metadata and CLI both report v0.4. The prior v0.3 directory is preserved under `~/.codex/skills-backup/`. |
| disposable `CODEX_HOME` + `./scripts/install.sh --migrate-existing` + repeat install | 0 | verified | Both legacy copied Skills were backed up, replaced with repository links, wrappers executed v0.4, and a second install was idempotent. |

## Criterion evidence

### AC-1 — Proportional governance

- `L0` reaches delivery acceptance without mandatory Learning or Maturity Report.
- `L1` rejects an empty Outcome Contract.
- `L1` with a `production` risk factor is rejected and must be reclassified as `L2`.
- `L2` cannot become READY without an independent, hashed, package-digest-bound PASS Challenge and cannot be accepted without Learning and five-question maturity.
- All paths reuse the existing single-writer, allowlist, exact-commit, Verifier, Codex Review, and Agent Shift Merge Gate.

### AC-2 — Outcome loop

- A new `L1` merge returns `OUTCOME_PENDING`.
- Hashed observations produce `OUTCOME_INCONCLUSIVE`, then `OUTCOME_CONFIRMED`; a separate Run produces `OUTCOME_REFUTED`.
- The Outcome Receipt binds the frozen contract and merge commit, stays in ignored Run evidence, and does not add a metadata commit above the merge. Exact-head rollback still passes.

### AC-3 — Governance economics

- Merge writes `run-economics.json`; `economics` recomputes it.
- Artifact includes wall-clock phases, verification duration, event/review/rework/failure/model/fallback counts, outcome state, and explicit measurement limits.
- Input and output tokens are `null` with source `unavailable-from-runtime`; no cost is estimated.

### AC-4 — Safe evolution

- Disposable v0.2 and v0.3 projects upgrade to schema 4 with an SQLite backup and pass integrity checks.
- Repeated upgrade is idempotent and makes no second backup.
- An active writer lock makes upgrade fail before backup or mutation.
- Existing exact-head rollback and finite process-local routing tests remain green.

### AC-5 — Usable release

- Skill, policy assets, references, example project rules, metadata, SVG badge, CLI help, and README describe v0.4.
- Search found no embedded real credential; only policy language and deliberate test sentinels exist.
- Legacy v0.3 mentions are limited to compatibility and migration statements.

## Measurement limits

- Disposable integration tests prove deterministic workflow behavior, not real product gain.
- Wall-clock economics includes human wait and is not labor accounting.
- Public GitHub rendering and file GET checks are required after merge and push; they cannot be claimed by this pre-publication evidence.
