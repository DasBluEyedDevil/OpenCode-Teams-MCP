---
phase: 02-agent-config-generation
plan: 01
subsystem: config_gen
tags: [tdd, opencode, yaml, mcp]
dependency_graph:
  requires:
    - spawner.py (model translation)
    - models.py (COLOR_PALETTE)
  provides:
    - generate_agent_config() - markdown builder
    - write_agent_config() - file writer
    - ensure_opencode_json() - MCP registration
  affects:
    - Phase 2 plan 02 (spawner integration)
    - All spawn operations going forward
tech_stack:
  added:
    - pyyaml>=6.0
  patterns:
    - YAML frontmatter generation
    - Read-modify-write JSON merging
    - Path-based file operations
key_files:
  created:
    - src/claude_teams/config_gen.py
    - tests/test_config_gen.py
  modified:
    - pyproject.toml
decisions:
  - decision: "Permission field uses string 'allow' not boolean True"
    rationale: "OpenCode non-interactive mode requires string shorthand"
    alternatives: "Per-tool permissions object (verbose, unnecessary)"
  - decision: "claude-teams_* wildcard for MCP tools in frontmatter"
    rationale: "Enables all MCP tools without listing each explicitly"
    alternatives: "List each tool individually (brittle if tools added)"
  - decision: "System prompt in body uses fully-qualified tool names"
    rationale: "MCP tools require claude-teams_ prefix in agent calls"
    alternatives: "Document bare names (would fail at runtime)"
  - decision: "ensure_opencode_json uses setdefault pattern for merging"
    rationale: "Preserves existing config, safe for re-spawns"
    alternatives: "Overwrite entire file (loses user config)"
metrics:
  duration: "3 minutes"
  tests_written: 32
  tests_passing: 32
  lines_of_code: 217
  completed: "2026-02-07"
---

# Phase 02 Plan 01: Agent Config Generation Module Summary

**One-liner:** Created config_gen.py with three core functions for generating OpenCode agent configs with YAML frontmatter, MCP tool permissions, and team coordination system prompts.

## Execution Summary

Followed TDD workflow (RED → GREEN → no REFACTOR needed). All 32 tests passing.

**Tasks completed:**
1. ✅ RED: Wrote comprehensive failing tests (32 test cases across 3 functions)
2. ✅ GREEN: Implemented config_gen.py with all three functions + added pyyaml dependency
3. ✅ REFACTOR: Not needed - implementation already clean and follows codebase conventions

## Implementation Details

### Three Core Functions

**1. generate_agent_config(agent_id, name, team_name, color, model) -> str**
- Builds complete markdown string with YAML frontmatter and system prompt body
- Frontmatter includes: mode="primary", permission="allow" (string), model, tools dict
- Tools dict: all builtins (read/write/edit/bash/etc) + "claude-teams_*": True
- System prompt sections: identity, inbox polling, sending messages, task management, shutdown protocol
- Tool references use fully-qualified names (claude-teams_read_inbox, etc.)

**2. write_agent_config(project_dir, name, config_content) -> Path**
- Creates .opencode/agents/ directory structure (parents=True, exist_ok=True)
- Writes config to .opencode/agents/<name>.md with UTF-8 encoding
- Overwrites existing file (handles re-spawn scenario)
- Returns path to created file

**3. ensure_opencode_json(project_dir, mcp_server_command, mcp_server_env=None) -> Path**
- Creates opencode.json if missing, merges if exists
- Preserves all existing keys using setdefault("mcp", {}) pattern
- Adds claude-teams MCP entry: {type: "local", command: "...", enabled: true}
- Optionally includes environment dict if provided
- Returns path to opencode.json

### Test Coverage

32 comprehensive tests across three test classes:

**TestGenerateAgentConfig (19 tests):**
- Frontmatter structure and delimiters
- Required fields: mode, model, permission (string type), tools dict
- All builtin tools enabled
- claude-teams_* wildcard enabled
- Body contains identity (name, team_name, agent_id, color)
- Body contains inbox polling instructions with claude-teams_read_inbox
- Body contains task management with claude-teams_task_list and claude-teams_task_update
- Body contains status values (in_progress, completed)
- Body contains shutdown protocol

**TestWriteAgentConfig (5 tests):**
- Creates .opencode/agents/ directory structure
- Writes file with correct name (<name>.md)
- Content matches input
- Overwrites existing (re-spawn scenario)
- UTF-8 encoding for unicode characters

**TestEnsureOpencodeJson (8 tests):**
- Creates new file with $schema and mcp section
- MCP entry has correct structure (type, command, enabled)
- Includes environment when provided
- Preserves existing config (other MCP servers, custom keys)
- Updates existing claude-teams entry
- Creates mcp section if missing

## Key Design Choices

**Permission as string "allow":** OpenCode's non-interactive mode (required for autonomous agents) uses a permission shorthand. String "allow" applies to all tools. Boolean True would fail.

**claude-teams_* wildcard:** Enables all MCP tools from claude-teams server without listing each tool explicitly. Future-proof if new tools are added.

**Fully-qualified tool names in system prompt:** Examples use `claude-teams_read_inbox`, not bare `read_inbox`. MCP tools require the prefix at runtime.

**Read-modify-write for opencode.json:** Uses `setdefault("mcp", {})` to preserve existing config when merging. Critical for projects with other MCP servers or custom settings.

**mode: "primary":** Required for `opencode run --agent <name>` CLI usage. Spawner will invoke agents using this command.

## Deviations from Plan

None - plan executed exactly as written. All must_haves truths verified by tests. All success criteria met.

## Next Phase Readiness

**Blocks:** None

**Enables:**
- Plan 02-02: Spawner integration (wire these functions into spawn_teammate)
- SPAWN-02 requirement: Dynamic config injection via .opencode/agents/<name>.md
- MCP-01 requirement: MCP server registration in opencode.json
- RELY-02 requirement: Non-interactive permissions via "allow" shorthand

**Required for continuation:** None - module is complete and tested

## Verification

```bash
# All tests pass
$ python -m pytest tests/test_config_gen.py -v
============================= 32 passed in 0.08s ==============================

# Module importable
$ python -c "from claude_teams.config_gen import generate_agent_config, write_agent_config, ensure_opencode_json; print('OK')"
OK

# Syntax valid
$ python -m py_compile src/claude_teams/config_gen.py
$ python -m py_compile tests/test_config_gen.py

# PyYAML declared
$ grep pyyaml pyproject.toml
    "pyyaml>=6.0",
```

## Self-Check: PASSED

**Created files:**
- ✅ src/claude_teams/config_gen.py exists
- ✅ tests/test_config_gen.py exists

**Modified files:**
- ✅ pyproject.toml (pyyaml dependency added)

**Commits:**
- ✅ 8494bf5: test(02-01): add failing tests for agent config generation
- ✅ b3e7526: feat(02-01): implement agent config generation module

All artifacts present and verified.
