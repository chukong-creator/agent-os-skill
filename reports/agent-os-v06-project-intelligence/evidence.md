# Agent OS v0.6 Project Intelligence Evidence

## Exact implementation

- Feature commit before final evidence: `f7c332200320a773b16220e3b3264109d1e9470f`.
- Control plane reports `agent_os_version=0.6` and SQLite schema revision 6.
- `SKILL.md` is exactly 160 lines; the strict context audit reports 924 words and eight routed references.

## Executable regressions

All commands below exited 0 on macOS from the isolated feature worktree:

- Python compilation for both control planes.
- Agent Shift view suite: 5 scenarios.
- Claude routing and supervision suite: 31 scenarios.
- Agent OS v0.6 project-intelligence suite: 3 scenarios.
- Agent OS v0.5 compatibility suite: 4 scenarios.
- Agent OS v0.4 compatibility suite: 18 scenarios.
- Agent OS v0.3 compatibility suite: 11 scenarios.
- Strict persistent-context audit and `git diff --check`.
- Isolated installer smoke test with a disposable `HOME`, including both command wrappers.

The v0.6 suite proves that an incomplete maintenance delta is rejected, a
bug-fix cannot be accepted without an exact-commit knowledge assessment, and
the knowledge doctor reports missing, stale, or malformed project intelligence
without converting it into a semantic claim.

## Enrolled-project migration

| Project | Governance commit | Knowledge doctor | Agent OS doctor | Preserved state |
|---|---|---|---|---|
| Longevity OS / Vitality Demo | `67787b763c857e1ffced118ea94fadcf24a5ddde` | PASS, 4 sources | PASS | clean tracked tree |
| Understand Things | `a0fe489b55f38e4a8a03214f848e3317843988b0` | PASS, 4 sources | PASS | untracked `Understand Stories/` preserved |
| Understand Stories adapter | `7ab7ada350b3368260519a4e1cf3810ec4a71996` | n/a | covered by parent doctor | clean tracked tree |
| World Now | `9c74f3c5c9f5c1145e5a1b10124dc7831807bcd2` | PASS, 5 sources | expected FAIL | pre-existing tracked `README.md` drift and all untracked site/evidence files preserved |

Each migration created a timestamped v0.5 SQLite backup under the project's
local `.agent-os/runtime/migrations/` directory. No product source, release,
credential, or external service was changed.

## Claim boundaries

- Knowledge doctor validates declared routes, freshness metadata, executable
  verification entrypoints, and corpus shape. It does not decide whether an
  architecture document is semantically correct.
- Empty failure corpora are an honest starting point; future bug-fix acceptance
  materializes reviewed records rather than retroactively inventing history.
- World Now is intentionally not reported as clean. Its known `README.md` drift
  predates this upgrade and remains blocked by the post-acceptance drift gate.

