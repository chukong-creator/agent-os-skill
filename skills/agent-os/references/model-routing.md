# CC Switch-backed model routing

## Ownership

CC Switch is the user-owned source for Claude provider endpoints and credentials. Agent OS owns role selection and finite recovery per Run. Never automate GUI clicks, mutate the CC Switch database, or change its globally current provider to route an Agent OS task.

The user-level routing file is `~/.config/agent-os/model-routing.json`. It contains provider names or ids, models, effort levels, and fallback chains, but never credentials.

## Example role chains

| Mode | Primary | Fallback | Permission |
|---|---|---|---|
| Builder | GLM-5.2 | Kimi K2.7 Code | scoped write and safe Git |
| Reviewer | K3 High | GLM-5.2 High | read-only |
| Deep review | K3 Max | none by default | read-only |

This table documents one validated deployment, not a product default. Use provider names and model identifiers that exist in your own CC Switch configuration; the repository example file uses generic placeholders.

Codex remains responsible for package scope, review interpretation, rework orders, and final acceptance. The supervisor may change HOW by selecting the next already-authorized profile; it may not change WHAT the Work Package requires.

## Isolation

1. Open `~/.cc-switch/cc-switch.db` in read-only mode.
2. Resolve the exact Claude provider configured by the selected profile.
3. Keep only allowlisted Claude provider environment keys.
4. Remove inherited provider/model variables from the child environment.
5. Inject endpoint, credential, and model into that child process only.
6. Pass model and effort explicitly to Claude Code.
7. Record only profile, provider id/name, endpoint host, model, effort, and the label `cc-switch-memory`.

An API key or auth token must never appear in the routing file, command line, temporary file, dry-run output, Work Package, event log, Evidence, or failure report.

## Finite recovery

The detached Run supervisor observes the exact Claude background session it launched.

- `done`: close the supervisor successfully.
- `stopped`: respect the stop and do not restart.
- `failed` with an explicit quota, rate-limit, insufficient-balance, provider-authentication, overload, HTTP 5xx, or provider-gateway error: start the next profile once.
- `failed` because the worktree is missing, permissions are invalid, or routing configuration is broken: do not burn another provider's quota.
- an unknown failure: stop as `RUNTIME_FAILED`; never guess that changing models will fix it.
- no remaining profile: record a runtime failure and transition the Run to `RUNTIME_FAILED`.

Fallback chains must contain unique profiles. A routing cycle records every attempted profile before launch and refuses to exceed the chain length, so a bad configuration cannot create an infinite provider loop. Startup status checks fail closed, and a per-worktree launch mutex makes the status-check plus launch operation single-writer. Once a role cycle exists, only its Supervisor may advance to the exact `next_profile` recorded in `FALLBACK_STARTING`; an external `claude-start --profile fallback` cannot bypass discovery latency.

Never run two write-capable Claude sessions concurrently in one worktree. The launch mutex is keyed by the canonical worktree path, so different Runs cannot race into the same worktree. A Builder with no observed job update for five minutes is marked `SUSPECTED_STALL`; a Reviewer uses fifteen minutes. This is an observability alert, not permission to start a second writer. Automatic fallback begins only after a terminal, explicitly classified provider/quota failure.

## Commands

```bash
agent-os provider-list
agent-os route-resolve
agent-os route-resolve --profile fallback
agent-os route-resolve --profile reviewer

# Stage selects builder or reviewer automatically.
agent-os claude-start <project-root> --run <run-id>

# Codex may explicitly start at a later authorized profile.
agent-os claude-start <project-root> --run <run-id> --profile fallback

# Resolve the launch without sending an API request.
agent-os claude-start <project-root> --run <run-id> --dry-run
```

Set `AGENT_OS_ROUTING_CONFIG` or pass `--routing-config` to use a different non-secret routing file. Use `--profile inherit` only when deliberate compatibility with the current global Claude settings is required.
