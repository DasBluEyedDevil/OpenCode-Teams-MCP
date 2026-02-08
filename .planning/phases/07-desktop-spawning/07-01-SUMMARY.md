---
phase: 07-desktop-spawning
plan: 01
subsystem: spawner
tags: [subprocess, process-management, desktop-app, cross-platform, os.kill]

requires:
  - phase: 05-agent-health-monitoring
    provides: "spawner.py with health check infrastructure"
provides:
  - "discover_desktop_binary() with 3-tier discovery (env var, known paths, PATH)"
  - "launch_desktop_app() with platform-specific detach flags returning PID"
  - "check_process_alive() cross-platform liveness check via os.kill(pid, 0)"
  - "kill_desktop_process() with SIGTERM and dead-process error swallowing"
  - "TeammateMember.process_id field (default 0, alias processId)"
affects: [07-desktop-spawning plan 02, spawn flow, MCP tools]

tech-stack:
  added: []
  patterns: ["os.kill(pid, 0) for cross-platform process liveness", "subprocess.Popen with CREATE_NEW_PROCESS_GROUP on Windows, start_new_session on POSIX"]

key-files:
  created: []
  modified:
    - "src/claude_teams/spawner.py"
    - "src/claude_teams/models.py"
    - "tests/test_spawner.py"

key-decisions:
  - "Desktop binary discovery mirrors discover_opencode_binary() pattern but adds env var and known-paths tiers"
  - "launch_desktop_app uses subprocess.Popen directly (not platform launchers) to get real PID"
  - "process_id field defaults to 0 (not None) to avoid optional handling complexity"

patterns-established:
  - "Desktop binary constants: DESKTOP_PATHS per-platform dict, DESKTOP_BINARY_NAMES per-platform dict, DESKTOP_BINARY_ENV_VAR string"
  - "Process lifecycle: discover -> launch -> check_alive -> kill pattern for desktop backend"

duration: 4min
completed: 2026-02-08
---

# Phase 7 Plan 1: Desktop Process Lifecycle Summary

**Desktop app discovery, process launch with PID tracking, liveness checking via os.kill(pid, 0), and SIGTERM termination with cross-platform detach flags**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-08T17:34:53Z
- **Completed:** 2026-02-08T17:38:31Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added process_id field to TeammateMember model with default 0 and JSON alias "processId"
- Implemented 4 desktop lifecycle functions: discover_desktop_binary, launch_desktop_app, check_process_alive, kill_desktop_process
- Added 14 comprehensive tests covering all desktop lifecycle functions with full branch coverage
- Platform-specific handling: CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS on Windows, start_new_session on POSIX

## Task Commits

Each task was committed atomically:

1. **Task 1: Add process_id field and desktop lifecycle functions** - `b6fe9aa` (feat)
2. **Task 2: Add comprehensive tests for desktop lifecycle functions** - `c21f3ed` (test)

## Files Created/Modified
- `src/claude_teams/models.py` - Added process_id field to TeammateMember
- `src/claude_teams/spawner.py` - Added desktop constants and 4 lifecycle functions (discover_desktop_binary, launch_desktop_app, check_process_alive, kill_desktop_process)
- `tests/test_spawner.py` - Added 14 tests in 3 classes (TestDesktopDiscovery, TestDesktopLaunch, TestProcessLifecycle)

## Decisions Made
- Desktop binary discovery mirrors the existing discover_opencode_binary() pattern but adds env var override and known installation paths tiers before PATH fallback
- launch_desktop_app uses subprocess.Popen directly to get the real PID, avoiding platform launchers (open, start) that don't return the actual app PID
- process_id field defaults to 0 (not None) so existing code doesn't need to handle Optional types

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed monkeypatch.attr to monkeypatch.setattr for sys.platform**
- **Found during:** Task 2 (test writing)
- **Issue:** Plan specified `monkeypatch.attr()` which does not exist in pytest; the correct method is `monkeypatch.setattr(sys, "platform", value)` with the module object
- **Fix:** Used `monkeypatch.setattr(sys, "platform", "linux")` and imported `sys` in test file
- **Files modified:** tests/test_spawner.py
- **Verification:** All 14 tests pass
- **Committed in:** c21f3ed (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug in plan specification)
**Impact on plan:** Trivial fix to use correct pytest API. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 4 desktop lifecycle primitives ready for Plan 02 to wire into spawn flow and MCP tools
- TeammateMember.process_id ready to store desktop process PIDs
- Existing tmux backend unaffected (process_id defaults to 0, backend_type defaults to "tmux")

---
*Phase: 07-desktop-spawning*
*Completed: 2026-02-08*
