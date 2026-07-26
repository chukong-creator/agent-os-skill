# Agent OS v0.5 Context Diet — Outcome Contract

## Objective

Apply Anthropic's July 2026 context-engineering lessons to Agent OS and the
user's Codex configuration without weakening deterministic governance.

## Boundaries

- Preserve permission, secret, authority, exact-commit, evidence, review,
  rollback, and recovery constraints because they are not safely derivable.
- Do not delete project-specific gotchas that would fail silently.
- Do not move deterministic control-plane behavior into prose.
- Do not modify product repositories enrolled in Agent OS.

## Acceptance criteria

1. Agent OS provides a read-only context audit that inventories always-loaded
   files, detects repeated instructions, enforces configurable size budgets,
   and produces machine-readable output.
2. Agent OS guidance uses progressive disclosure: the main Skill is a compact
   router and detailed procedures live in referenced files.
3. Global and workspace `AGENTS.md` files contain no duplicated global policy;
   the workspace file is limited to workspace-specific gotchas and routing.
4. Existing Agent OS v0.4 delivery, recovery, routing, and security behavior
   remains covered by passing regression tests.
5. Installation paths still resolve and the context audit passes in strict mode
   for the user's actual Codex configuration.

## Verification

- Run the new v0.5 context audit test.
- Run all existing Agent OS and Agent Shift test suites.
- Run Python syntax checks and JSON validation.
- Run `agent-os context-doctor` against this workspace with global context and
  the installed Agent OS Skill included.
- Inspect line/word/byte counts before and after.

## Non-goals

- Replacing Codex or Claude Code built-in system prompts.
- Automatically deleting context.
- Treating every semantic similarity as a contradiction.
- Weakening L0/L1/L2 governance or changing the database schema.

## Implementation checklist

- [x] Add context inventory and audit command.
- [x] Add regression tests.
- [x] Compress the Agent OS Skill.
- [x] Add context-engineering reference.
- [x] Update README and release metadata.
- [x] Compress global and workspace instructions.
- [x] Run full verification and record evidence.
