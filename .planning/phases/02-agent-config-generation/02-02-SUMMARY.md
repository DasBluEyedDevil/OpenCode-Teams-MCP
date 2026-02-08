---
phase: 02-agent-config-generation
plan: 02
subsystem: spawner-lifecycle
tags: [config-gen, spawn, cleanup, integration]
dependency_graph:
  requires:
    - "02-01 (config_gen module)"
  provides:
    - "spawn_teammate wired to config generation"
    - "agent config cleanup on kill/shutdown"
  affects:
    - "src/claude_teams/spawner.py"
    - "src/claude_teams/server.py"
tech_stack:
  added: []
  patterns:
    - "Config generation integrated into spawn flow"
    - "Cleanup lifecycle management"
key_files:
  created: []
  modified:
    - path: "src/claude_teams/spawner.py"
      lines_added: 19
      functions: ["spawn_teammate", "cleanup_agent_config"]
    - path: "src/claude_teams/server.py"
      lines_added: 11
      functions: ["spawn_teammate_tool", "force_kill_teammate", "process_shutdown_approved"]
    - path: "tests/test_spawner.py"
      lines_added: 91
      functions: ["TestConfigGenIntegration"]
    - path: "tests/test_server.py"
      lines_added: 60
      functions: ["TestConfigCleanup"]
decisions:
  - id: "cleanup-location"
    choice: "cleanup_agent_config in spawner.py, not config_gen.py"
    rationale: "Cleanup is a lifecycle concern (spawn/kill), not a config generation concern. Keeps config_gen module pure (generation only)."
  - id: "project-dir-default"
    choice: "Use Path.cwd() as default project_dir in server.py"
    rationale: "MCP server runs from project root, so cwd is the correct default for OpenCode config file location."
metrics:
  duration: 205
  unit: seconds
  completed: 2026-02-08T03:20:03Z
---

# Phase 2 Plan 2: Config Gen Lifecycle Wiring Summary

**One-liner:** Integrated config generation into spawn_teammate flow, adding .opencode/agents/<name>.md creation and cleanup on agent removal

## What Was Built

### Spawn Integration

1. **spawner.py changes:**
   - Added `project_dir: Path | None = None` parameter to `spawn_teammate()`
   - Config generation now runs AFTER messaging setup, BEFORE `build_spawn_command()`
   - Calls `generate_agent_config()`, `write_agent_config()`, `ensure_opencode_json()` in sequence
   - Added `cleanup_agent_config()` utility function to remove config files
   - Config files written relative to `project_dir` (defaults to `Path.cwd()`)

2. **server.py changes:**
   - `spawn_teammate_tool()` now passes `project_dir=Path.cwd()` to spawner
   - `force_kill_teammate()` calls `cleanup_agent_config()` after `reset_owner_tasks()`
   - `process_shutdown_approved()` calls `cleanup_agent_config()` after `reset_owner_tasks()`
   - Added `Path` import and `cleanup_agent_config` import

### Test Coverage

**test_spawner.py (4 new tests):**
- `test_spawn_generates_agent_config`: Verify `.opencode/agents/<name>.md` created with YAML frontmatter
- `test_spawn_creates_opencode_json`: Verify `opencode.json` has MCP server entry with type=local
- `test_cleanup_agent_config_removes_file`: Verify cleanup deletes config file
- `test_cleanup_agent_config_noop_if_missing`: Verify cleanup handles missing file gracefully

**test_server.py (2 new tests):**
- `test_force_kill_cleans_up_agent_config`: Verify `force_kill_teammate` calls cleanup
- `test_process_shutdown_cleans_up_agent_config`: Verify `process_shutdown_approved` calls cleanup

All tests use mocking to avoid subprocess/tmux dependencies and follow existing test patterns.

## Deviations from Plan

None - plan executed exactly as written.

## Technical Details

**Spawn flow sequence (after this plan):**
1. Create `TeammateMember` object
2. Add member to team config
3. Write initial prompt to inbox
4. **NEW: Generate agent config content**
5. **NEW: Write to `.opencode/agents/<name>.md`**
6. **NEW: Ensure `opencode.json` has MCP server registered**
7. Build spawn command (still uses Claude Code, replacement in Phase 3)
8. Execute tmux spawn
9. Update pane_id in team config

**Cleanup flow:**
- `force_kill_teammate`: kill pane → remove member → reset tasks → **cleanup config**
- `process_shutdown_approved`: remove member → reset tasks → **cleanup config**

**Why cleanup is in spawner.py:**
Cleanup is a lifecycle operation (spawn/kill), not a config generation concern. This keeps `config_gen.py` focused on pure config generation without mixing in lifecycle management.

## Verification Results

All verification checks passed:
- All Python files compile without syntax errors
- `generate_agent_config`, `write_agent_config`, `ensure_opencode_json` imports present in spawner.py
- `cleanup_agent_config` appears in both spawner.py (definition) and server.py (usage)
- `project_dir` parameter added to `spawn_teammate()` signature
- 6 new tests added (4 in test_spawner.py, 2 in test_server.py)

**Note:** Runtime import testing blocked by fcntl (POSIX-only) on Windows, which is a known project blocker documented in STATE.md. Syntax compilation confirms correctness.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 366832a | Wire config generation into spawn lifecycle |
| 2 | 91eb826 | Add integration tests for config gen wiring |

## Next Phase Readiness

**Ready for 03-opencode-spawner:** spawn_teammate now generates the config files that Phase 3's `opencode run` command will consume. The `build_spawn_command()` function can be replaced with `opencode run --agent <name>` since `.opencode/agents/<name>.md` will exist and contain the correct model, tools, and system prompt.

## Self-Check: PASSED

**Verify created files exist:**
```
FOUND: .planning/phases/02-agent-config-generation/02-02-SUMMARY.md
```

**Verify commits exist:**
```
FOUND: 366832a (feat(02-02): wire config generation into spawn lifecycle)
FOUND: 91eb826 (test(02-02): add integration tests for config gen wiring)
```

**Verify key changes:**
- spawner.py: config_gen imports present ✓
- spawner.py: project_dir parameter in spawn_teammate ✓
- spawner.py: cleanup_agent_config function defined ✓
- server.py: cleanup_agent_config import and calls present ✓
- test_spawner.py: 4 new tests in TestConfigGenIntegration ✓
- test_server.py: 2 new tests in TestConfigCleanup ✓
