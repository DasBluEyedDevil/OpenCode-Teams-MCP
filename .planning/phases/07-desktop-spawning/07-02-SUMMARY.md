---
phase: 07-desktop-spawning
plan: 02
subsystem: spawner
tags: [subprocess, process-management, desktop-app, mcp-tools, backend-branching]

requires:
  - phase: 07-desktop-spawning
    plan: 01
    provides: "Desktop lifecycle primitives (discover, launch, check_alive, kill)"
  - phase: 06-agent-templates
    provides: "Template-aware spawn_teammate_tool with template and custom_instructions params"
provides:
  - "spawn_teammate() with backend_type='desktop' path using launch_desktop_app and PID tracking"
  - "spawn_teammate_tool MCP tool with backend='desktop' parameter and desktop binary discovery"
  - "force_kill_teammate branching: desktop -> kill_desktop_process, tmux -> kill_tmux_pane"
  - "check_single_agent_health branching: desktop -> alive/dead only, tmux -> alive/dead/hung/unknown"
affects: [08-polish-reliability]

tech-stack:
  added: []
  patterns: ["backend_type branching pattern for tmux/desktop dual-backend lifecycle management"]

key-files:
  created: []
  modified:
    - "src/claude_teams/spawner.py"
    - "src/claude_teams/server.py"
    - "tests/test_spawner.py"
    - "tests/test_server.py"

key-decisions:
  - "Desktop binary discovered at spawn time in server.py (not cached in lifespan) since it may not be needed for tmux spawns"
  - "Desktop health check returns alive/dead only -- no hung detection since there is no content hash equivalent for desktop apps"
  - "force_kill_teammate looks up full member object (not just pane_id) to branch on backend_type"

patterns-established:
  - "Backend branching: check member.backend_type == 'desktop' at top of function, early return, then fall through to tmux path"
  - "Spawn tool discovers binary just-in-time: desktop_binary resolved only when backend='desktop'"

duration: 5min
completed: 2026-02-08
---

# Phase 7 Plan 2: Desktop Spawn Wiring Summary

**Desktop backend wired into spawn_teammate, force_kill, and health checks with MCP tool backend parameter and just-in-time binary discovery**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-08T17:41:43Z
- **Completed:** 2026-02-08T17:46:50Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- spawn_teammate() accepts backend_type="desktop" with desktop_binary param, calls launch_desktop_app and stores PID in process_id
- spawn_teammate_tool MCP tool accepts backend="desktop" param, discovers binary via discover_desktop_binary()
- force_kill_teammate branches on backend_type to use kill_desktop_process or kill_tmux_pane
- check_single_agent_health branches on backend_type: desktop returns alive/dead only (no hung detection)
- Tmux path completely unchanged -- all existing tests pass without modification
- 12 new tests across 4 test classes covering all desktop backend paths

## Task Commits

Each task was committed atomically:

1. **Task 1: Add desktop backend path to spawn_teammate and branch health checks** - `33a446c` (feat)
2. **Task 2: Wire backend param into MCP tools and branch force_kill by backend_type** - `a6550a6` (feat)

## Files Created/Modified
- `src/claude_teams/spawner.py` - Added backend_type/desktop_binary params to spawn_teammate, desktop branch in check_single_agent_health
- `src/claude_teams/server.py` - Added backend param to spawn_teammate_tool, desktop binary discovery, desktop-aware force_kill_teammate
- `tests/test_spawner.py` - Added TestSpawnDesktopBackend (4 tests) and TestDesktopHealthCheck (3 tests)
- `tests/test_server.py` - Added TestSpawnDesktopBackendTool (3 tests) and TestForceKillDesktopBackend (2 tests)

## Decisions Made
- Desktop binary discovered at spawn time in server.py (not cached in lifespan) since most spawns may use tmux backend and desktop binary may not be installed
- Desktop health returns alive/dead only -- no hung detection possible since desktop apps don't have tmux pane content hashing
- force_kill_teammate refactored to look up full member object (not just pane_id) to support backend_type branching

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing test_force_kill_cleans_up_agent_config missing kill_tmux_pane mock**
- **Found during:** Task 2 (server test suite validation)
- **Issue:** TestConfigCleanup::test_force_kill_cleans_up_agent_config did not mock kill_tmux_pane, causing FileNotFoundError on Windows where tmux is not installed. This test was already failing before our changes.
- **Fix:** Added `unittest.mock.patch("claude_teams.server.kill_tmux_pane")` to the test's context manager stack
- **Files modified:** tests/test_server.py
- **Verification:** All 61 server tests pass
- **Committed in:** a6550a6 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 pre-existing bug in test)
**Impact on plan:** Trivial mock addition to fix Windows compatibility. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full desktop spawn lifecycle complete: discover binary -> spawn with PID tracking -> health check (alive/dead) -> force kill
- Phase 7 complete -- all desktop spawning functionality wired in
- Phase 8 (polish/reliability) can now build on both tmux and desktop backends

---
*Phase: 07-desktop-spawning*
*Completed: 2026-02-08*
