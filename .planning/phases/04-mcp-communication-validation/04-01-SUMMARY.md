---
phase: 04-mcp-communication-validation
plan: 01
subsystem: testing
tags: [fastmcp, integration-tests, mcp-tools, agent-messaging]

requires:
  - phase: 02-config-generation
    provides: "config_gen.py system prompt with MCP tool instructions"
  - phase: 01-core-models
    provides: "MCP server with send_message, read_inbox, task_* tools"
provides:
  - "Integration tests proving all agent-callable MCP tools work correctly"
  - "Bug fix: send_message type=message now respects sender parameter"
  - "Bug fix: config_gen.py system prompt uses correct MCP tool parameter names"
affects: [04-02, 05-spawn-lifecycle, 08-integration]

tech-stack:
  added: []
  patterns: ["fastmcp.Client integration testing for agent-perspective tool validation"]

key-files:
  created:
    - "tests/test_mcp_agent_tools.py"
  modified:
    - "src/claude_teams/server.py"
    - "src/claude_teams/config_gen.py"

key-decisions:
  - "04-01: Duplicate _make_teammate and _data helpers locally rather than importing from test_server.py for test isolation"
  - "04-01: Fix send_message to use sender param (was hardcoded to team-lead) -- bug discovered via test-first approach"

patterns-established:
  - "Agent-perspective testing: tests validate MCP tools as an agent would call them (with sender=<name>)"

duration: 6min
completed: 2026-02-08
---

# Phase 4 Plan 1: Single-Agent MCP Tool Access Validation Summary

**8 integration tests proving agents can read_inbox, send_message (with sender attribution), and manage tasks via MCP tools, plus two bug fixes for sender handling**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-08T04:39:33Z
- **Completed:** 2026-02-08T04:45:55Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- 8 integration tests covering every agent-callable MCP tool (read_inbox, send_message, task_create, task_update, task_list, task_get)
- Fixed send_message handler to use `sender` parameter instead of hardcoded "team-lead" for type="message"
- Fixed config_gen.py system prompt to use correct MCP tool parameter names (type, recipient, content, summary, sender) instead of incorrect from_agent/to_agent/message

## Task Commits

Each task was committed atomically:

1. **Task 1: Single-agent MCP tool access integration tests** - `cfd39cc` (feat + fix: tests + sender bug fix in server.py)
2. **Task 2: Fix send_message sender in config_gen system prompt** - `5e1a1a2` (fix: correct param names)

## Files Created/Modified
- `tests/test_mcp_agent_tools.py` - 8 integration tests for agent-perspective MCP tool access (200+ lines)
- `src/claude_teams/server.py` - Fixed send_message to use `sender` param instead of hardcoded "team-lead" for message type
- `src/claude_teams/config_gen.py` - Fixed send_message example to use correct MCP parameter names with sender="{name}"

## Decisions Made
- Duplicated `_make_teammate` and `_data` helpers locally in test file rather than importing from test_server.py -- cleaner test isolation
- Combined the server.py sender bug fix with Task 1 commit since the tests exposed the bug

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] send_message handler ignored sender parameter for type="message"**
- **Found during:** Task 1 (integration test for agent sending message)
- **Issue:** `server.py` line 141 hardcoded `"team-lead"` as the from_name in `send_plain_message()` and the routing dict, ignoring the `sender` parameter entirely. Agents calling `send_message(sender="alice")` would have messages attributed to "team-lead".
- **Fix:** Changed `send_plain_message(team_name, "team-lead", ...)` to `send_plain_message(team_name, sender, ...)` and updated routing dict to use `sender` variable. Default parameter value is still "team-lead" so backward compatibility is preserved.
- **Files modified:** `src/claude_teams/server.py`
- **Verification:** test_agent_can_send_message_to_teammate passes (asserts `from="alice"`), all 38 existing server tests still pass
- **Committed in:** `cfd39cc` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential fix for MCP-02 requirement that agents can send messages attributed to themselves. No scope creep.

## Issues Encountered
- Tests cannot run natively on Windows due to `fcntl` (POSIX-only) dependency in messaging.py. Ran tests via WSL with `uv run pytest`. This is a known constraint documented in STATE.md.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All agent-callable MCP tools validated from agent perspective
- sender attribution confirmed working (critical for multi-agent messaging in 04-02)
- config_gen system prompt now produces correct tool call examples
- Ready for 04-02 (multi-agent communication patterns)

---
*Phase: 04-mcp-communication-validation*
*Completed: 2026-02-08*
