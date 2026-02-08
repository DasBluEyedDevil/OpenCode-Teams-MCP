# Architecture Patterns

**Domain:** Multi-agent team coordination -- OpenCode spawning integration
**Researched:** 2026-02-07
**Overall Confidence:** MEDIUM (OpenCode is well-documented for CLI/agent config; spawning automation patterns are emerging but less standardized)

## Executive Summary

The existing codebase has a clean three-layer architecture: MCP server (server.py) -> Domain logic (teams/tasks/messaging/spawner) -> Filesystem persistence (~/.claude/). The spawner module is the **only** component that needs replacement. Everything else -- team lifecycle, task management, inbox messaging, file persistence, concurrency controls -- remains unchanged.

The core architectural challenge is that Claude Code has native team-awareness flags (`--agent-id`, `--team-name`, `--parent-session-id`) baked into its CLI, while OpenCode has **no equivalent**. OpenCode agents receive context through: (1) agent config files with system prompts, (2) MCP server tools, and (3) the `opencode run` command's `--agent` flag. The integration must bridge this gap by dynamically generating agent config files that inject team context before spawning.

## Recommended Architecture

### Current vs. Target Architecture

**Current flow (Claude Code):**
```
server.py -> spawner.py -> build_spawn_command() -> tmux split-window "claude --agent-id X --team-name Y ..."
```

**Target flow (OpenCode):**
```
server.py -> spawner.py -> generate_agent_config() -> write .opencode/agents/<name>.md
                        -> build_spawn_command()   -> tmux split-window "opencode run --agent <name> 'initial prompt'"
```

The key difference: Claude Code receives team identity via CLI flags at process start. OpenCode receives team identity via a pre-written agent config file that includes a system prompt with team awareness instructions.

### Component Diagram

```
+------------------+
| MCP Client       |  (team lead -- OpenCode instance)
| (team-lead)      |
+--------+---------+
         |  MCP tool calls
         v
+------------------+     +-------------------+
| server.py        |---->| teams.py          |  Team lifecycle (UNCHANGED)
| (MCP Server)     |---->| tasks.py          |  Task management (UNCHANGED)
|                  |---->| messaging.py      |  Inbox system (UNCHANGED)
|                  |---->| spawner.py        |  ** REPLACE **
+------------------+     +---+---------------+
                              |
                    +---------+---------+
                    |                   |
                    v                   v
          +------------------+  +------------------+
          | config_gen.py    |  | tmux subprocess   |
          | (NEW)            |  | (MODIFIED)        |
          |                  |  |                   |
          | Writes:          |  | Runs:             |
          | .opencode/agents |  | opencode run      |
          | /<name>.md       |  | --agent <name>    |
          +------------------+  | "initial prompt"  |
                                +------------------+
                                         |
                                         v
                              +------------------+
                              | OpenCode Instance |
                              | (teammate)        |
                              |                   |
                              | Reads:            |
                              | - Agent config    |
                              | - MCP tools from  |
                              |   claude-teams    |
                              +------------------+
```

### Component Boundaries

| Component | Responsibility | Communicates With | Change Status |
|-----------|---------------|-------------------|---------------|
| `server.py` | MCP tool definitions, parameter validation, lifespan | teams, tasks, messaging, spawner | MINOR CHANGES (model enum, lifespan binary discovery) |
| `teams.py` | Team lifecycle, config CRUD, member management | models, filesystem | UNCHANGED |
| `tasks.py` | Task CRUD, dependency DAG, status transitions | models, filesystem | UNCHANGED |
| `messaging.py` | Inbox read/write/append, file locking | models, filesystem | UNCHANGED |
| `spawner.py` | Binary discovery, command building, tmux spawning | teams, messaging, subprocess | MAJOR REWRITE |
| `models.py` | Pydantic data models | pydantic | MINOR CHANGES (model field values, backend_type) |
| `config_gen.py` (NEW) | Generate .opencode/agents/*.md files with team context | filesystem | NEW MODULE |

### What Changes, What Stays

**UNCHANGED (75% of codebase):**
- `teams.py` -- All team lifecycle operations
- `tasks.py` -- All task management
- `messaging.py` -- All inbox operations
- `conftest.py` -- Test fixtures (base_dir pattern works for both)
- Storage layout: `~/.claude/teams/`, `~/.claude/tasks/`, inboxes

**MODIFIED (small changes):**
- `server.py` -- Change `discover_claude_binary` to `discover_opencode_binary`, update model enum from `["sonnet", "opus", "haiku"]` to OpenCode model format, update lifespan context
- `models.py` -- Update `TeammateMember.model` default/allowed values, possibly add `agent_config_path` field

**REPLACED (spawner.py):**
- `discover_claude_binary()` -> `discover_opencode_binary()`
- `build_spawn_command()` -> completely new implementation
- `spawn_teammate()` -> new flow: generate agent config -> build command -> tmux spawn

**NEW (config_gen.py):**
- `generate_agent_config()` -- Writes `.opencode/agents/<name>.md` with YAML frontmatter and team-aware system prompt
- `cleanup_agent_config()` -- Removes config file when teammate is shut down

## Data Flow

### Spawning Flow (Target)

```
1. Team lead calls spawn_teammate(team_name, name, prompt, model)
     |
2. spawner.py validates name (existing logic)
     |
3. spawner.py calls config_gen.generate_agent_config()
     |   Writes: .opencode/agents/<name>.md
     |   Contains:
     |     ---
     |     description: "Team member: <name> on team <team_name>"
     |     model: "novita/moonshotai/kimi-k2.5"
     |     mode: primary
     |     ---
     |     You are <name>, a member of team "<team_name>".
     |     Your agent ID is <name>@<team_name>.
     |
     |     ## Communication
     |     Use the claude-teams MCP tools to:
     |     - read_inbox: Check for messages from team lead and teammates
     |     - send_message: Send messages to team lead or teammates
     |     - poll_inbox: Wait for new messages
     |
     |     ## Tasks
     |     Use task_get, task_update to manage assigned tasks.
     |     Always update task status as you work.
     |
     |     ## Shutdown Protocol
     |     When you receive a shutdown_request, approve it via send_message.
     |
4. spawner.py registers member in team config (existing logic)
     |
5. spawner.py creates inbox and sends initial prompt (existing logic)
     |
6. spawner.py builds tmux command:
     |   tmux split-window -dP -F "#{pane_id}" \
     |     "cd <cwd> && opencode run --agent <name> '<initial_prompt>'"
     |
7. Captures pane_id, updates config (existing logic)
```

### How Team Context Reaches OpenCode Instances

There are three channels through which a spawned OpenCode teammate receives team awareness:

**Channel 1: Agent Config File (identity + behavior)**
- Written to `.opencode/agents/<name>.md` before spawn
- Contains: agent name, team name, agent ID, communication protocol instructions
- OpenCode loads this automatically when `--agent <name>` is specified
- This replaces Claude Code's `--agent-id`, `--team-name`, `--agent-name` flags

**Channel 2: MCP Server Tools (coordination primitives)**
- The spawned OpenCode instance must have `claude-teams` MCP server configured in its `opencode.json`
- This provides: `read_inbox`, `send_message`, `poll_inbox`, `task_get`, `task_update`, etc.
- This replaces Claude Code's built-in team awareness with explicit tool calls

**Channel 3: Initial Prompt (task assignment)**
- Passed as the argument to `opencode run --agent <name> "<prompt>"`
- Also written to the agent's inbox (existing behavior)
- The prompt tells the agent what to do; the agent config tells it who it is

### MCP Configuration Requirement

For spawned teammates to access team coordination tools, the project's `opencode.json` must include the claude-teams MCP server. This is a **project-level prerequisite**, not something the spawner generates per-agent:

```json
{
  "mcp": {
    "claude-teams": {
      "type": "local",
      "command": ["claude-teams"],
      "enabled": true
    }
  }
}
```

**Confidence: MEDIUM** -- OpenCode's MCP config is per-project (opencode.json), not per-agent. All agents in the same project directory share the same MCP servers. This is actually simpler than trying to inject MCP config per-spawn.

### Shutdown and Cleanup Flow

```
1. Team lead sends shutdown_request via send_message tool
     |
2. Teammate receives shutdown_request in inbox
     |
3. Teammate approves via send_message(type="shutdown_response", approve=True)
     |
4. Team lead calls process_shutdown_approved
     |  - Removes member from team config
     |  - Resets owned tasks
     |
5. spawner.cleanup_agent_config(name)   ** NEW **
     |  - Deletes .opencode/agents/<name>.md
     |
6. tmux pane exits naturally (opencode run completes)
   OR force_kill_teammate kills the pane
```

## Patterns to Follow

### Pattern 1: Agent Config as Identity Injection

**What:** Generate a markdown agent file that serves as the "birth certificate" for a spawned teammate, containing everything it needs to know about its identity and team membership.

**When:** Every time a teammate is spawned.

**Why:** OpenCode has no built-in team awareness. The agent config file is the only way to inject persistent identity context that survives the entire session.

**Example:**
```python
def generate_agent_config(
    agent_name: str,
    team_name: str,
    model: str,
    agent_type: str = "general-purpose",
    cwd: str | None = None,
) -> Path:
    """Write .opencode/agents/<name>.md with team-aware system prompt."""
    agents_dir = Path(cwd or Path.cwd()) / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    config_path = agents_dir / f"{agent_name}.md"
    config_path.write_text(
        f"---\n"
        f"description: \"Team member: {agent_name} ({agent_type})\"\n"
        f"model: \"{model}\"\n"
        f"---\n\n"
        f"You are **{agent_name}**, a member of team **{team_name}**.\n"
        f"Your agent ID is `{agent_name}@{team_name}`.\n\n"
        f"## Team Protocol\n\n"
        f"1. Check your inbox regularly using `read_inbox`\n"
        f"2. Update task status as you work using `task_update`\n"
        f"3. Send progress updates to team-lead using `send_message`\n"
        f"4. When you receive a `shutdown_request`, wrap up and approve it\n"
    )
    return config_path
```

### Pattern 2: Command Construction for opencode run

**What:** Build the tmux spawn command using `opencode run` with the `--agent` flag.

**When:** After agent config is written and member is registered.

**Example:**
```python
def build_spawn_command(
    member: TeammateMember,
    opencode_binary: str,
) -> str:
    team_name = member.agent_id.split("@", 1)[1]
    cmd = (
        f"cd {shlex.quote(member.cwd)} && "
        f"{shlex.quote(opencode_binary)} run "
        f"--agent {shlex.quote(member.name)} "
        f"{shlex.quote(member.prompt)}"
    )
    return cmd
```

Note: The `--model` flag is redundant here because the model is already specified in the agent config file. But it could be passed as a belt-and-suspenders measure.

### Pattern 3: Preserving the base_dir Testing Pattern

**What:** The existing codebase uses `base_dir: Path | None = None` parameters throughout to allow tests to use `tmp_path` instead of `~/.claude/`. The new config_gen module should follow this same pattern for the `.opencode/agents/` directory.

**When:** Always, for testability.

**Example:**
```python
def generate_agent_config(
    agent_name: str,
    team_name: str,
    model: str,
    agents_dir: Path | None = None,  # defaults to .opencode/agents/ in cwd
) -> Path:
    ...
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Per-Agent opencode.json Generation

**What:** Generating a separate `opencode.json` for each spawned agent to configure its MCP servers.

**Why bad:** OpenCode's config is project-scoped. Multiple agents in the same working directory share the same `opencode.json`. Overwriting it per-spawn would break other running agents. The MCP configuration should be a one-time project setup, not a per-spawn operation.

**Instead:** Document that the project's `opencode.json` must include the `claude-teams` MCP server. Validate this at spawn time and raise a clear error if missing.

### Anti-Pattern 2: Using opencode serve + SDK for Spawning

**What:** Starting an `opencode serve` instance and using the SDK/REST API to create sessions programmatically.

**Why bad:** There is a known issue (GitHub #6573) where sessions hang indefinitely when the Task tool spawns subagents via the REST API. The `opencode run` CLI approach is simpler, more reliable, and matches the existing tmux split-window pattern. The serve API adds unnecessary complexity for this use case.

**Instead:** Use `opencode run --agent <name> "<prompt>"` in a tmux split-window, exactly like the current Claude Code spawning but with different command construction.

### Anti-Pattern 3: Relying on OpenCode's Built-in Subagent System

**What:** Using OpenCode's `mode: subagent` agent type and `@agent` mentions for team coordination.

**Why bad:** OpenCode's subagent system runs within the same process/session. Team coordination requires separate processes with independent contexts, separate inboxes, and the ability to run in parallel tmux panes. The built-in subagent system is for within-session delegation, not multi-process team orchestration.

**Instead:** Use `mode: primary` for all spawned agents. They are independent processes that coordinate through the claude-teams MCP server.

### Anti-Pattern 4: Modifying ~/.config/opencode/agents/ (Global Config)

**What:** Writing agent configs to the global `~/.config/opencode/agents/` directory.

**Why bad:** Global agents persist across all projects and sessions. Team-specific agents should be scoped to the project directory (`.opencode/agents/`) so they are created and cleaned up with the team lifecycle. Global pollution would leak agent definitions between unrelated projects.

**Instead:** Always write to `.opencode/agents/` in the project working directory.

## Key Architectural Decisions

### Decision 1: opencode run vs. opencode serve

**Recommendation: Use `opencode run`**

| Criterion | opencode run | opencode serve + SDK |
|-----------|-------------|---------------------|
| Simplicity | Single command, matches existing pattern | Requires server lifecycle management |
| Reliability | Well-tested CLI path | Known session hang bug (#6573) |
| Process isolation | Each agent is a separate process | Sessions share server process |
| tmux integration | Natural fit (command in split-window) | Extra complexity (attach to server) |
| Monitoring | Each pane shows agent output | Server logs aggregated |

**Confidence: HIGH** -- The `opencode run` pattern directly mirrors the existing `claude` CLI spawning pattern, minimizing architectural changes.

### Decision 2: Agent Config Location

**Recommendation: `.opencode/agents/` in project directory**

- Project-scoped (not global)
- Automatically picked up by `opencode run --agent <name>`
- Can be cleaned up per-team without affecting other projects
- Matches OpenCode's documented per-project agent convention

**Confidence: HIGH** -- This is explicitly documented in OpenCode's agent docs.

### Decision 3: Model Specification Format

**Recommendation: Use `provider/model` format in agent config**

OpenCode uses the `provider/model` format (e.g., `novita/moonshotai/kimi-k2.5` or `moonshot-ai/kimi-k2.5`). The spawner's model parameter should accept this format directly rather than translating from short names.

The `spawn_teammate` tool's `model` parameter should change from:
```python
model: Literal["sonnet", "opus", "haiku"] = "sonnet"
```
to:
```python
model: str = "novita/moonshotai/kimi-k2.5"
```

**Confidence: MEDIUM** -- The exact provider/model ID format for Kimi K2.5 depends on the user's configured provider (Novita, Moonshot direct, OpenRouter). The default should be configurable.

### Decision 4: fcntl File Locking on Windows

**Observation:** The existing codebase uses `fcntl.flock()` for concurrent file access (messaging.py, tasks.py). The `fcntl` module is POSIX-only and does not exist on Windows.

**Impact on OpenCode migration:** This is not directly related to the spawning change, but since the project context mentions `platform: win32`, this is a pre-existing issue that will surface. The spawning changes should not make this worse, but it is worth noting that the current codebase cannot run on Windows without addressing `fcntl`.

**Confidence: HIGH** -- `fcntl` is documented as POSIX-only in Python stdlib.

## Scalability Considerations

| Concern | 2-3 agents | 5-10 agents | 10+ agents |
|---------|-----------|-------------|------------|
| Agent config files | Trivial | Trivial | Clean up matters |
| tmux panes | Works well | Gets crowded | Need tmux windows, not just panes |
| Inbox file locking | No contention | Rare contention | May need per-agent lock files |
| opencode.json MCP config | Shared, fine | Shared, fine | Shared, fine (N agents, 1 config) |
| opencode run processes | Low overhead | Moderate memory | Each is a full Node.js process |

## Suggested Build Order

Based on dependency analysis, the recommended implementation order:

### Phase 1: Spawner Core (no external dependencies on OpenCode)
1. **`discover_opencode_binary()`** -- Replace `discover_claude_binary()`. Same pattern (`shutil.which("opencode")`), different binary name.
2. **`config_gen.py`** -- New module for generating `.opencode/agents/<name>.md` files. Can be tested entirely in isolation with `tmp_path`.
3. **Unit tests for config generation** -- Verify frontmatter format, system prompt content, file paths.

### Phase 2: Command Construction
4. **`build_spawn_command()`** -- New implementation using `opencode run --agent <name> "<prompt>"`. Can be tested as pure string construction (existing test pattern).
5. **Update `models.py`** -- Change model field defaults/types to OpenCode format.
6. **Unit tests for command construction** -- Verify command format, quoting, flag presence.

### Phase 3: Integration
7. **`spawn_teammate()`** -- Wire together: config_gen -> register member -> create inbox -> build command -> tmux spawn. The tmux subprocess call itself is the same (`tmux split-window -dP -F "#{pane_id}" <cmd>`).
8. **`cleanup_agent_config()`** -- Add cleanup on shutdown/force-kill.
9. **Update `server.py`** -- Change lifespan, model parameter types, import paths.
10. **Integration tests** -- Test full spawn flow with mocked subprocess (existing test pattern).

### Phase 4: Cleanup
11. **Remove Claude Code artifacts** -- Delete `CLAUDECODE=1` env var setting, `--agent-id` flag construction, Claude-specific model names.
12. **Update documentation** -- README, pyproject.toml description.

**Build order rationale:** Each phase can be independently tested. Phase 1 has zero dependencies on the existing spawner. Phase 2 only depends on Phase 1. Phase 3 wires everything together. Phase 4 is cleanup that cannot break anything.

## Open Questions (Need Phase-Specific Research)

1. **Non-interactive mode reliability**: OpenCode's `opencode run` does not have a formal `--non-interactive` flag yet (GitHub issue #10411). If OpenCode prompts for permissions during execution, the tmux pane will hang. Mitigation: configure permissive permissions in agent config (`permission: { edit: "allow", bash: "allow" }`). Needs validation.

2. **Agent config hot-reload**: When a new agent config is written to `.opencode/agents/`, does an already-running OpenCode instance pick it up? If not, agent configs must be written BEFORE the `opencode run` command (which is the planned flow, so likely fine).

3. **Multiple simultaneous opencode run processes**: Can multiple `opencode run` instances operate in the same project directory concurrently? Each has its own session, but they share the same `opencode.json` and `.opencode/agents/` directory. This should work since each specifies its own `--agent` flag, but needs empirical validation.

4. **tmux on Windows**: The existing codebase uses tmux for spawning. The platform is `win32`. Tmux is not natively available on Windows (requires WSL or Git Bash). This is a pre-existing architectural constraint, not introduced by the OpenCode migration.

## Sources

- [OpenCode CLI documentation](https://opencode.ai/docs/cli/) -- HIGH confidence
- [OpenCode Agents documentation](https://opencode.ai/docs/agents/) -- HIGH confidence
- [OpenCode Config documentation](https://opencode.ai/docs/config/) -- HIGH confidence
- [OpenCode MCP servers documentation](https://opencode.ai/docs/mcp-servers/) -- HIGH confidence
- [OpenCode Server/SDK documentation](https://opencode.ai/docs/server/) -- HIGH confidence
- [OpenCode non-interactive mode issue #10411](https://github.com/anomalyco/opencode/issues/10411) -- HIGH confidence (issue is open)
- [OpenCode session hang issue #6573](https://github.com/sst/opencode/issues/6573) -- HIGH confidence (known bug)
- [OpenCode tmux support request #1247](https://github.com/anomalyco/opencode/issues/1247) -- HIGH confidence
- [joelhooks/opencode-config](https://github.com/joelhooks/opencode-config) -- MEDIUM confidence (community reference)
- [kdcokenny/opencode-workspace](https://github.com/kdcokenny/opencode-workspace) -- MEDIUM confidence (community reference)
- [joelhooks/swarm-tools](https://github.com/joelhooks/swarm-tools) -- MEDIUM confidence (community reference)
- [Kimi K2.5 OpenCode setup gist](https://gist.github.com/OmerFarukOruc/26262e9c883b3c2310c507fdf12142f4) -- MEDIUM confidence
- [OpenCode agent markdown frontmatter issue #3461](https://github.com/sst/opencode/issues/3461) -- HIGH confidence

---

*Architecture research: 2026-02-07*
