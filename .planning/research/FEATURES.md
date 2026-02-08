# Feature Landscape

**Domain:** Multi-agent team coordination for OpenCode (replacing Claude Code spawning)
**Researched:** 2026-02-07
**Overall Confidence:** MEDIUM -- OpenCode agent ecosystem is well-documented but rapidly evolving; spawning patterns vary across community projects with no single canonical approach.

## Table Stakes

Features users expect. Missing = product feels incomplete or broken.

| # | Feature | Why Expected | Complexity | Notes |
|---|---------|--------------|------------|-------|
| T1 | **OpenCode binary discovery** | Replaces `shutil.which("claude")` -- system won't start without finding the right binary | Low | Same pattern as existing `discover_claude_binary()`. Just swap to `which("opencode")`. |
| T2 | **Non-interactive spawn via `opencode run`** | The fundamental act of creating a teammate. OpenCode's `run` command accepts prompts non-interactively: `opencode run --model provider/model --agent <name> "<prompt>"` | Medium | Must construct correct CLI invocation. Flags: `--model`, `--agent`, `--format json`, `--quiet`. Model format is `provider/model` (e.g., `novita/kimi-k2.5`). |
| T3 | **Dynamic agent config generation** | OpenCode agents are defined via markdown files in `.opencode/agents/`. Each spawned teammate needs its own agent definition with system prompt, tool permissions, and model override. Without this, spawned agents have no team awareness. | High | Must generate `.opencode/agents/<name>.md` with frontmatter (description, mode, model, tools) and system prompt body containing team identity, inbox instructions, MCP tool usage. |
| T4 | **System prompt injection for team awareness** | Spawned OpenCode agents have no native concept of "teams." The system prompt is the ONLY mechanism to teach an agent its identity (`agent_id`), team name, how to use inbox tools, task tools, and coordination protocol. | High | This is the single most critical feature. The prompt must include: agent identity, team name, available MCP tools for coordination, how to read/poll inbox, how to update tasks, and shutdown protocol. |
| T5 | **MCP server auto-configuration for teammates** | Spawned agents need `claude-teams` MCP server configured so they can call team tools (read_inbox, send_message, task_update, etc.). Without MCP access, agents are isolated. | Medium | Options: (a) generate per-agent `opencode.json` with MCP config, (b) use project-level `.opencode/opencode.json` that all agents share, (c) rely on global config. Option (b) is simplest since all teammates share the same MCP server. |
| T6 | **Tmux-based process spawning** | Existing infrastructure uses tmux for process isolation. OpenCode supports tmux integration. Teammates need separate terminal sessions. | Medium | Use `tmux split-window` or `tmux new-window` to run `opencode run ...` commands. Capture pane IDs for lifecycle management. Same pattern as existing code, different binary invocation. |
| T7 | **Model specification translation** | Claude Code uses shorthand (`sonnet`, `opus`, `haiku`). OpenCode requires `provider/model` format (e.g., `novita/kimi-k2.5`). The server API must translate or accept the correct format. | Low | Update the `model` parameter in `spawn_teammate_tool` from Claude Code shorthand to OpenCode format. Default should be Kimi K2.5 via configured provider. |
| T8 | **Agent lifecycle management** | Create, track, and terminate spawned agents. This is already implemented but must work with OpenCode processes instead of Claude Code processes. | Medium | Existing `force_kill_teammate` kills tmux panes -- this still works. Need to verify OpenCode processes terminate cleanly when tmux pane is killed. |
| T9 | **Remove Claude Code-specific code paths** | Current spawner builds Claude Code commands with `--agent-id`, `--team-name`, `--parent-session-id`, etc. These flags don't exist in OpenCode. Leaving them causes spawn failures. | Medium | Rewrite `build_spawn_command()` entirely. Remove `CLAUDECODE=1` and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` env vars. Remove all Claude-specific CLI flags. |
| T10 | **Inbox-based messaging** (existing) | Already implemented and working. Teammates communicate via JSON inboxes. No changes needed for OpenCode migration -- this is MCP-server-side, not client-side. | None | Keep as-is. The messaging layer is client-agnostic. |
| T11 | **Task management with dependencies** (existing) | Already implemented. Tasks with status tracking, ownership, blocks/blockedBy DAG. No changes needed. | None | Keep as-is. Pure server-side logic. |
| T12 | **Shutdown protocol** (existing) | Already implemented. Graceful shutdown requests/responses via messaging, force kill via tmux. Minor adaptation needed for OpenCode process cleanup. | Low | Verify OpenCode handles SIGTERM cleanly when tmux pane is killed. |

## Differentiators

Features that set this product apart from other OpenCode multi-agent approaches (swarm-tools, OpenAgentsControl, oh-my-opencode). Not expected, but valuable.

| # | Feature | Value Proposition | Complexity | Notes |
|---|---------|-------------------|------------|-------|
| D1 | **Structured task DAG with dependency enforcement** | Most OpenCode multi-agent tools use flat task lists or ad-hoc coordination. This server enforces `blocks`/`blockedBy` relationships with cycle detection and status transition validation. swarm-tools has basic task tracking but no dependency enforcement. | Already built | Existing `tasks.py` already implements this. Major differentiator vs. swarm-tools' flat `.hive/` cells and oh-my-opencode's todo-based tracking. |
| D2 | **Protocol-level shutdown negotiation** | swarm-tools uses simple `/handoff`, oh-my-opencode has no graceful shutdown. This server implements request/response shutdown with approval gates, preventing data loss from abrupt termination. | Already built | Existing `ShutdownRequest`/`ShutdownApproved` models. Unique in the ecosystem. |
| D3 | **Plan approval protocol** | The lead agent can require plan approval before a teammate proceeds. This prevents expensive mistakes from autonomous agents. Similar to OpenAgentsControl's approval gates but integrated into the messaging system rather than requiring a separate framework. | Already built | Existing `plan_approval_response` message type. |
| D4 | **File reservation / lock tracking** | Prevent multiple agents from editing the same file simultaneously. swarm-tools implements this via its actor-model messaging. This server currently lacks it. | Medium | Not in current codebase. swarm-tools' file reservation is a proven pattern. Would add a `file_reserve` / `file_release` tool pair. Track reservations in team config or separate lock file. |
| D5 | **Agent health monitoring** | Detect when a spawned agent has crashed, hung, or completed. Currently relies on manual checking. Automated health checks (tmux pane alive? last inbox activity?) would improve reliability. | Medium | Check if tmux pane still exists via `tmux has-session` / `tmux list-panes`. Track last activity timestamp per agent. Auto-cleanup dead agents. |
| D6 | **Progress checkpoints** | Agents report progress at defined intervals (25/50/75%). swarm-tools implements this. Useful for long-running tasks where the lead needs visibility without polling. | Low | Add a `checkpoint` message type. Agents send structured progress updates via existing messaging. Lead can query checkpoint history. |
| D7 | **Context-efficient inbox** | swarm-tools limits inbox to 5 messages and excludes bodies by default to prevent context bloat in agent windows. Current implementation returns all messages including full text, which can consume agent context rapidly. | Low | Add `max_messages` parameter to `read_inbox` and `poll_inbox`. Add `summary_only` mode that returns summaries without full text. Already have `summary` field on `InboxMessage`. |
| D8 | **Agent specialization templates** | Pre-defined agent templates (researcher, coder, reviewer, scribe) with appropriate tool permissions and system prompts. Rather than requiring the lead to specify full prompts, provide shorthand for common roles. | Low | Templates are just markdown files with preset system prompts and tool permissions. Store in `src/claude_teams/templates/` or as bundled resources. |
| D9 | **Working directory isolation** | Each agent works in a separate directory or git worktree to prevent file conflicts. opencode-workspace's worktree plugin and agent-of-empires both implement this. | High | Git worktree creation adds significant complexity. Simpler approach: allow specifying `cwd` per agent (already in model) and ensure agents stay in their directory via system prompt instructions. Full worktree isolation is a stretch goal. |
| D10 | **Broadcast with filtering** | Current broadcast sends to ALL teammates. Add role-based or tag-based filtering (e.g., broadcast to all "coder" agents but not "reviewer" agents). | Low | Add optional `role` or `tags` filter to broadcast. Check `agent_type` field on `TeammateMember`. |
| D11 | **Desktop app spawning (non-tmux)** | PROJECT.md mentions optional desktop app spawning. OpenCode has a web UI mode via `opencode serve`. Could spawn agents via HTTP API rather than tmux. | High | `opencode serve` starts HTTP server. Could use `opencode run --attach http://localhost:<port>` to connect. Would need separate port per agent. Significantly more complex than tmux approach. Defer unless specifically requested. |

## Anti-Features

Features to explicitly NOT build. These are tempting but harmful.

| # | Anti-Feature | Why Avoid | What to Do Instead |
|---|--------------|-----------|-------------------|
| A1 | **Recursive agent spawning** | oh-my-opencode discovered (issue #535) that background agents recursively spawning subagents creates exponential cascades (800+ tasks from one request). Teammates should never spawn other teammates. | Only the team lead can call `spawn_teammate`. System prompt for teammates must explicitly prohibit spawning. Enforce at MCP tool level: restrict `spawn_teammate` tool to the lead's agent ID. |
| A2 | **Autonomous team formation** | Agents deciding on their own to create teams, recruit members, or restructure coordination. This leads to runaway resource consumption and unpredictable behavior. | Team creation and membership are human-initiated via the lead agent. Agents work within the team structure they're given. |
| A3 | **Shared context windows** | Cognition.ai argues for "shared full agent traces." While theoretically better, piping full conversation history between agents bloats context, increases cost, and creates circular dependency problems. Each agent should have its own focused context. | Use structured messages (inbox) with summaries. Each agent maintains its own context window. Results flow through inbox messages, not shared state. This matches OpenCode's native subagent model where "only the distilled result comes back." |
| A4 | **Real-time streaming between agents** | Building WebSocket or SSE channels between agents for live updates. Over-engineers the coordination layer and creates tight coupling. | Polling-based inbox (existing `poll_inbox` with 30s timeout) is sufficient. Agents don't need sub-second coordination. If an agent needs a result, it polls. |
| A5 | **Too many specialized agent types** | MetaGPT uses 5 agents, ChatDev uses 7. Research shows 3 focused agents outperform 7 generic ones in token efficiency. Don't build a framework that encourages 10+ agent types. | Recommend 2-4 agents per team. System prompt templates for common roles (coder, reviewer, researcher). Warn in docs against over-specialization. |
| A6 | **Semantic memory / vector embeddings** | swarm-tools includes a "Hivemind" with Ollama embeddings for cross-session learning. This adds an external dependency (Ollama), significant complexity, and questionable value for short-lived coding teams. | File-based task history is sufficient. If cross-session learning is needed later, it's a separate concern from team coordination. |
| A7 | **Git-backed coordination state** | swarm-tools stores all state in `.hive/` and syncs via git. This means coordination artifacts pollute the repo, create merge conflicts, and leak team internals to version control. | Keep state in `~/.claude/` (outside repo). Coordination is ephemeral -- teams are created, work is done, teams are deleted. No need to version-control inbox messages. |
| A8 | **Provider-specific LLM features** | Building features that only work with Kimi K2.5 (specific API parameters, token counting, etc.). The MCP server should be model-agnostic. | The server coordinates agents; it doesn't call LLMs directly. Model selection is passed to `opencode run --model`. If the user switches from Kimi K2.5 to Claude or GPT, coordination should still work. |
| A9 | **Web UI / dashboard** | Building a monitoring dashboard for agent teams. Attractive but a massive scope expansion that distracts from core coordination. | tmux provides visual monitoring out of the box. `task_list` and `read_inbox` tools provide programmatic visibility. A dashboard is a separate project. |
| A10 | **Hybrid Claude Code + OpenCode mode** | PROJECT.md explicitly states "Replace Claude Code entirely (not hybrid)." Don't maintain dual code paths. | Clean replacement. Remove all Claude Code specifics. If someone needs Claude Code teams, they use the original implementation (pre-fork). |

## Feature Dependencies

```
T1 (binary discovery) --> T2 (spawn command)
T3 (agent config gen) --> T4 (system prompt)
T3 (agent config gen) --> T5 (MCP config)
T2 (spawn command) --> T6 (tmux spawning)
T7 (model translation) --> T2 (spawn command)
T9 (remove claude paths) --> T2 (spawn command)

T4 (system prompt) --> D1 (task DAG) [prompt must explain task tools]
T4 (system prompt) --> D2 (shutdown protocol) [prompt must explain shutdown]
T4 (system prompt) --> D3 (plan approval) [prompt must explain approval]
T4 (system prompt) --> A1 (no recursive spawning) [prompt must prohibit spawning]

D4 (file reservation) --> T4 (system prompt) [prompt must explain file locking]
D5 (health monitoring) --> T8 (lifecycle management)
D7 (context-efficient inbox) --> T10 (inbox messaging)
D8 (agent templates) --> T3 (agent config gen)
```

**Critical path:** T1 -> T7 -> T9 -> T2 -> T6 (get basic spawning working), then T3 -> T4 -> T5 (add team awareness).

## MVP Recommendation

**Phase 1 -- Functional spawning (Table Stakes):**

Prioritize in this order:
1. T1: OpenCode binary discovery
2. T7: Model specification translation (`provider/model` format)
3. T9: Remove Claude Code-specific code paths
4. T2: Non-interactive spawn via `opencode run`
5. T6: Tmux-based process spawning
6. T3: Dynamic agent config generation (`.opencode/agents/<name>.md`)
7. T4: System prompt injection for team awareness
8. T5: MCP server auto-configuration for teammates
9. T8: Agent lifecycle management (verify with OpenCode)
10. T12: Shutdown protocol verification

**Phase 2 -- Reliability (Differentiators that prevent failures):**
1. D5: Agent health monitoring (detect dead agents)
2. D7: Context-efficient inbox (prevent context bloat)
3. A1 enforcement: Restrict `spawn_teammate` to lead only

**Phase 3 -- Power features (Differentiators for productivity):**
1. D4: File reservation / lock tracking
2. D6: Progress checkpoints
3. D8: Agent specialization templates
4. D10: Broadcast with filtering

**Defer indefinitely:**
- D9: Working directory isolation via git worktrees (too complex, low ROI for initial milestone)
- D11: Desktop app spawning (niche use case, can add later if requested)

## Key Implementation Notes

### OpenCode Spawn Command Construction

The core spawn command replaces `build_spawn_command()`:

```bash
cd <cwd> && opencode run \
  --model <provider/model> \
  --agent <agent-name> \
  --format json \
  --quiet \
  "<initial-prompt>"
```

Where `<agent-name>` corresponds to a dynamically generated `.opencode/agents/<agent-name>.md` file.

### Agent Config File Format

Each spawned teammate needs a file at `.opencode/agents/<name>.md`:

```markdown
---
description: "Team worker for <team-name>"
mode: primary
model: novita/kimi-k2.5
tools:
  write: true
  edit: true
  bash: true
  read: true
permission:
  bash:
    "*": ask
---

You are <agent-name>, a member of team "<team-name>".
Your agent ID is <agent-name>@<team-name>.

## How to Coordinate

Use these MCP tools from the claude-teams server:
- `read_inbox(team_name, agent_name)` -- check for messages
- `send_message(team_name, type, ...)` -- communicate with team lead
- `task_list(team_name)` -- see available tasks
- `task_update(team_name, task_id, ...)` -- update task status

## Rules
1. Check your inbox FIRST before starting work
2. Update task status as you progress
3. Send completion messages when done
4. NEVER call spawn_teammate -- only the lead can spawn agents
5. Respond to shutdown requests promptly
```

### Model Provider Format

OpenCode uses `provider/model` format. The existing `Literal["sonnet", "opus", "haiku"]` parameter must be replaced:

```python
# Old (Claude Code)
model: Literal["sonnet", "opus", "haiku"] = "sonnet"

# New (OpenCode)
model: str = "novita/kimi-k2.5"  # or whatever the configured default is
```

The model string passes directly to `opencode run --model <value>`.

## Competitive Landscape

| Feature | This Project | swarm-tools | OpenAgentsControl | oh-my-opencode | opencode-workspace |
|---------|-------------|-------------|-------------------|----------------|-------------------|
| Task dependencies (DAG) | Yes (built) | No (flat) | No | No | No |
| Shutdown negotiation | Yes (built) | No | No | No | No |
| Plan approval | Yes (built) | No | Yes | No | No |
| File reservation | No (planned) | Yes | No | No | No |
| Agent health monitoring | No (planned) | No | No | Yes (BackgroundManager) | No |
| Context-efficient inbox | No (planned) | Yes (5-msg limit) | No | No | No |
| Cross-session learning | No (anti-feature) | Yes (Hivemind) | No | No | No |
| Git-backed state | No (anti-feature) | Yes (.hive/) | No | No | No |
| Kimi K2.5 focus | Yes | No | No | No | No |
| MCP-native coordination | Yes | Yes | No (agent-only) | No (hooks) | Partial (plugins) |

## Sources

- [OpenCode Agents docs](https://opencode.ai/docs/agents/) -- HIGH confidence
- [OpenCode CLI docs](https://opencode.ai/docs/cli/) -- HIGH confidence
- [OpenCode Config docs](https://opencode.ai/docs/config/) -- HIGH confidence
- [OpenCode Tools docs](https://opencode.ai/docs/tools/) -- HIGH confidence
- [swarm-tools](https://github.com/joelhooks/swarm-tools) -- MEDIUM confidence (community project, well-documented)
- [OpenAgentsControl](https://github.com/darrenhinde/OpenAgentsControl) -- MEDIUM confidence (community project)
- [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode) -- MEDIUM confidence (community project, actively maintained)
- [opencode-workspace](https://github.com/kdcokenny/opencode-workspace) -- MEDIUM confidence (community project)
- [opencode-background-agents](https://github.com/kdcokenny/opencode-background-agents) -- MEDIUM confidence
- [joelhooks/opencode-config](https://github.com/joelhooks/opencode-config) -- MEDIUM confidence (real-world usage reference)
- [How Coding Agents Actually Work: Inside OpenCode](https://cefboud.com/posts/coding-agents-internals-opencode-deepdive/) -- MEDIUM confidence (deep technical analysis)
- [Cognition.ai: Don't Build Multi-Agents](https://cognition.ai/blog/dont-build-multi-agents) -- HIGH confidence (authoritative industry perspective)
- [OpenCode tmux feature request #1247](https://github.com/anomalyco/opencode/issues/1247) -- HIGH confidence (official repo)
- [oh-my-opencode recursive spawning bug #535](https://github.com/code-yeongyu/oh-my-opencode/issues/535) -- HIGH confidence (documented real-world failure)
