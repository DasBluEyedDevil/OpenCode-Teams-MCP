---
phase: 05-agent-health-monitoring
plan: 01
subsystem: agent-lifecycle
tags: [tmux, health-check, sha256, pydantic, subprocess]

# Dependency graph
requires:
  - phase: 03-spawn-execution
    provides: tmux pane spawning with pane_id tracking
  - phase: 01-opencode-swap
    provides: TeammateMember model with tmux_pane_id field
provides:
  - AgentHealthStatus Pydantic model (alive/dead/hung/unknown)
  - check_pane_alive() for tmux pane liveness detection
  - capture_pane_content_hash() for SHA-256 content fingerprinting
  - check_single_agent_health() combining liveness + hung detection + grace period
  - load_health_state/save_health_state for JSON persistence
affects: [05-02-PLAN, phase-06, phase-07]

# Tech tracking
tech-stack:
  added: [hashlib, msvcrt (Windows compat)]
  patterns: [tmux display-message for pane status, content hashing for hang detection, grace period for new agents]

key-files:
  created: []
  modified:
    - src/claude_teams/models.py
    - src/claude_teams/spawner.py
    - src/claude_teams/messaging.py
    - tests/test_spawner.py

key-decisions:
  - "Cross-platform fcntl: messaging.py uses msvcrt on Windows, fcntl on POSIX -- resolves known blocker"
  - "No -S- flag on capture-pane: visible content only to avoid known tmux scroll-back hangs"
  - "Grace period comparison uses joined_at millis converted to seconds for consistency with time.time()"

patterns-established:
  - "Health state persistence: JSON file at ~/.claude/teams/<name>/health.json alongside config.json"
  - "Subprocess timeout of 5s for all tmux health queries to prevent blocking"
  - "Grace period pattern: newly spawned agents exempt from hung detection for configurable duration"

# Metrics
duration: 5min
completed: 2026-02-08
---

# Phase 5 Plan 1: Agent Health Detection Summary

**Tmux pane liveness check, SHA-256 content hashing for hung detection, and combined health status with grace period support**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-08T16:11:13Z
- **Completed:** 2026-02-08T16:16:11Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- AgentHealthStatus model with status literals alive/dead/hung/unknown and camelCase alias support
- check_pane_alive() queries tmux pane_dead flag with full error handling (timeout, missing tmux, empty pane_id)
- capture_pane_content_hash() returns SHA-256 digest of visible pane content (no -S- flag)
- check_single_agent_health() orchestrates liveness + hung detection with configurable grace period and timeout
- Health state persistence via JSON round-trip for tracking content change timestamps between polls
- 21 new tests covering all edge cases (76 total tests pass)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add AgentHealthStatus model and core detection functions** - `d04fada` (feat)
2. **Task 2: Add comprehensive tests for all health detection functions** - `c11b26d` (test)

## Files Created/Modified
- `src/claude_teams/models.py` - Added AgentHealthStatus Pydantic model
- `src/claude_teams/spawner.py` - Added check_pane_alive, capture_pane_content_hash, check_single_agent_health, load_health_state, save_health_state + constants
- `src/claude_teams/messaging.py` - Fixed cross-platform file locking (fcntl on POSIX, msvcrt on Windows)
- `tests/test_spawner.py` - Added 21 tests across 4 new test classes

## Decisions Made
- Cross-platform fcntl fix: messaging.py now uses msvcrt.locking on Windows and fcntl.flock on POSIX, resolving the known Windows/WSL blocker
- No -S- flag on capture-pane to avoid known tmux scroll-back buffer hangs
- Grace period math converts joined_at millis to seconds before comparing with time.time()

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed fcntl import failure on Windows**
- **Found during:** Task 1 (import verification)
- **Issue:** messaging.py imports fcntl at module level, which is POSIX-only. On Windows (win32), this causes ModuleNotFoundError preventing any code from loading.
- **Fix:** Made fcntl import conditional: uses msvcrt.locking on Windows, fcntl.flock on POSIX. Both provide exclusive file locking semantics.
- **Files modified:** src/claude_teams/messaging.py
- **Verification:** All imports succeed on Windows; all 76 tests pass
- **Committed in:** d04fada (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix to unblock all code execution on Windows. No scope creep.

## Issues Encountered
- uv venv was corrupted (broken lib64 symlink) -- removed and re-synced with `uv sync`

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Health detection functions ready for Plan 05-02 (MCP tool wrappers)
- check_single_agent_health can be called from MCP tools to expose health status to agents
- Health state persistence enables polling-based monitoring loops

---
*Phase: 05-agent-health-monitoring*
*Completed: 2026-02-08*
