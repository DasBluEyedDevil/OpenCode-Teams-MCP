# OpenCode Teams MCP

## What This Is

An MCP server that enables multi-agent team coordination for OpenCode with Kimi K2.5. Replaces Claude Code-specific team spawning with OpenCode-native approach while preserving the existing team/task/messaging infrastructure.

## Core Value

Kimi K2.5 agents in OpenCode can coordinate as teams with shared task lists and messaging, just like Claude Code agents can today.

## Requirements

### Validated

<!-- Existing capabilities from codebase -->

- ✓ Team lifecycle management (create, delete, read config) — existing
- ✓ Task management with status tracking and dependencies — existing
- ✓ Inbox-based messaging between agents — existing
- ✓ File-based persistence under ~/.claude/ — existing
- ✓ Concurrency-safe operations (file locking, atomic writes) — existing
- ✓ MCP server exposing all coordination primitives — existing
- ✓ Broadcast and direct messaging — existing
- ✓ Shutdown request/response protocol — existing
- ✓ Plan approval protocol — existing

### Active

<!-- New capabilities to build -->

- [ ] OpenCode binary discovery and validation
- [ ] OpenCode-compatible spawn command construction
- [ ] Dynamic agent config generation with team context
- [ ] System prompt injection for team awareness
- [ ] Model specification translation (Kimi K2.5 format)
- [ ] Tmux spawning with OpenCode CLI
- [ ] Desktop app spawning support (optional)
- [ ] Remove Claude Code-specific code paths

### Out of Scope

- Claude Code backward compatibility — full replacement, not hybrid
- Custom OpenCode fork — use standard OpenCode CLI
- Alternative coordination systems (swarm-tools, etc.) — keep existing protocol
- Non-Kimi models in OpenCode — focus on Kimi K2.5

## Context

**Existing codebase**: Python MCP server using FastMCP. Spawner module (`spawner.py`) currently builds Claude Code commands with flags like `--agent-id`, `--team-name`, `--parent-session-id`. These flags don't exist in OpenCode.

**OpenCode approach**: Agents receive context via markdown files (`.opencode/agents/<name>.md`) with system prompts. MCP servers provide tools. No native team flags, but all building blocks exist.

**Key architectural change**: Instead of relying on Claude Code's native team awareness, we inject team context via:
1. Dynamically generated agent config files
2. System prompt with agent identity, team name, inbox instructions
3. claude-teams MCP server for messaging/task coordination

**Research sources**:
- [OpenCode CLI docs](https://opencode.ai/docs/cli/)
- [OpenCode Agents docs](https://opencode.ai/docs/agents/)
- [swarm-tools](https://github.com/joelhooks/swarm-tools) - reference for OpenCode multi-agent patterns

## Constraints

- **Runtime**: OpenCode CLI must be on PATH (replaces claude binary requirement)
- **Process**: Keep tmux spawning for CLI; optionally support desktop app spawning
- **Persistence**: Keep existing ~/.claude/ storage layout for compatibility
- **MCP**: Teammates must have claude-teams MCP server configured
- **Model**: Default to Kimi K2.5 via configured provider (e.g., Novita AI)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Replace Claude Code entirely (not hybrid) | User wants Kimi-only teams, simpler implementation | — Pending |
| Dynamic agent config generation | OpenCode agents need .md files for system prompts | — Pending |
| Keep existing storage layout | Preserve compatibility with team/task file structure | — Pending |
| Support both CLI and desktop spawning | User requested flexibility | — Pending |

---
*Last updated: 2026-02-07 after initialization*
