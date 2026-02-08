# Project Research Summary

**Project:** OpenCode Teams MCP (replacing Claude Code spawning with OpenCode + Kimi K2.5)
**Domain:** Multi-agent team coordination via MCP server with programmatic CLI spawning
**Researched:** 2026-02-07
**Confidence:** MEDIUM

## Executive Summary

This project replaces the Claude Code CLI spawning layer in an existing multi-agent team coordination MCP server with OpenCode CLI + Kimi K2.5. The existing codebase is well-structured: an MCP server (`server.py`) exposes team coordination tools (inbox messaging, task DAG, shutdown protocol) that spawned AI agents use to collaborate. The spawner module is the **only** component that needs replacement -- roughly 25% of the codebase. Everything else (team lifecycle, task management, messaging, file persistence) is client-agnostic and stays unchanged. The recommended approach is `opencode run` in tmux panes, which directly mirrors the existing `claude` CLI spawning pattern, minimizing architectural disruption.

The critical architectural difference is that Claude Code has native team-awareness flags (`--agent-id`, `--team-name`), while OpenCode has none. Team identity must be injected via dynamically generated agent config files (`.opencode/agents/<name>.md`) containing system prompts with coordination instructions, plus MCP server configuration so agents can access team tools. This "context injection via files" pattern replaces "context injection via CLI flags" and is the single most important design decision. A new `config_gen.py` module handles this.

The primary risks are: (1) `opencode run` hanging indefinitely on API errors or permission prompts -- both confirmed OpenCode bugs with no upstream fix, requiring timeout wrappers and permissive permissions as mitigations; (2) MCP server state isolation -- each spawned agent may start its own MCP server subprocess with separate state, breaking inter-agent messaging unless all instances share the filesystem backend at `~/.claude/`; (3) Kimi K2.5 instruction-following reliability -- since team coordination depends entirely on the LLM following system prompt instructions about inbox polling and task updates, this must be validated empirically with Kimi K2.5 specifically, not assumed from Claude behavior.

## Key Findings

### Recommended Stack

The stack is a clean swap of the spawning binary from `claude` to `opencode`, preserving the existing Python/FastMCP/tmux infrastructure. No new Python dependencies are needed. The key change is command construction and agent configuration.

**Core technologies:**
- **OpenCode CLI v1.1.49+**: Replaces `claude` binary; `opencode run` command for non-interactive spawning with `--agent`, `--model`, `--format json` flags
- **Kimi K2.5 via Moonshot AI**: LLM for agent reasoning; supported via `moonshot-ai/kimi-k2.5` provider string; OpenRouter available as fallback
- **Python 3.12+ / FastMCP 3.0.0b1 / tmux**: Existing stack, unchanged -- MCP server framework, process isolation, data models
- **Dynamic agent markdown configs**: `.opencode/agents/<name>.md` files replace Claude Code's `--agent-id`/`--team-name` CLI flags for identity injection

**Critical version requirement:** OpenCode v1.1.49+ required for Kimi K2.5 support (merged in PR #10835).

**What NOT to use:** `opencode serve` + SDK (session hang bug #6573, pre-release SDK); OpenCode's native Task/subagent system (single-process, wrong coordination model); `dmux`/`oh-my-opencode` plugins (overlapping responsibility with our orchestrator).

### Expected Features

**Must have (table stakes):**
- T1: OpenCode binary discovery (swap `shutil.which("claude")` to `which("opencode")`)
- T2: Non-interactive spawn via `opencode run` with correct flag construction
- T3: Dynamic agent config generation (`.opencode/agents/<name>.md` with YAML frontmatter + system prompt)
- T4: System prompt injection for team awareness (agent identity, MCP tool usage, coordination protocol)
- T5: MCP server auto-configuration for teammates (project-level `opencode.json`)
- T6: Tmux-based process spawning (existing pattern, different binary)
- T7: Model specification translation (`provider/model` format replaces `sonnet`/`opus`/`haiku`)
- T9: Remove all Claude Code-specific code paths (flags, env vars, model names)
- T8/T12: Lifecycle management and shutdown protocol verification with OpenCode

**Should have (differentiators):**
- D5: Agent health monitoring (detect dead/hung agents via tmux + heartbeat)
- D7: Context-efficient inbox (message limits, summary-only mode to prevent context bloat)
- D4: File reservation/lock tracking (prevent edit conflicts between agents)
- D8: Agent specialization templates (pre-defined roles: coder, reviewer, researcher)

**Defer (v2+):**
- D9: Git worktree isolation per agent (high complexity, low ROI)
- D11: Desktop app spawning via `opencode serve` (niche, adds port management)
- A9: Web UI / dashboard (scope creep, tmux provides monitoring)

**Anti-features (never build):**
- A1: Recursive agent spawning (causes exponential cascades -- oh-my-opencode bug #535)
- A3: Shared context windows between agents (bloats context, creates circular dependencies)
- A10: Hybrid Claude Code + OpenCode mode (clean replacement, not dual paths)

### Architecture Approach

The architecture preserves the existing three-layer design (MCP server -> domain logic -> filesystem persistence) with surgical replacement of only the spawner module. A new `config_gen.py` module is introduced to handle dynamic agent config file generation. The spawning flow becomes: generate agent config -> write `.opencode/agents/<name>.md` -> build `opencode run` command -> execute in tmux pane. Three channels deliver team context to spawned agents: (1) agent config file for identity, (2) MCP server tools for coordination primitives, (3) initial prompt for task assignment.

**Major components:**
1. **server.py** -- MCP tool definitions (MINOR CHANGES: model enum, binary discovery)
2. **teams.py / tasks.py / messaging.py** -- Team lifecycle, task DAG, inbox system (UNCHANGED)
3. **spawner.py** -- Binary discovery, command building, tmux spawning (MAJOR REWRITE)
4. **config_gen.py** (NEW) -- Generate/cleanup `.opencode/agents/<name>.md` files with team context
5. **models.py** -- Pydantic data models (MINOR CHANGES: model field values)

### Critical Pitfalls

1. **Permission prompts silently hang headless agents (P2)** -- Set ALL permissions to `"allow"` (string, never boolean) in generated agent configs. The `"ask"` default blocks `opencode run` indefinitely with no error output. This is the most common failure mode.

2. **`opencode run` hangs on API errors instead of exiting (P1)** -- Wrap every spawn command with `timeout 300 opencode run ...`. OpenCode has no proper `process.exit()` on unrecoverable errors (confirmed bugs #8203, #3213). No upstream fix exists.

3. **MCP server state isolation breaks inter-agent messaging (P9)** -- If each spawned agent launches its own MCP server subprocess via `command` config, each gets independent state. Solution: either run a single MCP server in `remote` mode with all agents connecting via URL, or ensure all subprocess instances share the same `~/.claude/` filesystem backend.

4. **Agent config schema validation crashes OpenCode silently (P3)** -- Boolean `true`/`false` for permissions causes `ConfigInvalidError` with no useful output. Use string `"allow"`/`"deny"` exclusively. Validate generated configs before spawning.

5. **No native team awareness -- LLM must follow instructions (P4)** -- Team coordination is entirely prompt-driven. Make system prompts explicit with exact tool names, parameter formats, and step-by-step protocols. Test with Kimi K2.5 specifically; instruction-following varies by model.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Spawner Core Replacement

**Rationale:** This is the foundation -- nothing else works until agents can be spawned via OpenCode. The dependency chain is strict: binary discovery -> model translation -> command construction -> tmux spawning. Agent config generation is a prerequisite for spawning because OpenCode needs the agent file to exist before `opencode run --agent <name>` is invoked.

**Delivers:** Working `opencode run` spawning in tmux panes with dynamically generated agent configs, replacing all Claude Code code paths.

**Addresses:** T1 (binary discovery), T7 (model translation), T9 (remove Claude paths), T2 (spawn command), T6 (tmux spawning), T3 (agent config generation), T5 (MCP config)

**Avoids:** P2 (permission hangs -- all permissions set to "allow"), P3 (schema validation -- validated templates with string permissions), P1 (process hangs -- timeout wrappers), P13 (naming collisions -- namespaced agent names)

### Phase 2: Team Context and Communication

**Rationale:** Once spawning works, agents need to actually know who they are and how to coordinate. System prompt design is the bridge between "agent runs" and "agent participates in team." This phase also validates that MCP server state is properly shared across agents -- the inter-agent messaging architecture must work or the entire system is broken.

**Delivers:** Full team-aware agents that read inboxes, send messages, update tasks, and follow shutdown protocol.

**Addresses:** T4 (system prompt injection), T8 (lifecycle management verification), T12 (shutdown protocol), P9 (MCP state isolation -- validate shared filesystem or switch to remote mode)

**Avoids:** P4 (no native team awareness -- explicit, tested prompts), P11 (subagent confusion -- disable native task tool, explicit instructions to use MCP tools only)

### Phase 3: Reliability and Hardening

**Rationale:** After basic spawning and communication work, harden the system against real-world failures: hung processes, dead agents, context bloat, and model configuration errors. These are the issues that surface under sustained multi-agent workloads.

**Delivers:** Health monitoring, liveness checks, context-efficient inbox, robust model configuration validation.

**Addresses:** D5 (health monitoring), D7 (context-efficient inbox), P1 (process hang detection via heartbeat), P5 (model configuration validation), P12 (rate limiting awareness)

**Avoids:** P15 (pane ID tracking -- track both pane ID and PID), P10 (non-interactive mode gaps -- pre-configure everything)

### Phase 4: Productivity Features

**Rationale:** With a stable, reliable system, add features that make multi-agent teams more productive. These are differentiators vs. competing tools (swarm-tools, oh-my-opencode) but are not required for basic operation.

**Delivers:** File locking, progress checkpoints, agent templates, filtered broadcasts.

**Addresses:** D4 (file reservation), D6 (progress checkpoints), D8 (agent templates), D10 (broadcast filtering), A1 enforcement (restrict `spawn_teammate` to lead at MCP tool level)

**Avoids:** Over-engineering (keep features simple, avoid scope creep into A9 dashboard or A6 semantic memory)

### Phase Ordering Rationale

- **Phase 1 before Phase 2** because agents must be spawnable before team context matters. Config generation is in Phase 1 (not Phase 2) because it is a prerequisite for the spawn command itself.
- **Phase 2 before Phase 3** because you cannot harden what does not yet work. Validating MCP state sharing is in Phase 2 because messaging failure is an architectural blocker, not a reliability concern.
- **Phase 3 before Phase 4** because reliability under failure conditions must be solved before adding features. A system that spawns agents but cannot detect when they die is worse than one with fewer features.
- The feature dependency graph confirms this ordering: T1 -> T7 -> T9 -> T2 -> T6 (Phase 1), then T3 -> T4 -> T5 (Phase 1-2 bridge), then D5 -> T8 (Phase 3), then D4/D6/D8/D10 (Phase 4).

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** Needs empirical validation of `opencode run` behavior for long-running sessions. The wrapper-script-loop pattern for persistent agents is untested. Also needs validation of multiple concurrent `opencode run` processes in the same project directory.
- **Phase 2:** Needs Kimi K2.5-specific testing of system prompt instruction-following. Also needs empirical validation of MCP server state sharing when agents use `local` type MCP config (each may spawn a separate server process).
- **Phase 3:** Needs testing of rate limiting behavior under multi-agent load with shared API key. What happens when N agents hit rate limits simultaneously?

Phases with standard patterns (skip research-phase):
- **Phase 4:** File locking, progress reporting, and message filtering are well-understood patterns. No novel engineering required. The existing codebase already has the messaging and task infrastructure; these are incremental extensions.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | OpenCode CLI docs are comprehensive and verified. Kimi K2.5 provider support confirmed via merged PR. Uncertainty: `opencode run` behavior for long-running agent sessions (designed for one-shots). |
| Features | MEDIUM | Feature landscape is clear from competitive analysis of swarm-tools, oh-my-opencode, etc. Uncertainty: which differentiators actually matter in practice vs. sound good in theory. |
| Architecture | MEDIUM-HIGH | Existing codebase is well-structured; replacement surface area is small (spawner only). Agent config generation pattern is documented in OpenCode docs. Uncertainty: MCP server state isolation under multi-agent load. |
| Pitfalls | HIGH | 15 pitfalls identified with specific GitHub issue numbers and confirmed reproduction steps. The top 5 are well-documented bugs in OpenCode with known mitigations. |

**Overall confidence:** MEDIUM

### Gaps to Address

- **Long-running agent behavior:** `opencode run` is designed for one-shot prompts (run, complete, exit). The existing Claude Code agents stay alive and poll inboxes. A wrapper script loop pattern is theorized but untested. This is the single biggest unknown. Validate in Phase 1 prototyping.

- **Kimi K2.5 instruction-following for team coordination:** All team awareness depends on the LLM correctly interpreting system prompt instructions. Different models have different instruction-following characteristics. Must be tested with Kimi K2.5 specifically during Phase 2, not assumed from Claude behavior.

- **MCP server state sharing:** When multiple `opencode run` instances each start their own `claude-teams` MCP server subprocess via `local` config, do they share state? They should if all use the same `~/.claude/` base directory, but this needs empirical confirmation. If they do not share state, switch to `remote` mode with a single server instance.

- **Windows / WSL constraints:** The codebase uses `fcntl` (Unix-only) and `tmux` (requires WSL on Windows). The project is running on `win32`. This is a pre-existing limitation, not introduced by the migration, but needs explicit documentation. Not a Phase 1 blocker if running in WSL.

- **Config merge precedence:** OpenCode merges configs from 5+ sources with unintuitive precedence. Generated project-level agent configs may be overridden by user's global configs. Mitigate by using unique agent names and/or `OPENCODE_CONFIG` env var for self-contained configs. Needs empirical testing.

## Sources

### Primary (HIGH confidence)
- [OpenCode CLI Reference](https://opencode.ai/docs/cli/) -- Command flags, `run` subcommand behavior, non-interactive mode
- [OpenCode Agent Configuration](https://opencode.ai/docs/agents/) -- Agent markdown format, frontmatter fields, modes
- [OpenCode Config](https://opencode.ai/docs/config/) -- opencode.json format, provider configuration, merge behavior
- [OpenCode MCP Servers](https://opencode.ai/docs/mcp-servers/) -- MCP server integration format, local vs remote
- [OpenCode Permissions](https://opencode.ai/docs/permissions/) -- Permission model, auto-approve behavior

### Secondary (MEDIUM confidence)
- [Kimi K2.5 PR #10835](https://github.com/anomalyco/opencode/pull/10835) -- Moonshot provider registration
- [swarm-tools](https://github.com/joelhooks/swarm-tools) -- Reference multi-agent architecture, file reservation pattern
- [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode) -- Recursive spawning bug #535, background agent management
- [OpenCode + Kimi K2.5 Config Gist](https://gist.github.com/OmerFarukOruc/26262e9c883b3c2310c507fdf12142f4) -- Provider config format
- [Cognition.ai: Don't Build Multi-Agents](https://cognition.ai/blog/dont-build-multi-agents) -- Architectural guidance on agent coordination

### Tertiary (LOW confidence, needs validation)
- Long-running `opencode run` behavior for persistent agents -- theorized wrapper script, untested
- Multiple concurrent `opencode run` processes in same directory -- should work, unconfirmed
- Kimi K2.5 instruction-following for team coordination prompts -- model-dependent, must test empirically

### Bug Reports (HIGH confidence, confirmed)
- [opencode run hangs on API errors (#8203)](https://github.com/anomalyco/opencode/issues/8203)
- [Permission hang in ask mode (#3332)](https://github.com/anomalyco/opencode/issues/3332)
- [Boolean permissions crash OpenCode (#7810)](https://github.com/anomalyco/opencode/issues/7810)
- [Subagent sessions are enclosed (#11012)](https://github.com/anomalyco/opencode/issues/11012)
- [Config merge precedence bugs (#4217)](https://github.com/anomalyco/opencode/issues/4217)
- [Non-interactive mode limitations (#10411)](https://github.com/anomalyco/opencode/issues/10411)

---
*Research completed: 2026-02-07*
*Ready for roadmap: yes*
