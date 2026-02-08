# Technology Stack: OpenCode Multi-Agent Spawning

**Project:** OpenCode Teams MCP (replacing Claude Code spawning)
**Researched:** 2026-02-07
**Overall Confidence:** MEDIUM -- OpenCode CLI docs and Python SDK are well-documented, but the exact spawning approach for multi-agent teams requires combining patterns that no single project demonstrates end-to-end.

## Recommended Stack

### Spawning Approach: `opencode run` via tmux (Not SDK, Not `serve`)

There are three viable approaches to programmatically drive OpenCode instances. After researching all three, **`opencode run` in tmux panes** is the right choice for this project.

| Approach | Verdict | Why |
|----------|---------|-----|
| `opencode run` in tmux | **USE THIS** | Closest to existing spawner, non-interactive, auto-approves permissions, exits cleanly |
| `opencode serve` + Python SDK | Do not use | Subagent Task tool hangs via REST API (issue #6573, fixed but fragile); server is 1-to-1 per project; adds HTTP layer complexity |
| `opencode serve` + JS/TS SDK | Do not use | Wrong language (project is Python); same REST API concerns |

**Rationale:** The existing `spawner.py` uses `tmux split-window` to launch `claude` CLI processes. OpenCode's `opencode run` command is the direct replacement -- it runs non-interactive, auto-approves all permissions, outputs to stdout, and exits when done. This preserves the architecture while swapping the binary.

**Confidence:** MEDIUM -- `opencode run` behavior verified via official CLI docs. The auto-approve-in-non-interactive behavior is documented. However, long-running agent sessions via `opencode run` (vs quick one-shots) need validation.

### Core Binary

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| OpenCode CLI | v1.1.49+ | AI coding agent runtime | Replaces `claude` binary; supports `run` subcommand for non-interactive mode, `--agent` for agent selection, `--model` for model pinning, `--format json` for structured output |

### Model Provider

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Kimi K2.5 | Latest | LLM for agent reasoning | Project requirement; supported in OpenCode v1.1.x via `moonshot-ai` or `moonshot-ai-china` providers; full tool-call support |
| OpenRouter (fallback) | N/A | Alternative provider | Access Kimi K2.5 via `moonshotai/kimi-k2.5` model ID if direct Moonshot API is unavailable |

**Confidence:** HIGH -- Kimi K2.5 support confirmed via merged PR #10835 in OpenCode. Registered with providers `moonshot-ai` (international) and `moonshot-ai-china`. Model ID: `kimi-k2.5`.

### Existing Stack (Preserved)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.12+ | Server runtime | Existing; no reason to change |
| FastMCP | 3.0.0b1 | MCP server framework | Existing; teammates connect to this for team coordination |
| tmux | System | Process isolation | Existing; each agent runs in its own tmux pane |
| Pydantic | v2 (via FastMCP) | Data models | Existing; used for TeamConfig, messages, etc. |

---

## OpenCode CLI Command Reference

### Spawning a Teammate (replaces `build_spawn_command`)

```bash
opencode run \
  --model "moonshot-ai/kimi-k2.5" \
  --agent "teammate-name" \
  --format json \
  "Your initial prompt here with team context"
```

**Key flags for spawning:**

| Flag | Value | Purpose |
|------|-------|---------|
| `run` | (subcommand) | Non-interactive mode; auto-approves all permissions; prints result to stdout and exits |
| `--model` / `-m` | `moonshot-ai/kimi-k2.5` | Pin to Kimi K2.5 via Moonshot provider |
| `--agent` | `<agent-name>` | Use a specific agent config (loads from `.opencode/agents/<name>.md`) |
| `--format` / `-f` | `json` | Structured JSON output for programmatic parsing |
| `--file` / `-f` | `<path>` | Attach files to the prompt context |
| `--title` | `<name>` | Name the session for later identification |

**Confidence:** HIGH -- flags verified from official CLI docs at opencode.ai/docs/cli/.

### What the spawn command looks like in tmux

```python
# New build_spawn_command (replaces Claude Code version)
cmd = (
    f"cd {shlex.quote(member.cwd)} && "
    f"opencode run "
    f"--model {shlex.quote(member.model)} "
    f"--agent {shlex.quote(member.name)} "
    f"--format json "
    f"{shlex.quote(member.prompt)}"
)

result = subprocess.run(
    ["tmux", "split-window", "-dP", "-F", "#{pane_id}", cmd],
    capture_output=True, text=True, check=True,
)
```

### Important Behavioral Differences from Claude Code

| Behavior | Claude Code | OpenCode |
|----------|-------------|----------|
| Team awareness | Native `--team-name`, `--agent-id`, `--parent-session-id` flags | None -- must inject via agent config + system prompt |
| Permission handling | Interactive prompts | `run` mode auto-approves all; config-level `permission: "allow"` for TUI mode |
| Agent identity | CLI flags set identity | Agent markdown file defines identity |
| Model selection | `--model sonnet/opus/haiku` | `--model provider/model-id` (e.g., `moonshot-ai/kimi-k2.5`) |
| Session persistence | Session file in `~/.claude/` | SQLite database managed by OpenCode |
| Exit behavior | Stays running in TUI | `run` mode exits after completion |

---

## Agent Configuration

### Dynamic Agent Config Files

Each teammate needs a markdown agent config file generated at spawn time. This replaces Claude Code's `--agent-id`/`--team-name` flags.

**Location:** `.opencode/agents/<teammate-name>.md` (project-level)

**Format:**

```markdown
---
description: "Team member: <name> on team <team-name>"
mode: primary
model: moonshot-ai/kimi-k2.5
temperature: 0.3
tools:
  write: true
  edit: true
  bash: true
  read: true
  grep: true
  glob: true
  list: true
  webfetch: false
  websearch: false
  todowrite: false
  todoread: false
permission:
  edit: allow
  bash: allow
---
You are <name>, a teammate on team "<team-name>".

## Your Identity
- Agent ID: <agent-id>
- Team: <team-name>
- Role: <agent-type>

## Team Coordination
You have access to the claude-teams MCP server which provides:
- `read_inbox` -- Check for messages from team lead and teammates
- `send_message` -- Send messages to team lead or teammates
- `task_list` -- View team tasks
- `task_update` -- Update task status
- `poll_inbox` -- Long-poll for new messages

## Working Protocol
1. Check your inbox first using `read_inbox`
2. Read any task assignments
3. Work on assigned tasks
4. Update task status as you progress
5. Send messages to team-lead when you need guidance or are done
6. Check inbox periodically for new instructions

## Important
- Your team lead is "team-lead"
- Always update task status when starting (`in_progress`) and finishing (`completed`)
- Send a message to team-lead when you complete your work
```

**Confidence:** HIGH -- Agent markdown format verified from official docs at opencode.ai/docs/agents/. Fields `mode`, `model`, `temperature`, `tools`, `permission` all confirmed.

### Project-Level OpenCode Config

Each teammate's working directory needs an `opencode.json` with MCP server configuration so the agent can communicate with the team.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "moonshot-ai/kimi-k2.5",
  "permission": "allow",
  "mcp": {
    "claude-teams": {
      "type": "local",
      "command": ["claude-teams"],
      "enabled": true
    }
  },
  "compaction": {
    "auto": true,
    "prune": true
  },
  "watcher": {
    "ignore": ["node_modules/**", "dist/**", ".opencode/**"]
  }
}
```

**Alternative -- remote MCP (if server is already running):**

```json
{
  "mcp": {
    "claude-teams": {
      "type": "remote",
      "url": "http://localhost:<port>",
      "enabled": true
    }
  }
}
```

**Confidence:** HIGH -- MCP server config format verified from official docs at opencode.ai/docs/mcp-servers/.

### Rules File (AGENTS.md)

OpenCode loads `AGENTS.md` from the project root as part of its system prompt context. This is where project-level team instructions go.

```markdown
# Team Coordination Rules

This project uses the claude-teams MCP server for multi-agent coordination.

## MCP Tools Available
- read_inbox, send_message, poll_inbox -- messaging
- task_list, task_get, task_create, task_update -- task management
- read_config -- team configuration

## Protocol
- Check inbox before starting work
- Update task status as you progress
- Report completion to team-lead
```

**Confidence:** HIGH -- AGENTS.md behavior verified from official rules docs at opencode.ai/docs/rules/.

---

## Provider Configuration

### Kimi K2.5 via Moonshot AI (Direct)

```json
{
  "provider": {
    "moonshot-ai": {
      "options": {
        "apiKey": "{env:MOONSHOT_API_KEY}"
      }
    }
  },
  "model": "moonshot-ai/kimi-k2.5"
}
```

API key obtained from platform.moonshot.ai.

### Kimi K2.5 via OpenRouter (Alternative)

```json
{
  "provider": {
    "openrouter": {
      "options": {
        "apiKey": "{env:OPENROUTER_API_KEY}"
      },
      "models": {
        "moonshotai/kimi-k2.5": {}
      }
    }
  },
  "model": "openrouter/moonshotai/kimi-k2.5"
}
```

**Confidence:** MEDIUM -- Moonshot provider confirmed in OpenCode. Exact `{env:}` syntax for API keys confirmed in config docs. OpenRouter model ID from openrouter.ai listing.

---

## What NOT to Use

### Do Not Use: `opencode serve` + Python SDK for spawning

The Python SDK (`pip install --pre opencode-ai`) exists and provides `Opencode()` / `AsyncOpencode()` clients with `session.create()`, `session.chat()`, etc. However:

1. **Subagent hang bug** -- Issue #6573 documented sessions hanging when Task tool spawns subagents via REST API. Marked fixed but architecturally fragile.
2. **One server per project** -- `opencode serve` binds to a single project directory. You would need N servers for N teammates, adding port management complexity.
3. **Unnecessary abstraction** -- The existing spawner uses subprocess + tmux. `opencode run` maps directly to this pattern. Adding an HTTP client layer provides no benefit and introduces failure modes (server crashes, port conflicts, timeout handling).
4. **SDK is pre-release** -- `pip install --pre opencode-ai` is still in beta. Production stability unclear.

**Confidence:** HIGH -- SDK surface verified via deepwiki.com/sst/opencode-sdk-python; hang bug verified via GitHub issue #6573.

### Do Not Use: OpenCode's Built-in Task Tool for Team Coordination

OpenCode has a built-in `task` tool that spawns subagents (agents with `mode: subagent`). This creates child sessions within the same OpenCode process. However:

1. **Single-process model** -- All subagents run within one OpenCode instance. Our architecture needs independent processes in separate tmux panes.
2. **No cross-instance communication** -- The Task tool returns results to the parent agent. It does not support the inbox/messaging protocol we use.
3. **Different model** -- We want N independent agents coordinated via MCP, not a parent-child hierarchy.

**Confidence:** HIGH -- Task tool behavior verified from official agent docs and DeepWiki analysis.

### Do Not Use: `dmux` or `opencode-worktree` Plugins

These tools (dmux, opencode-worktree, workmux) manage git worktrees + tmux for parallel agents. They solve a different problem:

1. **Git worktree isolation** -- They create separate worktrees per agent. We may want agents sharing a working directory (team coordination on same codebase).
2. **No team protocol** -- They spawn independent agents with no messaging/task infrastructure.
3. **External dependencies** -- Adding another orchestration layer when we already have one (this MCP server) creates confusion about which system is in charge.

Use git worktrees as a strategy within the spawner if needed, but don't delegate orchestration to these tools.

**Confidence:** MEDIUM -- Tools reviewed via GitHub repos; architectural mismatch assessment based on our requirements.

### Do Not Use: `oh-my-opencode` Multi-Agent Plugin

This plugin provides multi-agent orchestration within OpenCode. But:

1. **It IS OpenCode** -- It runs inside OpenCode, not as an external orchestrator. We are the external orchestrator.
2. **Overlapping responsibility** -- It would compete with our MCP server for coordination.

**Confidence:** MEDIUM -- Based on GitHub repo review and DeepWiki analysis.

---

## Key Architecture Decisions

### Decision 1: Generate agent configs at spawn time, clean up at shutdown

The spawner must:
1. Create `.opencode/agents/<name>.md` with team context before running `opencode run`
2. Ensure `opencode.json` has MCP server config in the agent's working directory
3. Clean up agent config files when teammate is killed or shuts down

This is the fundamental difference from Claude Code: context injection happens via files, not CLI flags.

### Decision 2: Use `opencode run` (not TUI mode) for teammates

- `opencode run` is non-interactive, auto-approves permissions, and exits when done
- The TUI mode (`opencode` without subcommand) requires interactive input
- The `--prompt` flag on TUI mode still launches the interactive interface

**Critical concern:** `opencode run` exits after completing the prompt. For long-running teammates that need to stay alive and check their inbox periodically, this may be a problem. Options:

1. **Wrapper script** -- Loop that runs `opencode run`, checks inbox, runs again
2. **TUI with `--prompt`** -- Launches interactive mode with initial prompt (but loses auto-approve)
3. **`opencode serve` per agent** -- Each agent gets its own server (complex but persistent)

This needs prototyping. The wrapper script approach is simplest and most aligned with the existing architecture.

**Confidence:** LOW for long-running behavior -- This is the biggest unknown. `opencode run` may not support the "stay alive and poll inbox" pattern that Claude Code agents use.

### Decision 3: Model string format is `provider/model-id`

Claude Code uses short names (`sonnet`, `opus`, `haiku`). OpenCode uses `provider/model-id` format:

| Old (Claude Code) | New (OpenCode) |
|-------------------|----------------|
| `sonnet` | `moonshot-ai/kimi-k2.5` |
| `opus` | `moonshot-ai/kimi-k2.5` |
| `haiku` | `moonshot-ai/kimi-k2.5` (or a cheaper model) |

The `spawn_teammate_tool` Literal type constraint `Literal["sonnet", "opus", "haiku"]` must be replaced.

---

## Installation & Setup

### Prerequisites

```bash
# Install OpenCode CLI
curl -fsSL https://opencode.ai/install | bash
# OR
brew install opencode

# Verify
opencode --version  # Should be v1.1.49+

# Configure Kimi K2.5 provider (interactive)
opencode
# Then: /connect -> search "Moonshot AI" -> enter API key
# Then: /models -> select kimi-k2.5
```

### Python Project Dependencies (unchanged)

```bash
# Existing - no new Python dependencies needed
pip install fastmcp==3.0.0b1
```

### Environment Variables

```bash
# Required for Kimi K2.5
export MOONSHOT_API_KEY="your-key-here"

# Alternative: OpenRouter
export OPENROUTER_API_KEY="your-key-here"
```

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Spawning method | `opencode run` in tmux | `opencode serve` + SDK | SDK is pre-release; REST API has subagent hang bugs; unnecessary complexity |
| Agent context | `.opencode/agents/*.md` files | CLI flags | OpenCode has no `--agent-id`/`--team-name` flags; markdown agents are the native approach |
| MCP transport | `local` (subprocess) | `remote` (HTTP) | Local is simpler; no port management; single process lifecycle |
| Model provider | Moonshot AI (direct) | OpenRouter | Direct provider has lower latency and cost; OpenRouter adds a middleman |
| Long-running agents | Wrapper script loop | `opencode serve` per agent | Wrapper is simpler; `serve` requires port management for N agents |
| Process isolation | tmux panes | Docker containers | tmux is existing pattern; Docker adds container management overhead |
| Coordination | Existing MCP inbox/tasks | OpenCode Task tool | Task tool is intra-process; we need inter-process coordination |

---

## Version Compatibility Matrix

| Component | Minimum Version | Tested With | Notes |
|-----------|----------------|-------------|-------|
| OpenCode CLI | v1.1.49 | v1.1.49 | Kimi K2.5 support requires recent version |
| Python | 3.12 | 3.12 | Existing requirement |
| FastMCP | 3.0.0b1 | 3.0.0b1 | Existing requirement |
| tmux | 3.0+ | System | Existing requirement |
| Kimi K2.5 | N/A (API) | Latest | Via Moonshot AI or OpenRouter |

---

## Sources

### Official Documentation (HIGH confidence)
- [OpenCode CLI Reference](https://opencode.ai/docs/cli/) -- Commands, flags, non-interactive mode
- [OpenCode Agent Configuration](https://opencode.ai/docs/agents/) -- Agent markdown format, fields, modes
- [OpenCode Configuration](https://opencode.ai/docs/config/) -- opencode.json format, provider config
- [OpenCode MCP Servers](https://opencode.ai/docs/mcp-servers/) -- MCP server integration format
- [OpenCode Rules](https://opencode.ai/docs/rules/) -- AGENTS.md behavior
- [OpenCode Permissions](https://opencode.ai/docs/permissions/) -- Permission model, auto-approve in run mode
- [OpenCode Server](https://opencode.ai/docs/server/) -- serve command API endpoints
- [OpenCode SDK](https://opencode.ai/docs/sdk/) -- JS/TS SDK reference

### GitHub (MEDIUM confidence)
- [OpenCode Repository](https://github.com/opencode-ai/opencode) -- Source, releases
- [Kimi K2.5 PR #10835](https://github.com/anomalyco/opencode/pull/10835) -- Moonshot provider registration
- [Subagent Hang Issue #6573](https://github.com/anomalyco/opencode/issues/6573) -- REST API subagent bug
- [CLI Run Feature #2330](https://github.com/anomalyco/opencode/issues/2330) -- Non-interactive run with --command
- [Python SDK](https://github.com/sst/opencode-sdk-python) -- Pre-release Python client

### Ecosystem Analysis (LOW-MEDIUM confidence)
- [opencode-workspace](https://github.com/kdcokenny/opencode-workspace) -- Multi-agent config-based orchestration patterns
- [DeepWiki: OpenCode Python SDK](https://deepwiki.com/sst/opencode-sdk-python) -- SDK API surface analysis
- [DeepWiki: Agent Configuration](https://deepwiki.com/sst/opencode/3.2-agent-configuration) -- Agent system internals
- [Kimi K2.5 on OpenRouter](https://openrouter.ai/moonshotai/kimi-k2.5) -- Model availability and pricing
- [Moonshot AI Platform](https://platform.moonshot.ai/docs/guide/kimi-k2-5-quickstart) -- Direct API access
