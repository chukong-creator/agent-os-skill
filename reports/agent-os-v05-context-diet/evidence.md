# Agent OS v0.5 Context Diet — Evidence

Date: 2026-07-26

## Source confirmation

- X announcement resolved through X oEmbed to Thariq's July 24 post and its
  linked article.
- Anthropic's article was read at:
  `https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models`.
- Applied shifts: judgment inside hard boundaries, expressive interfaces,
  progressive disclosure, single-owner instructions, memory outside instruction
  files, and high-fidelity references.

## Context measurements

Before:

- global `AGENTS.md`: 29 lines
- workspace `AGENTS.md`: 150 lines
- Agent OS `SKILL.md`: 239 lines
- total: 418 lines

After:

- global `AGENTS.md`: 34 lines
- workspace `AGENTS.md`: 55 lines
- Agent OS `SKILL.md`: 145 lines
- total: 234 lines
- reduction: 184 lines, approximately 44%
- always-loaded global plus workspace reduction: 179 to 89 lines,
  approximately 50%

Strict audit of global, workspace, Agent OS Skill, Agent Shift Skill, and Claude
template: `PASS`, 0 failures, 0 warnings, 0 repeated normalized instructions,
and 0 broken references.

## Executable verification

- `test_agent_os_v05.py`: PASS, 4 scenarios
  - clean progressive disclosure
  - duplicate and budget warnings
  - broken and missing references fail closed
  - explicit v0.4 to v0.5 migration with SQLite backup
- `test_agent_os_v04.py`: PASS, 16 delivery and recovery scenarios
- `test_agent_os_v03.py`: PASS, 11 compatibility scenarios
- `test_agent_os_routing.py`: PASS, 23 routing, permission, fallback, and
  secret-boundary tests
- `test_agent_shift_views.py`: PASS, 3 view consistency tests
- Python compilation: PASS
- JSON validation for changed policy assets: PASS
- `git diff --check`: PASS
- installed `agent-os --help`: reports v0.5 and exposes `context-doctor`
- installed Skill symlinks resolve to this repository
- versioned project and global `AGENTS.md` templates preserve the lightweight
  configuration pattern for future installations

## Enrolled-project migration

The three canonical control roots discovered under `/Users/fanchao/Documents`
were explicitly upgraded with zero active writer locks. Each migration created
an SQLite backup and passed `agent-os doctor --strict` after its governance
commit:

- Understand Things: `9646486`; Understand Stories adapter: `b8004fa`
- World Now: `f1065d3`
- Vitality Demo / Longevity OS: `0e604d6`

Legacy generated `WORK_QUEUE.md` views in Understand Things and World Now were
regenerated from Agent Shift state before the final doctor pass. Unrelated
untracked product files were not staged or changed.

## Claim classification

- `verified`: CLI behavior, migration, tests, context budgets, duplicate
  detection, broken-reference detection, installed command, and symlinks.
- `reviewed`: instruction sorting and progressive-disclosure placement.
- `assumed`: token savings are directionally positive; exact inference-token
  savings are not exposed and were not estimated.
