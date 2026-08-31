# Agent OS v0.6 context engineering

This policy applies Anthropic's July 2026 context-engineering guidance without
turning “write less” into an unsafe universal rule.

## The sorting test

Evaluate each persistent instruction with two questions:

1. Can a capable Agent derive the right behavior from the repository, tool
   interface, current task, or surrounding examples?
2. If it guesses wrong, will a deterministic check, visible failure, or required
   review catch the error?

When both answers are yes, the instruction is usually scaffolding: test removing
it or replace it with a pointer to the source of truth. When either answer is no,
the instruction is load-bearing: keep it short and explicit.

## Keep always loaded

- permission, confidentiality, credential, and irreversible-action boundaries
- decision rights and escalation points
- definitions of done that have no mechanical oracle
- project-specific gotchas that are surprising and fail silently
- the routing rule that tells the Agent where deeper context lives

## Defer until relevant

- long command examples already expressed by `--help`
- review, release, design, migration, and verification procedures
- rubrics and domain references used by only a subset of tasks
- historical decisions and learnings already available through memory or Git
- explanations that restate a deterministic hook or state-machine constraint

## One owner per instruction

Put each rule at the narrowest authoritative layer:

- tool behavior and parameters: tool schema or `--help`
- mechanical safety and state transitions: control-plane code plus tests
- cross-project Codex boundaries: global `AGENTS.md`
- repository purpose and gotchas: project `AGENTS.md` or `CLAUDE.md`
- task-specific procedure: Skill
- durable observation: memory, not a manually growing instruction file

Higher layers should point to lower layers instead of repeating them. Conflicting
instructions across system, global, project, Skill, and task context impose a
reasoning tax even when the model eventually chooses correctly.

## Prefer interfaces and rich references

Use typed arguments, enumerated states, structured JSON, executable tests,
working functions, HTML artifacts, mockups, and verifier rubrics when they
communicate more precisely than prose. Examples are useful only when the
interface cannot express the constraint; do not let examples narrow exploration
without intent.

## Audit loop

Run:

```bash
agent-os context-doctor <project-root> --include-global \
  --skill /path/to/relevant/SKILL.md --strict
```

The command is deliberately read-only. It inventories line, word, instruction,
and reference counts; detects exact normalized repeated instructions; applies
separate budgets to global, project, Claude, and Skill context; and fails on
broken local references. It does not pretend to settle semantic conflicts or
delete load-bearing context.

Re-run the sort after a major model release, a recurring failure pattern, or a
new deterministic verification capability. Remove a rule only when evidence
shows the surrounding system can now carry its load.
