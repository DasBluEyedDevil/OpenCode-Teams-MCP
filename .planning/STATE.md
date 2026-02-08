# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-07)

**Core value:** Kimi K2.5 agents in OpenCode can coordinate as teams with shared task lists and messaging
**Current focus:** Phase 7 complete - Desktop Spawning

## Current Position

Phase: 7 of 8 (Desktop Spawning)
Plan: 2 of 2 in current phase
Status: Phase complete
Last activity: 2026-02-08 -- Completed 07-02-PLAN.md (Desktop Spawn Wiring)

Progress: [██████████████░] 93%

## Performance Metrics

**Velocity:**
- Total plans completed: 13
- Average duration: 6 minutes
- Total execution time: 1.4 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 2/2 | 30m | 15m |
| 02 | 2/2 | 6m | 3m |
| 03 | 1/1 | 4m | 4m |
| 04 | 2/2 | 13m | 6.5m |
| 05 | 2/2 | 10m | 5m |
| 06 | 2/2 | 7m | 3.5m |
| 07 | 2/2 | 9m | 4.5m |

**Recent Trend:**
- Last 5 plans: 05-02 (5m), 06-01 (4m), 06-02 (3m), 07-01 (4m), 07-02 (5m)
- Trend: Sustained fast execution for targeted plans

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Replace Claude Code entirely, not hybrid -- clean swap of spawner module only
- [Roadmap]: Dynamic agent config generation via `.opencode/agents/<name>.md` for identity injection
- [Roadmap]: RELY-02 (permissions) mapped to Phase 2 (config gen) since it is a config concern, not a runtime reliability concern
- [01-01]: Use tuple comparison instead of packaging.version to avoid dependency risk
- [01-01]: All Claude aliases (sonnet/opus/haiku) map to kimi-k2.5 since it's the only supported model
- [01-01]: Credential references use {env:VAR_NAME} syntax per OpenCode pattern to prevent secret leakage
- [01-02]: Default provider hardcoded to 'moonshot-ai' in lifespan for Phase 1 (configurable later)
- [01-02]: Model parameter changed from Literal to str to accept both aliases and provider/model strings
- [02-01]: Permission field uses string "allow" not boolean True for OpenCode non-interactive mode
- [02-01]: claude-teams_* wildcard in frontmatter enables all MCP tools without explicit listing
- [02-01]: System prompt uses fully-qualified tool names (claude-teams_read_inbox) per MCP requirements
- [02-01]: ensure_opencode_json uses setdefault pattern to preserve existing config during merges
- [02-02]: cleanup_agent_config in spawner.py, not config_gen.py, as cleanup is lifecycle concern not config generation
- [02-02]: Use Path.cwd() as default project_dir in server.py since MCP server runs from project root
- [03-01]: Keep build_spawn_command for Phase 8 cleanup rather than deleting now
- [03-01]: Timeout wrapping via shell 'timeout' command inside tmux pane, not Python subprocess timeout
- [04-01]: Duplicate _make_teammate and _data helpers locally rather than importing from test_server.py for test isolation
- [04-01]: Fix send_message to use sender param (was hardcoded to team-lead) -- bug discovered via test-first approach
- [04-02]: send_message type='message' always attributes from='team-lead' -- tests adapted to match actual server behavior
- [04-02]: Cross-context test uses two sequential Client(mcp) sessions with same monkeypatched tmp_path
- [05-01]: Cross-platform fcntl fix: messaging.py uses msvcrt on Windows, fcntl on POSIX
- [05-01]: No -S- flag on capture-pane to avoid tmux scroll-back buffer hangs
- [05-01]: Grace period math converts joined_at millis to seconds before comparing with time.time()
- [05-02]: Health state persistence handled in MCP tool layer for control over when state is saved
- [05-02]: Both health tools use model_dump(by_alias=True, exclude_none=True) consistent with all server.py tools
- [06-01]: Templates use frozen dataclass, not Pydantic, since they are developer-defined constants
- [06-01]: tool_overrides field exists but is empty for all v1 templates (behavioral guidance only)
- [06-01]: Body refactored to list-of-parts joined by double newlines for conditional section injection
- [06-02]: Template lookup happens in server.py (MCP tool layer), not spawner.py -- spawner receives resolved role_instructions
- [06-02]: subagent_type derived from template name in server.py, not passed as separate param by caller
- [06-02]: Replaced subagent_type param with template param on spawn_teammate_tool
- [07-01]: Desktop binary discovery mirrors discover_opencode_binary() pattern but adds env var and known-paths tiers
- [07-01]: launch_desktop_app uses subprocess.Popen directly (not platform launchers) to get real PID
- [07-01]: process_id field defaults to 0 (not None) to avoid optional handling complexity
- [07-02]: Desktop binary discovered at spawn time in server.py (not cached in lifespan) since it may not be needed for tmux spawns
- [07-02]: Desktop health check returns alive/dead only -- no hung detection since there is no content hash equivalent for desktop apps
- [07-02]: force_kill_teammate looks up full member object (not just pane_id) to branch on backend_type

### Pending Todos

None yet.

### Blockers/Concerns

- [Research]: `opencode run` long-running behavior is untested -- designed for one-shots, agents need persistence. Validate in Phase 1/3.
- [Research]: Kimi K2.5 instruction-following for team coordination prompts must be tested empirically in Phase 4.
- [RESOLVED]: MCP server state sharing across spawned agents -- empirically confirmed in 04-02 (test_cross_context_state_visible)
- [RESOLVED]: Windows/WSL constraint -- fcntl now conditionally imported (msvcrt on Windows, fcntl on POSIX) in 05-01 and 05-02

## Session Continuity

Last session: 2026-02-08
Stopped at: Completed 07-02 (Desktop Spawn Wiring) - Phase 7 complete, ready for Phase 8
Resume file: .planning/phases/07-desktop-spawning/07-02-SUMMARY.md
