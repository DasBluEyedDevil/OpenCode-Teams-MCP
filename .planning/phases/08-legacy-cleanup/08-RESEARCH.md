# Phase 8: Legacy Cleanup - Research

**Researched:** 2026-02-08
**Domain:** Code removal, test migration, documentation update
**Confidence:** HIGH

## Summary

Phase 8 is a pure deletion-and-update phase. All new OpenCode functionality (Phases 1-7) is already in place. The work is surgical removal of Claude Code-specific code paths, updating tests that still reference Claude model strings, and rewriting the README to describe the current OpenCode + Kimi K2.5 system.

The codebase is small (9 source files, 12 test files) and the Claude-specific code is concentrated in a few well-defined locations. There are no library decisions, no architecture changes, and no new features. The primary risk is breaking existing tests during removal -- which is easily caught by running the test suite after each deletion.

**Primary recommendation:** Execute in 2 plans: (1) Remove legacy code + update tests, (2) Update README and documentation. Keep the package name `claude-teams` and the `~/.claude/` storage paths unchanged -- these are protocol-compatible with Claude Code's native teams feature and renaming them would break backward compatibility for users who want to use both systems.

## Standard Stack

### Core

No new libraries. This phase only removes code and edits existing files.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=8.0 | Run test suite to verify nothing broke | Already in dev dependencies |

### Supporting

N/A -- no new dependencies.

### Alternatives Considered

N/A -- this is a deletion phase.

## Architecture Patterns

### Recommended Approach: Surgical Deletion, Not Refactoring

**What:** Remove specific functions and their tests, not restructure modules.
**When to use:** When the replacement code is already in place and working.
**Why:** The OpenCode equivalents (`discover_opencode_binary`, `build_opencode_run_command`) are already the production code paths. The Claude-specific functions (`discover_claude_binary`, `build_spawn_command`) are dead code that is never called in the production flow.

### Deletion Inventory

Based on thorough codebase analysis, here is the complete inventory of Claude-specific code to remove:

#### CLEAN-01: Remove `discover_claude_binary()` function

| Location | What | Action |
|----------|------|--------|
| `src/claude_teams/spawner.py:119-126` | `discover_claude_binary()` function | DELETE |
| `tests/test_spawner.py:80-91` | `TestDiscoverClaudeBinary` class (2 tests) | DELETE |
| `tests/test_spawner.py:23` | Import of `discover_claude_binary` | REMOVE from import list |

#### CLEAN-02: Remove `build_spawn_command()` function

| Location | What | Action |
|----------|------|--------|
| `src/claude_teams/spawner.py:135-155` | `build_spawn_command()` function | DELETE |
| `tests/test_spawner.py:108-129` | `TestBuildSpawnCommand` class (2 tests) | DELETE |
| `tests/test_spawner.py:18` | Import of `build_spawn_command` | REMOVE from import list |
| `tests/test_spawner.py:59-77` | `_make_member()` helper (only used by build_spawn_command tests) | DELETE (verify not used elsewhere first) |

#### CLEAN-03: Remove Claude Code CLI flag references

The Claude Code CLI flags (`--agent-id`, `--team-name`, `--parent-session-id`, `CLAUDECODE=1`, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) exist ONLY inside `build_spawn_command()` in source code. They also appear in test assertions:

| Location | What | Action |
|----------|------|--------|
| `tests/test_spawner.py:112-120` | Assertions for Claude flags in `build_spawn_command` | Removed with CLEAN-02 |
| `tests/test_spawner.py:193-202` | "no_claude_flags" negative assertions in `TestBuildOpencodeRunCommand` | KEEP as-is (these verify OpenCode commands do NOT contain Claude flags -- still valuable) |
| `tests/test_spawner.py:304` | `CLAUDECODE` not in tmux_cmd assertion | KEEP (same reason) |

#### CLEAN-04: Update tests to remove Claude-specific model strings

Several test files use `model="claude-sonnet-4-20250514"` or `model="claude-opus-4-6"` in test helpers, even though these are just arbitrary strings passed through. Update to Kimi K2.5 strings for consistency:

| Location | Current Value | New Value |
|----------|---------------|-----------|
| `tests/test_server.py:21` | `model="claude-sonnet-4-20250514"` | `model="moonshot-ai/kimi-k2.5"` |
| `tests/test_mcp_multi_agent.py:30` | `model="claude-sonnet-4-20250514"` | `model="moonshot-ai/kimi-k2.5"` |
| `tests/test_teams.py:26` | `model="claude-sonnet-4-20250514"` | `model="moonshot-ai/kimi-k2.5"` |
| `tests/test_models.py:43` | `model="claude-opus-4-6"` | `model="moonshot-ai/kimi-k2.5"` |
| `tests/test_models.py:60` | `"model": "claude-opus-4-6"` | `"model": "moonshot-ai/kimi-k2.5"` |
| `tests/test_models.py:129` | `model="claude-opus-4-6"` | `model="moonshot-ai/kimi-k2.5"` |
| `src/claude_teams/teams.py:43` | `lead_model: str = "claude-opus-4-6"` | `lead_model: str = "moonshot-ai/kimi-k2.5"` |

Note: The `lead_model` default in `teams.py:43` is used by `create_team()` for the LeadMember. This should be updated to a Kimi K2.5 model string since the system no longer supports Claude Code models.

#### CLEAN-04 (continued): Remove unused `lead_session_id` parameter from `spawn_teammate`

The `lead_session_id` parameter in `spawn_teammate()` is a vestige of the Claude Code spawning flow. It was used by `build_spawn_command()` for `--parent-session-id`. With `build_spawn_command()` gone, `lead_session_id` is no longer consumed anywhere in `spawn_teammate()`. However, note:

- `spawn_teammate()` signature includes `lead_session_id: str` (line 193)
- It is NOT used in the function body after Phase 3's refactor (the OpenCode path does not use it)
- `server.py:130` passes `ls["session_id"]` as the `lead_session_id` arg
- All test callers pass `SESSION_ID` as the 5th positional arg

**Recommendation:** Remove the `lead_session_id` parameter from `spawn_teammate()` and update all callers. This is clean and safe because the value is never used.

#### CLEAN-05: Update README and documentation

| Location | Current Content | New Content |
|----------|----------------|-------------|
| `README.md:1-7` | "claude-teams" title referencing Claude Code agent teams | Update to describe OpenCode + Kimi K2.5 teams |
| `README.md:15-19` | About section referencing Claude Code internals | Update to describe OpenCode MCP server |
| `README.md:23-36` | Install section with Claude Code `.mcp.json` | Update to OpenCode-first setup |
| `README.md:55-57` | Requirements: "Claude Code CLI on PATH" | Update to "OpenCode CLI on PATH" |
| `README.md:60-74` | Tools table mentioning "Claude Code teammate" | Update tool descriptions |
| `README.md:78` | "Spawning: Teammates launch as separate Claude Code processes" | Update spawning description |
| `pyproject.toml:8` | `description = "MCP server for orchestrating Claude Code agent teams"` | Update description |

### What NOT to Change

Critical: Several things that contain "claude" should NOT be renamed:

1. **Package name `claude-teams`** -- This is the MCP server name, used by all clients. Renaming requires updating every user's config.
2. **MCP server name `claude-teams`** in `server.py:46` -- Same reason.
3. **`~/.claude/` storage paths** -- Protocol-compatible with Claude Code's native teams. Renaming breaks interop.
4. **`claude-teams_*` tool prefix** in config_gen -- This is the MCP tool namespace, derived from the server name.
5. **The `src/claude_teams/` Python package directory** -- Renaming requires updating all imports, pyproject.toml, and is a much larger scope change.
6. **The `conftest.py` fixture `tmp_claude_dir`** -- This is just a test fixture name, harmless.
7. **The `CLAUDE_DIR` variable in `teams.py:19`** -- This is just a variable name pointing to `~/.claude`. Could be renamed for clarity but is optional and low-value.

### Anti-Patterns to Avoid

- **Renaming the package:** This is Phase 8 (cleanup), not a rebrand. Renaming `claude-teams` to `opencode-teams` would be a breaking change requiring a new package release, updated install instructions, and MCP config changes for every user. Out of scope.
- **Removing the negative test assertions:** The tests in `TestBuildOpencodeRunCommand` that assert `--agent-id not in cmd` etc. are still valuable -- they document that the OpenCode command format does not include Claude Code flags. Keep them.
- **Removing `~/.claude/` storage paths:** This would break all existing team data. The path is a protocol detail, not a brand reference.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Finding all references | Manual search | `grep -r` for each flag pattern | Comprehensive, catches edge cases |
| Verifying removal | Manual inspection | `pytest` full suite after each deletion step | Automated regression detection |

**Key insight:** This is a deletion phase. The only tool needed is grep (to find references) and pytest (to verify nothing broke).

## Common Pitfalls

### Pitfall 1: Removing Code That Tests Still Import
**What goes wrong:** Delete `discover_claude_binary` from spawner.py but forget to remove the import from test_spawner.py. Tests crash with ImportError.
**Why it happens:** The deletion inventory has multiple files per function.
**How to avoid:** Run `pytest` after each function deletion, not just at the end.
**Warning signs:** ImportError in test output.

### Pitfall 2: Breaking the `_make_member` Helper Shared by Other Tests
**What goes wrong:** Delete `_make_member()` from test_spawner.py thinking it is only used by `TestBuildSpawnCommand`, but another test class also uses it.
**Why it happens:** Grep for usage before deleting.
**How to avoid:** Verify `_make_member` is not used by `TestSpawnTeammate`, `TestSpawnTeammateNameValidation`, or any other class. Based on current analysis: `TestSpawnTeammateNameValidation` does NOT use `_make_member` (it calls `spawn_teammate` directly). `TestSpawnTeammate` does NOT use `_make_member` either. So `_make_member` is safe to remove.
**Warning signs:** NameError in test output.

### Pitfall 3: Removing `lead_session_id` Without Updating All Callers
**What goes wrong:** Remove the parameter from `spawn_teammate()` but forget to update one of the many test callers that pass it positionally.
**Why it happens:** The parameter is the 5th positional arg, not keyword.
**How to avoid:** Use grep to find ALL callers: `grep -rn "spawn_teammate" tests/ src/` and update each one.
**Warning signs:** TypeError: spawn_teammate() got unexpected argument.

### Pitfall 4: Over-Zealous Deletion of "claude" References
**What goes wrong:** Rename `claude-teams` MCP server name, breaking all client configurations.
**Why it happens:** Enthusiasm for cleanup exceeds scope.
**How to avoid:** Only remove code explicitly listed in CLEAN-01 through CLEAN-05 requirements. The package name, MCP server name, and storage paths are NOT in scope.
**Warning signs:** Users report "MCP server not found" errors.

### Pitfall 5: Forgetting to Update `lead_model` Default
**What goes wrong:** The `create_team` function still defaults to `claude-opus-4-6` for the lead member model.
**Why it happens:** It is a default parameter, not actively called with Claude model strings, so it is easy to miss.
**How to avoid:** It is in the deletion inventory under CLEAN-04. Update to `moonshot-ai/kimi-k2.5`.
**Warning signs:** Team configs on disk still contain `claude-opus-4-6` model strings for the lead member.

## Code Examples

### Deletion Pattern: Remove Function and Its Tests

```python
# BEFORE (spawner.py)
def discover_claude_binary() -> str:
    path = shutil.which("claude")
    if path is None:
        raise FileNotFoundError(...)
    return path

# AFTER: Function is completely removed from the file.
# No replacement needed -- discover_opencode_binary() is already the production path.
```

```python
# BEFORE (test_spawner.py)
from claude_teams.spawner import (
    build_spawn_command,
    discover_claude_binary,
    ...
)

class TestDiscoverClaudeBinary:
    ...

class TestBuildSpawnCommand:
    ...

# AFTER: Imports removed, test classes removed.
```

### Update Pattern: Replace Model Strings in Test Helpers

```python
# BEFORE (test_server.py)
def _make_teammate(name: str, team_name: str, pane_id: str = "%1") -> TeammateMember:
    return TeammateMember(
        ...
        model="claude-sonnet-4-20250514",
        ...
    )

# AFTER
def _make_teammate(name: str, team_name: str, pane_id: str = "%1") -> TeammateMember:
    return TeammateMember(
        ...
        model="moonshot-ai/kimi-k2.5",
        ...
    )
```

### Update Pattern: Remove Unused Parameter

```python
# BEFORE (spawner.py)
def spawn_teammate(
    team_name: str,
    name: str,
    prompt: str,
    opencode_binary: str,
    lead_session_id: str,    # <-- REMOVE
    *,
    ...
) -> TeammateMember:

# AFTER
def spawn_teammate(
    team_name: str,
    name: str,
    prompt: str,
    opencode_binary: str,
    *,
    ...
) -> TeammateMember:
```

```python
# BEFORE (server.py)
member = spawn_teammate(
    team_name=team_name,
    name=name,
    prompt=prompt,
    opencode_binary=ls["opencode_binary"],
    lead_session_id=ls["session_id"],    # <-- REMOVE
    ...
)

# AFTER
member = spawn_teammate(
    team_name=team_name,
    name=name,
    prompt=prompt,
    opencode_binary=ls["opencode_binary"],
    ...
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `discover_claude_binary()` | `discover_opencode_binary()` | Phase 1 | Claude function is dead code |
| `build_spawn_command()` with Claude CLI flags | `build_opencode_run_command()` | Phase 3 | Claude function is dead code |
| Claude model strings in tests | Kimi K2.5 model strings | This phase | Consistency, no functional impact |
| README describes Claude Code setup | README describes OpenCode setup | This phase | User-facing documentation |

**Deprecated/outdated:**
- `discover_claude_binary()`: Dead code since Phase 1. Remove.
- `build_spawn_command()`: Dead code since Phase 3. Remove.
- `lead_session_id` parameter: Unused since Phase 3. Remove.

## Open Questions

1. **Should `session_id` be removed from lifespan entirely?**
   - What we know: `session_id` is generated in `app_lifespan` and passed to `create_team` and `spawn_teammate` (as `lead_session_id`). `create_team` uses it for `lead_session_id` in the team config. With `lead_session_id` removed from `spawn_teammate`, the only consumer is `create_team`.
   - What's unclear: Is `lead_session_id` in the team config still meaningful for OpenCode agents?
   - Recommendation: Keep `session_id` in lifespan and `create_team` for now. It is stored in team config and could be useful for debugging or future features. Only `spawn_teammate`'s use of it is dead.

2. **Should `tmp_claude_dir` fixture be renamed?**
   - What we know: It is just a test fixture name. Renaming it to `tmp_base_dir` would be clearer but requires updating every test file that uses it.
   - Recommendation: Low priority. Could rename in this phase for cleanliness, but it is not a CLEAN requirement. Leave as-is unless it is trivial.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis of all 9 source files and 12 test files
- Grep results for `--agent-id`, `--team-name`, `--parent-session-id`, `CLAUDECODE`, `claude_binary`, `discover_claude_binary`, `build_spawn_command`
- Cross-reference with STATE.md decision: "[03-01]: Keep build_spawn_command for Phase 8 cleanup rather than deleting now"

### Secondary (MEDIUM confidence)
- REQUIREMENTS.md CLEAN-01 through CLEAN-05 definitions
- ROADMAP.md Phase 8 success criteria

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new libraries, just deletion and editing
- Architecture: HIGH - Direct codebase analysis, complete deletion inventory
- Pitfalls: HIGH - All risks are straightforward (ImportError, NameError, TypeError) and caught by pytest

**Research date:** 2026-02-08
**Valid until:** No expiration (deletion inventory is pinned to current codebase state)
