# CC Switch-backed model routing

## Ownership

CC Switch is the user-owned source for Claude provider endpoints and credentials. Agent OS owns role selection and finite recovery per Run. Never automate GUI clicks, mutate the CC Switch database, or change its globally current provider to route an Agent OS task.

The user-level routing file is `~/.config/agent-os/model-routing.json`. It contains provider names or ids, models, effort levels, and fallback chains, but never credentials.

Routing is opt-in. The presence of this file alone never authorizes provider selection or quota consumption. A Builder inherits the normal Claude environment unless Codex passes `--profile` or `--routing-config`. Every `agent-os claude-start` launch is supervised; explicit routing additionally enables finite provider fallback.

The Claude Code shell is transport, not model identity. A Run may use Anthropic, GLM, DeepSeek, Kimi, or another configured Anthropic-compatible provider. Provider and model selection may change HOW the Builder executes, but never the Work Package, allowed paths, writer lock, evidence requirements, verification, or Codex acceptance.

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

The detached Run supervisor observes the exact Claude background session it launched. Do not replace `agent-os claude-start` with a raw `claude -p` or `claude --background` call for governed work: raw text-mode silence is not a trustworthy activity signal and bypasses Run-level diagnosis.

- `working`, `busy`, `queued`, `pending`, `blocked`, or an input-waiting state: keep waiting; these are non-terminal states. Claude reports ordinary permission prompts as `blocked`, so the Supervisor records Run-local `WAITING_FOR_PERMISSION`, preserves the same writer, surfaces `waitingFor`, suppresses stall fallback, and resumes supervision only after the prompt clears.
- `done`: close the supervisor successfully.
- `stopped`: respect the stop and do not restart.
- `failed` with an explicit quota, rate-limit, insufficient-balance, provider-authentication, overload, HTTP 5xx, or provider-gateway error: start the next profile once.
- `failed` because the worktree is missing, permissions are invalid, or routing configuration is broken: do not burn another provider's quota.
- an unknown failure: stop as `RUNTIME_FAILED`; never guess that changing models will fix it.
- no remaining profile: record a runtime failure and transition the Run to `RUNTIME_FAILED`.

After the cause is understood, Codex may run `agent-os runtime-recover <project-root> --run <run-id> --reason "..."`. Recovery reuses the same Run and worktree, restores the single-writer lock, and starts a fresh finite routing cycle. It does not duplicate the Work Package or erase failure evidence.

Fallback chains must contain unique profiles. A routing cycle records every attempted profile before launch and refuses to exceed the chain length, so a bad configuration cannot create an infinite provider loop. Startup status checks fail closed, and a per-worktree launch mutex makes the status-check plus launch operation single-writer. Once a role cycle exists, only its Supervisor may advance to the exact `next_profile` recorded in `FALLBACK_STARTING`; an external `claude-start --profile fallback` cannot bypass discovery latency.

Never run two write-capable Claude sessions concurrently in one worktree. The launch mutex is keyed by the canonical worktree path, so different Runs cannot race into the same worktree.

Supervision has two inactivity thresholds:

- Builder: `SUSPECTED_STALL` after five minutes without a job update and `UNRESPONSIVE` after fifteen minutes by default.
- Reviewer: `SUSPECTED_STALL` after fifteen minutes and `UNRESPONSIVE` after thirty minutes by default.
- A new job update clears either alert and records `routing_activity_resumed`.
- Permission waits do not become stalls.

`UNRESPONSIVE` means the session is still present but no longer provides evidence of progress. It requires diagnosis or an explicit stop before takeover; it never authorizes a second writer by itself. Automatic fallback begins only after a terminal, explicitly classified provider/quota or compatibility failure. The same Run, branch, worktree, and Work Package continue under the next authorized profile.

`agent-os claude-status` keeps runtime health separate from implementation evidence. A responsive session with no branch commit or worktree change is `ACTIVE_NO_IMPLEMENTATION_EVIDENCE`: Claude is observably active, but the Supervisor does not claim to know whether it is reasoning, planning, or preparing a tool call. Git changes or commits move the classification to `ACTIVE_IMPLEMENTING`. A missing session with retained Git changes becomes `ORPHANED_PARTIAL_WORK`. Only a terminal failed session or a Supervisor-recorded terminal provider category becomes `PROVIDER_FAILED`.

The status response also reports the observed active-session count for the whole worktree. `single_writer_preserved` is derived from that count rather than assumed. A quiet process, CPU usage, network connection, or absence of a diff is never sufficient by itself to classify a provider failure.

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

# Separate provider health from implementation progress.
agent-os claude-status <project-root> --run <run-id>
```

Set `AGENT_OS_ROUTING_CONFIG` or pass `--routing-config` to use a different non-secret routing file. Use `--profile inherit` only when deliberate compatibility with the current global Claude settings is required.
