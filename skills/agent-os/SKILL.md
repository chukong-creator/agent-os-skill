---
name: agent-os
description: Operate Agent OS v0.5 when delivery needs cross-Agent handoff, isolation, recovery, independent acceptance, or external-release evidence. Keep local reversible work on the normal single-Agent loop.
---

# Agent OS

Agent OS is the governance and evidence layer above Agent Shift. Agent Shift
owns Git baselines, branches, worktrees, and merge mechanics. Agent OS owns
work contracts, risk, permissions, Runs, evidence, review, Outcome, recovery,
and governance economics.

## Route before loading detail

- Use direct single-Agent execution for local, reversible work that one Agent
  can implement and verify in the current task.
- Use Agent OS when handoff, isolation, recovery across sessions, independent
  acceptance, or an authorized external release has concrete value.
- Keep one Builder and Codex acceptance by default. Add a Reviewer or model
  fallback only for a named independent benefit.
- Read only the reference required by the current stage:
  - risk and level selection:
    [proportional-governance.md](references/proportional-governance.md)
  - states, evidence, roles, and recovery:
    [protocol.md](references/protocol.md)
  - L1/L2 post-merge validation and cost:
    [outcomes-and-economics.md](references/outcomes-and-economics.md)
  - strategic or high-impact judgment:
    [director-principles.md](references/director-principles.md)
  - L2 maturity:
    [maturity-contract.md](references/maturity-contract.md)
  - explicit CC Switch routing:
    [model-routing.md](references/model-routing.md)
  - context and instruction maintenance:
    [context-engineering.md](references/context-engineering.md)

## Preserve the non-derivable invariants

These are hard boundaries, not style suggestions:

- one write-capable Agent per isolated worktree
- Work Package allowlist plus protected governance paths
- no credential, release, push, destructive Git, or irreversible action without
  explicit authority
- Evidence, Review, and Merge Gate bound to the same exact commit
- non-repository deliveries checked in the final form the user receives
- Reviewer never repairs or accepts its own implementation
- Codex owns scope, architecture, governance, and acceptance
- rollback stays narrow, explicit, and honest about external effects

Let the Builder use judgment inside those boundaries and match the surrounding
code's naming, comments, tests, and idiom.

## Establish project truth

Read the nearest `AGENTS.md`, root `CLAUDE.md`,
`.agent-shift/project.json`, and `.agent-os/project.json`. Then run:

```bash
agent-shift doctor <project-root>
agent-os doctor <project-root>
```

Treat Work Package JSON as goal and permission truth, Agent Shift as handoff
truth, Git as file-state truth, Evidence plus Review as delivery truth, and the
Outcome Receipt as gain truth. Root `CLAUDE.md` is the durable Claude entry;
`.claude/` files are runtime adapters.

Initialize or explicitly upgrade with `agent-os init --help` or
`agent-os upgrade --help`. Upgrade refuses active writer locks, backs up SQLite,
validates integrity, and never runs implicitly.

## Run the bounded delivery loop

Use the command interface as the canonical procedure; inspect `--help` instead
of copying stale examples:

```text
package-create -> [director-challenge for L2] -> package-ready
run-start -> claude-start -> verify -> verifier
review -> rework-start or merge -> outcome-check for L1/L2
```

Choose the lightest honest level:

- `L0`: local, reversible governed work with no risk factors or external effect.
- `L1`: normal measurable delivery or reversible authorized release; requires an
  Outcome Contract.
- `L2`: production, privacy, credentials, migration, deletion, payment,
  irreversible, or materially consequential work; adds independent Challenge,
  learning, and five-question maturity.

Classify delivery as `repo`, `artifact`, `installable`, or `live`. For the last
three, bind each claim to a check against the final artifact or endpoint.
Rebuild, repackaging, signing, upload, or artifact hash changes invalidate prior
delivery evidence.

Claude owns implementation and ordinary rework in its assigned worktree.
`CHANGES_REQUESTED` returns that same worktree to Claude. Mechanical verification
checks structure, hashes, and the exact commit; it is not product acceptance.

## Keep routing finite

Routing is opt-in through an explicit profile or routing config. It reads CC
Switch metadata and injects provider settings only into the Claude child
process; it never changes the global provider or stores credentials.

Only explicit provider or quota terminal failures advance through a finite,
unique fallback chain. Permission waits keep the same writer. Unknown failures,
manual stops, suspected stalls, repeated profiles, and exhausted chains never
start a second writer or loop indefinitely.

## Recover without inventing success

- `recover` is read-only diagnosis.
- `runtime-recover` resumes the same failed Run, lock, branch, worktree, and
  partial edits after an explicit reason.
- `rollback` only reverts the latest recorded no-ff merge when protected-branch,
  commit, and Evidence gates match.
- External effects remain `CODE_REVERTED_EXTERNAL_PENDING` until separately
  verified.

Record command output, exit status, duration, SHA-256, diff, paths, commit, and
timestamp. Classify claims as `verified`, `reviewed`, `observed`, or `assumed`;
never promote assumptions. One Run may propose a learning rule but may not edit
Policy or this Skill automatically.

## Right-size context

Run the read-only audit after changing `AGENTS.md`, `CLAUDE.md`, or a Skill:

```bash
agent-os context-doctor <project-root> --include-global \
  --skill /Users/fanchao/.codex/skills/agent-os/SKILL.md --strict
```

Keep non-derivable boundaries and project gotchas always loaded. Move procedures,
examples, rubrics, and domain guidance behind references or Skills. A broken
reference fails; duplication and budget excess warn, and fail under `--strict`.

## Resources

- `scripts/agent_os.py`: deterministic control plane and context audit
- `references/`: detailed policy loaded by task stage
- `assets/`: machine-readable governance defaults
