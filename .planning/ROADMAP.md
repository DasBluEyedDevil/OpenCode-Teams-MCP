# Roadmap: OpenCode Teams MCP

## Overview

This roadmap replaces the Claude Code spawning layer with OpenCode CLI + Kimi K2.5 support across 8 phases. The journey starts with low-level binary discovery and model configuration, builds up through agent config generation and spawn execution, validates inter-agent communication, then layers on reliability, templates, desktop support, and finally removes all legacy Claude Code paths. Each phase delivers an independently verifiable capability, and later phases depend on earlier ones being solid.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Binary Discovery & Model Configuration** - Find OpenCode on PATH and translate model specifications to Kimi K2.5 format ✓
- [x] **Phase 2: Agent Config Generation** - Dynamically generate `.opencode/agents/<name>.md` files with team context, MCP tools, and permissions ✓
- [x] **Phase 3: Spawn Execution** - Construct and execute `opencode run` commands in tmux panes with timeout protection ✓
- [x] **Phase 4: MCP Communication Validation** - Verify spawned agents can exchange messages and share state through the MCP server ✓
- [x] **Phase 5: Agent Health & Monitoring** - Detect dead/hung agents and force-kill unresponsive instances ✓
- [ ] **Phase 6: Agent Templates** - Pre-built role templates for common agent specializations
- [ ] **Phase 7: Desktop Spawning** - Support launching OpenCode desktop app as an alternative to CLI
- [ ] **Phase 8: Legacy Cleanup** - Remove all Claude Code-specific code paths, update tests and documentation

## Phase Details

### Phase 1: Binary Discovery & Model Configuration
**Goal**: The system can locate the OpenCode binary and translate any model specification into the correct Kimi K2.5 provider format
**Depends on**: Nothing (first phase)
**Requirements**: SPAWN-01, MODEL-01, MODEL-02, MODEL-03, MODEL-04
**Success Criteria** (what must be TRUE):
  1. Running the discovery function with OpenCode installed returns the binary path; running it without OpenCode installed returns a clear error
  2. Model name "sonnet", "opus", or "haiku" is translated to the correct `moonshot-ai/kimi-k2.5` provider string
  3. System can generate valid provider configuration for Novita AI, Moonshot, and OpenRouter backends
  4. Provider credentials are referenced correctly in generated configuration (not hardcoded)
  5. OpenCode version is validated as v1.1.52+ (minimum for Kimi K2.5 support)
**Plans:** 2 plans

Plans:
- [x] 01-01-PLAN.md -- OpenCode binary discovery, version validation, model translation, and provider config functions ✓
- [x] 01-02-PLAN.md -- Wire discovery and model translation into MCP server layer ✓

### Phase 2: Agent Config Generation
**Goal**: The system generates complete, valid `.opencode/agents/<name>.md` config files that give a spawned agent its identity, team awareness, communication instructions, and MCP tool access
**Depends on**: Phase 1 (model/provider format needed in configs)
**Requirements**: SPAWN-02, SPAWN-03, SPAWN-04, SPAWN-05, RELY-02, MCP-01
**Success Criteria** (what must be TRUE):
  1. A generated agent config file exists at `.opencode/agents/<name>.md` with valid YAML frontmatter and markdown system prompt
  2. The config contains the agent's identity (agent_id, team_name, color) so the agent knows who it is
  3. The config contains explicit inbox polling instructions (tool name, frequency, protocol) so the agent checks for messages
  4. The config contains task management instructions (how to claim tasks, update status, report completion)
  5. The config includes the claude-teams MCP server in its tools section so the agent can access coordination primitives
  6. All tool permissions in the config are set to string "allow" (not boolean, not "ask") to prevent silent hangs
**Plans:** 2 plans

Plans:
- [x] 02-01-PLAN.md -- Config generation module with TDD: generate_agent_config, write_agent_config, ensure_opencode_json ✓
- [x] 02-02-PLAN.md -- Wire config generation into spawn flow and add cleanup on kill/shutdown ✓

### Phase 3: Spawn Execution
**Goal**: The system can launch an OpenCode agent in a tmux pane with a correct command, track its pane ID, and deliver an initial task prompt
**Depends on**: Phase 1 (binary path), Phase 2 (agent config must exist before spawn)
**Requirements**: SPAWN-06, SPAWN-07, SPAWN-08, SPAWN-09, RELY-01
**Success Criteria** (what must be TRUE):
  1. The system constructs a valid `opencode run --agent <name>` command with correct flags (model, format, agent)
  2. Executing the spawn creates a new tmux pane running the OpenCode process
  3. The tmux pane ID is captured and stored in the team config so the system can track the agent
  4. An initial prompt message is delivered to the teammate's inbox before the spawn command executes
  5. Spawn commands are wrapped with a timeout (e.g., 300s) so hung processes do not block indefinitely
**Plans:** 1 plan (research confirmed SPAWN-07/08/09 already satisfied by existing code; only SPAWN-06 and RELY-01 need new work)

Plans:
- [x] 03-01-PLAN.md -- Replace build_spawn_command with build_opencode_run_command, add timeout wrapping, rename claude_binary to opencode_binary ✓

### Phase 4: MCP Communication Validation
**Goal**: Spawned agents can actually use the MCP server to read their inbox, send messages to teammates, and operate on shared task state
**Depends on**: Phase 2 (MCP config in agent), Phase 3 (agents are running)
**Requirements**: MCP-02, MCP-03
**Success Criteria** (what must be TRUE):
  1. A spawned agent can call read_inbox, send_message, and task_* MCP tools and receive correct responses
  2. Two agents spawned in the same team can exchange messages through the MCP server (agent A sends, agent B receives)
  3. MCP server state is shared across all spawned agents via the filesystem backend at `~/.claude/` (not isolated per process)
**Plans:** 2 plans

Plans:
- [x] 04-01-PLAN.md -- Single-agent MCP tool access verification and config_gen send_message fix ✓
- [x] 04-02-PLAN.md -- Multi-agent message exchange, task sharing, and filesystem state verification ✓

### Phase 5: Agent Health & Monitoring
**Goal**: The system can detect when a spawned agent has died or hung, and forcefully terminate unresponsive agents
**Depends on**: Phase 3 (agents must be spawnable to monitor them)
**Requirements**: RELY-03, RELY-04
**Success Criteria** (what must be TRUE):
  1. The system can query a tmux pane to determine if the OpenCode process is still alive or has exited
  2. The system can detect a hung agent (process alive but unresponsive -- no output for configurable duration)
  3. The system can force-kill an unresponsive OpenCode instance and clean up its tmux pane
**Plans:** 2 plans

Plans:
- [x] 05-01-PLAN.md -- Core health detection functions: AgentHealthStatus model, check_pane_alive, capture_pane_content_hash, check_single_agent_health, health state persistence, and tests ✓
- [x] 05-02-PLAN.md -- MCP tool exposure: check_agent_health and check_all_agents_health tools with integration tests ✓

### Phase 6: Agent Templates
**Goal**: Users can spawn agents with pre-built role templates (researcher, implementer, reviewer, tester) that include role-appropriate system prompts and can be customized per-spawn
**Depends on**: Phase 2 (config generation is the foundation templates build on)
**Requirements**: TMPL-01, TMPL-02, TMPL-03
**Success Criteria** (what must be TRUE):
  1. The system ships with at least 4 pre-built templates: researcher, implementer, reviewer, tester
  2. Spawning an agent with a template produces a config file with role-specific system prompt instructions (e.g., reviewer focuses on code review, tester focuses on test execution)
  3. A user can customize a template at spawn time by providing additional prompt text that is injected into the generated config
**Plans**: TBD

Plans:
- [ ] 06-01: Template data model and built-in role definitions
- [ ] 06-02: Template selection and prompt customization at spawn time

### Phase 7: Desktop Spawning
**Goal**: The system can spawn OpenCode desktop app instances as an alternative to CLI tmux panes, on Windows, macOS, and Linux
**Depends on**: Phase 3 (shares spawn infrastructure, alternative execution path)
**Requirements**: DESK-01, DESK-02, DESK-03
**Success Criteria** (what must be TRUE):
  1. The system can launch the OpenCode desktop app with the correct agent configuration
  2. Desktop spawning works on Windows, macOS, and Linux (platform-appropriate launch commands)
  3. The system tracks the desktop process ID and can use it for lifecycle management (status check, termination)
**Plans**: TBD

Plans:
- [ ] 07-01: Desktop app discovery and cross-platform launch commands
- [ ] 07-02: Desktop process tracking and lifecycle management

### Phase 8: Legacy Cleanup
**Goal**: All Claude Code-specific code is removed, all tests pass against the new OpenCode spawning, and documentation reflects the current system
**Depends on**: Phases 1-5 (all new functionality must be in place before removing old code)
**Requirements**: CLEAN-01, CLEAN-02, CLEAN-03, CLEAN-04, CLEAN-05
**Success Criteria** (what must be TRUE):
  1. The `discover_claude_binary()` function no longer exists in the codebase
  2. The `build_spawn_command()` function no longer contains Claude Code CLI flags (`--agent-id`, `--team-name`, `--parent-session-id`)
  3. No references to Claude Code CLI flags remain anywhere in the codebase (grep for `--agent-id`, `--team-name`, `--parent-session-id` returns zero results)
  4. All existing tests pass with OpenCode spawning (no tests reference Claude-specific behavior)
  5. README and documentation describe OpenCode + Kimi K2.5 setup, not Claude Code setup
**Plans**: TBD

Plans:
- [ ] 08-01: Remove Claude Code discovery and command building functions
- [ ] 08-02: Remove Claude Code CLI flag references throughout codebase
- [ ] 08-03: Update all tests for OpenCode spawning
- [ ] 08-04: Update README and documentation

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Binary Discovery & Model Configuration | 2/2 | ✓ Complete | 2026-02-08 |
| 2. Agent Config Generation | 2/2 | ✓ Complete | 2026-02-08 |
| 3. Spawn Execution | 1/1 | ✓ Complete | 2026-02-08 |
| 4. MCP Communication Validation | 2/2 | ✓ Complete | 2026-02-08 |
| 5. Agent Health & Monitoring | 2/2 | ✓ Complete | 2026-02-08 |
| 6. Agent Templates | 0/2 | Not started | - |
| 7. Desktop Spawning | 0/2 | Not started | - |
| 8. Legacy Cleanup | 0/4 | Not started | - |

---
*Roadmap created: 2026-02-07*
*Depth: comprehensive (8 phases, 17 plans)*
