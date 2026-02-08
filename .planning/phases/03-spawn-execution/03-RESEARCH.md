# Phase 3: Spawn Execution - Research

**Researched:** 2026-02-07
**Domain:** OpenCode `run` command construction, tmux pane spawning, pane ID tracking, initial prompt delivery, timeout wrapping
**Confidence:** HIGH

## Summary

Phase 3 replaces the existing `build_spawn_command()` function (which constructs Claude Code CLI flags like `--agent-id`, `--team-name`, `--parent-session-id`) with a new implementation that constructs `opencode run --agent <name>` commands. The tmux spawning mechanism itself (subprocess calling `tmux split-window -dP -F "#{pane_id}"`) remains architecturally identical -- only the command string inside the pane changes.

The existing `spawn_teammate()` function already handles the full lifecycle: validation, member registration, inbox creation, initial prompt delivery, tmux spawning, and pane ID tracking. Phase 3 rewires the command construction and adds timeout wrapping. The inbox/prompt delivery and pane ID capture logic are already correct and stay unchanged.

A critical design point: `opencode run` is a one-shot command that processes a prompt through the agent loop (LLM calls + tool calls in a loop, up to 1000 steps) and then exits. The agent does NOT exit after a single LLM call -- it loops with tool calls until it determines the task is complete. For team agents, the system prompt instructs the agent to poll its inbox and work continuously. When the agent eventually exits (task complete or timeout), the tmux pane closes automatically because `tmux split-window` with a command kills the pane on exit. This is acceptable behavior -- the pane closing is a natural signal that the agent has finished.

**Primary recommendation:** Replace `build_spawn_command()` to emit `opencode run --agent <name> --model <provider/model> --format json "<prompt>"` with timeout wrapping via `timeout 300`. Reuse the existing tmux spawn pattern, pane ID capture, and inbox delivery unchanged.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `shlex` | 3.12+ | `shlex.quote()` for shell command escaping | Already used in existing `build_spawn_command()` |
| Python stdlib `subprocess` | 3.12+ | `subprocess.run()` for tmux pane creation | Already used for tmux spawning in `spawn_teammate()` |
| Python stdlib `pathlib` | 3.12+ | Path construction for cwd and config paths | Already used throughout codebase |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Existing `config_gen.py` | Phase 2 output | Generate agent config before spawn | Called in spawn flow before command execution |
| Existing `messaging.py` | Codebase | Inbox creation and initial prompt delivery | Called in spawn flow before command execution |
| Existing `teams.py` | Codebase | Member registration and config updates | Called in spawn flow for member tracking |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `tmux split-window` | `tmux new-window` | `new-window` avoids splitting current pane but creates a new window per agent; `split-window` matches existing codebase and is user-visible |
| Shell `timeout` command | Python `subprocess.run(timeout=N)` | Shell `timeout` kills the child process directly; Python `subprocess.run(timeout=)` would not work here because we spawn via tmux, not as a direct subprocess |
| `opencode run` per-agent | `opencode serve` + `opencode run --attach` | `serve` avoids MCP cold boot but adds server lifecycle complexity; not needed for v1 |

**Installation:**
```bash
# No new dependencies -- all stdlib + existing codebase modules
```

## Architecture Patterns

### Recommended Project Structure
```
src/claude_teams/
  spawner.py          # MODIFY: replace build_spawn_command(), add timeout wrapping
  config_gen.py       # UNCHANGED (Phase 2 output, already called in spawn flow)
  server.py           # UNCHANGED for Phase 3 (already wired in Phase 2)
  models.py           # UNCHANGED for Phase 3
  messaging.py        # UNCHANGED (already delivers initial prompt)
  teams.py            # UNCHANGED (already manages member registration)
```

### Pattern 1: OpenCode Run Command Construction
**What:** Build the `opencode run` command string with the correct flags for spawning an agent in a tmux pane.
**When to use:** In `build_spawn_command()` (replaces current Claude Code command construction).
**Example:**
```python
# Source: OpenCode CLI docs (opencode.ai/docs/cli/) - verified flags
def build_opencode_run_command(
    member: TeammateMember,
    opencode_binary: str,
) -> str:
    """Build the opencode run command for spawning in a tmux pane.

    The command includes:
    - cd to the agent's working directory
    - timeout wrapping (RELY-01) to prevent indefinite hangs
    - opencode run with --agent, --model, and --format flags
    - The initial prompt as the positional argument
    """
    team_name = member.agent_id.split("@", 1)[1]
    cmd = (
        f"cd {shlex.quote(member.cwd)} && "
        f"timeout 300 "
        f"{shlex.quote(opencode_binary)} run "
        f"--agent {shlex.quote(member.name)} "
        f"--model {shlex.quote(member.model)} "
        f"--format json "
        f"{shlex.quote(member.prompt)}"
    )
    return cmd
```

### Pattern 2: Tmux Spawn with Pane ID Capture (Existing -- Unchanged)
**What:** Execute the spawn command in a detached tmux pane and capture its pane ID.
**When to use:** In `spawn_teammate()` after building the command (existing pattern).
**Example:**
```python
# Source: Existing spawner.py lines 190-197 -- this pattern does NOT change
result = subprocess.run(
    ["tmux", "split-window", "-dP", "-F", "#{pane_id}", cmd],
    capture_output=True,
    text=True,
    check=True,
)
pane_id = result.stdout.strip()
```

### Pattern 3: Spawn Flow Ordering (Existing -- Minimal Changes)
**What:** The spawn flow has a specific ordering: validate -> register -> inbox -> config -> command -> tmux -> track.
**When to use:** The existing `spawn_teammate()` already implements this correctly.
**Example:**
```python
def spawn_teammate(...) -> TeammateMember:
    # 1. Validate name (existing - unchanged)
    if not _VALID_NAME_RE.match(name): raise ValueError(...)

    # 2. Register member in team config (existing - unchanged)
    member = TeammateMember(...)
    teams.add_member(team_name, member, base_dir)

    # 3. Create inbox and deliver initial prompt (existing - unchanged)
    # SPAWN-09: Initial prompt delivered BEFORE spawn command executes
    messaging.ensure_inbox(team_name, name, base_dir)
    messaging.append_message(team_name, name, initial_msg, base_dir)

    # 4. Generate agent config (existing - added in Phase 2)
    config_content = generate_agent_config(...)
    write_agent_config(project, name, config_content)
    ensure_opencode_json(project, mcp_server_command="uv run claude-teams")

    # 5. Build spawn command (MODIFIED - Phase 3)
    cmd = build_opencode_run_command(member, opencode_binary)  # NEW

    # 6. Execute in tmux pane (existing - unchanged)
    result = subprocess.run(
        ["tmux", "split-window", "-dP", "-F", "#{pane_id}", cmd],
        capture_output=True, text=True, check=True,
    )

    # 7. Track pane ID (existing - unchanged)
    pane_id = result.stdout.strip()
    # ... update config with pane_id ...
```

### Anti-Patterns to Avoid

- **Passing the prompt via stdin instead of as a positional argument:** `opencode run` expects the prompt as a positional argument (`opencode run "prompt"`), not on stdin. Piping would hang.
- **Using `--model` without the `provider/` prefix:** The model flag requires the full `provider/model` format (e.g., `moonshot-ai/kimi-k2.5`). Passing just `kimi-k2.5` will fail to find the model.
- **Omitting `--format json` for non-interactive use:** Without `--format json`, `opencode run` outputs a spinner animation and formatted text that pollutes tmux pane content. JSON format produces clean structured output suitable for non-interactive use.
- **Using Python subprocess timeout instead of shell timeout:** The tmux command returns immediately (it creates a detached pane). Python's `subprocess.run(timeout=)` would timeout on the tmux command itself, not the opencode process inside the pane. Shell `timeout` inside the pane command is the correct approach.
- **Duplicating the prompt in both the command argument AND the inbox:** The existing code already writes the prompt to the inbox. The command argument to `opencode run` is what the agent processes first. Having it in both places is correct -- the inbox copy serves as a persistent record the agent can re-read.
- **Removing `is_active=False` from initial member creation:** The member starts as `is_active=False` because the spawn hasn't happened yet. The tmux pane launch is what makes the agent active. Do NOT set `is_active=True` before the tmux command succeeds.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Shell command escaping | Manual string quoting | `shlex.quote()` | Handles spaces, special chars, injection attacks |
| Timeout management | Custom watchdog thread | Shell `timeout` command | Battle-tested, handles signal delivery correctly, zero Python code |
| Pane ID capture | Parsing tmux output manually | `tmux split-window -dP -F "#{pane_id}"` | Official tmux format string, returns pane ID directly |
| Initial prompt delivery | Custom file writing | Existing `messaging.append_message()` | Already implemented, tested, uses file locking |
| Member registration | Direct JSON file manipulation | Existing `teams.add_member()` | Already implemented, handles duplicates, atomic writes |

**Key insight:** Phase 3 is primarily about string replacement in `build_spawn_command()` and adding a `timeout` wrapper. The existing spawn flow is correct -- the change is in WHAT command runs inside the tmux pane, not HOW the pane is created or tracked.

## Common Pitfalls

### Pitfall 1: opencode run Hangs on API Errors (No Exit)
**What goes wrong:** When `opencode run` encounters an API error (429 rate limit, auth failure), it logs internally but never exits. The process hangs indefinitely, blocking the tmux pane.
**Why it happens:** OpenCode's error handling lacks `process.exit()` for unrecoverable errors. This is a known, unresolved issue (GitHub #8203, #3213).
**How to avoid:** Wrap every `opencode run` invocation with `timeout 300` in the shell command. This kills the process after 5 minutes if it hasn't exited naturally. The `--kill-after` option can be added for SIGKILL after SIGTERM grace period: `timeout --kill-after=10 300`.
**Warning signs:** Agent pane shows no output for extended periods. Agent never reads inbox.

### Pitfall 2: Prompt Quoting in Shell Command
**What goes wrong:** The initial prompt may contain single quotes, double quotes, backticks, dollar signs, or other shell-special characters. If not properly escaped, the command breaks or is interpreted incorrectly.
**Why it happens:** The prompt is user-provided text passed as a shell argument inside a tmux command.
**How to avoid:** Use `shlex.quote()` on the prompt. This wraps the string in single quotes and handles internal single quotes. The existing codebase already uses `shlex.quote()` for other arguments.
**Warning signs:** Spawn fails with shell syntax errors. Agent receives truncated or mangled prompt.

### Pitfall 3: Tmux Pane Closes When Agent Exits
**What goes wrong:** When `opencode run` finishes processing, the tmux pane automatically closes. If someone is looking at the pane to monitor the agent, the output disappears.
**Why it happens:** `tmux split-window` with a command kills the pane when the command exits. This is tmux's default behavior.
**How to avoid:** This is actually DESIRED behavior for the system -- a closed pane means the agent has finished. The pane ID check (`tmux list-panes`) can determine if the agent is still running. If output preservation is needed later, use `remain-on-exit` window option, but this is a Phase 5 concern (agent monitoring), not Phase 3.
**Warning signs:** None -- this is expected behavior.

### Pitfall 4: build_spawn_command Parameter Name Still Says claude_binary
**What goes wrong:** The existing function signature uses `claude_binary` as the parameter name. The server lifespan context key was already updated to `opencode_binary` in Phase 2. If the parameter name is left as `claude_binary`, the code works but is confusing.
**Why it happens:** Incremental migration -- Phase 1/2 changed the lifespan key but not all downstream function signatures.
**How to avoid:** Rename the parameter from `claude_binary` to `opencode_binary` in the new function. Update all call sites (there is only one: `spawn_teammate()`).
**Warning signs:** Code reviews flag misleading parameter names.

### Pitfall 5: Missing --agent Flag Causes Fallback to Default Agent
**What goes wrong:** If `--agent <name>` is omitted or the agent name doesn't match a file in `.opencode/agents/`, OpenCode falls back to the "build" agent. The spawned agent runs without team awareness.
**Why it happens:** OpenCode silently falls back to default agents when the specified agent is not found. No error is raised.
**How to avoid:** Verify the agent config file exists at `.opencode/agents/<name>.md` before executing the spawn command. The Phase 2 `write_agent_config()` call in the spawn flow ensures this, but a defensive check is wise.
**Warning signs:** Agent starts but has no team context. Agent doesn't poll inbox or use MCP tools.

### Pitfall 6: Timeout Command Not Available on All Systems
**What goes wrong:** The `timeout` command (from GNU coreutils) may not be available on macOS by default (macOS ships with BSD coreutils which calls it `gtimeout`).
**Why it happens:** `timeout` is a GNU extension not in POSIX.
**How to avoid:** On macOS, use `gtimeout` from `brew install coreutils`, or implement a Python-based timeout monitor. Since the project already requires tmux (POSIX) and fcntl (POSIX), macOS users likely have coreutils. On Linux/WSL, `timeout` is always available.
**Warning signs:** `spawn_teammate()` fails with "timeout: command not found" on macOS.

## Code Examples

Verified patterns from official sources:

### Complete build_opencode_run_command Implementation
```python
# Source: OpenCode CLI docs (opencode.ai/docs/cli/), existing spawner.py pattern
import shlex
from claude_teams.models import TeammateMember

SPAWN_TIMEOUT_SECONDS = 300  # 5 minutes

def build_opencode_run_command(
    member: TeammateMember,
    opencode_binary: str,
    timeout_seconds: int = SPAWN_TIMEOUT_SECONDS,
) -> str:
    """Build the shell command for spawning an OpenCode agent in a tmux pane.

    Constructs: cd <cwd> && timeout <N> opencode run --agent <name> --model <model> --format json "<prompt>"

    The timeout wrapper (RELY-01) prevents indefinite hangs from API errors or
    permission prompts. The --format json flag produces clean structured output
    for non-interactive use.

    Args:
        member: TeammateMember with name, model, prompt, cwd fields
        opencode_binary: Path to the opencode binary (from discover_opencode_binary)
        timeout_seconds: Maximum time the agent can run before being killed

    Returns:
        Shell command string suitable for tmux split-window
    """
    cmd = (
        f"cd {shlex.quote(member.cwd)} && "
        f"timeout {timeout_seconds} "
        f"{shlex.quote(opencode_binary)} run "
        f"--agent {shlex.quote(member.name)} "
        f"--model {shlex.quote(member.model)} "
        f"--format json "
        f"{shlex.quote(member.prompt)}"
    )
    return cmd
```

### Updated spawn_teammate with OpenCode Command
```python
# Source: Existing spawner.py spawn_teammate() with Phase 3 modifications
def spawn_teammate(
    team_name: str,
    name: str,
    prompt: str,
    opencode_binary: str,  # Renamed from claude_binary
    lead_session_id: str,  # Still stored in config but not passed to opencode
    *,
    model: str = "sonnet",
    subagent_type: str = "general-purpose",
    cwd: str | None = None,
    plan_mode_required: bool = False,
    base_dir: Path | None = None,
    project_dir: Path | None = None,
) -> TeammateMember:
    # ... validation (unchanged) ...
    # ... member creation (unchanged) ...
    # ... team registration (unchanged) ...
    # ... inbox + initial prompt (unchanged, satisfies SPAWN-09) ...
    # ... config generation (unchanged, from Phase 2) ...

    # Phase 3: Build OpenCode run command instead of Claude command
    cmd = build_opencode_run_command(member, opencode_binary)

    # Tmux spawn (unchanged pattern)
    result = subprocess.run(
        ["tmux", "split-window", "-dP", "-F", "#{pane_id}", cmd],
        capture_output=True,
        text=True,
        check=True,
    )
    pane_id = result.stdout.strip()

    # Pane ID tracking (unchanged)
    # ... update config with pane_id ...
```

### Test Patterns for Phase 3
```python
# Test: Command construction
class TestBuildOpencodeRunCommand:
    def test_basic_format(self) -> None:
        member = _make_member("researcher", model="moonshot-ai/kimi-k2.5")
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        assert "opencode run" in cmd
        assert "--agent researcher" in cmd  # SPAWN-06
        assert "--model moonshot-ai/kimi-k2.5" in cmd  # SPAWN-06
        assert "--format json" in cmd
        assert "timeout 300" in cmd  # RELY-01
        assert f"cd /tmp" in cmd

    def test_prompt_is_shell_quoted(self) -> None:
        member = _make_member("worker")
        member.prompt = "Fix the bug in file 'main.py' and run tests"
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        # shlex.quote wraps in single quotes, handling internal quotes
        assert "Fix the bug" in cmd

    def test_no_claude_flags(self) -> None:
        member = _make_member("worker")
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        assert "--agent-id" not in cmd  # Claude flag removed
        assert "--team-name" not in cmd  # Claude flag removed
        assert "--parent-session-id" not in cmd  # Claude flag removed
        assert "--agent-color" not in cmd  # Claude flag removed
        assert "CLAUDECODE" not in cmd  # Claude env var removed
        assert "CLAUDE_CODE_EXPERIMENTAL" not in cmd  # Claude env var removed

    def test_custom_timeout(self) -> None:
        member = _make_member("worker")
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode", timeout_seconds=600)
        assert "timeout 600" in cmd

    def test_special_chars_in_prompt(self) -> None:
        member = _make_member("worker")
        member.prompt = 'Use "$HOME" and `backticks` safely'
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        # Command should not fail when passed to shell
        assert "$HOME" in cmd  # Content preserved (shell-safe via quoting)


# Test: Spawn flow integration
class TestSpawnTeammateOpenCode:
    @patch("claude_teams.spawner.subprocess")
    def test_spawn_calls_tmux_with_opencode_command(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        spawn_teammate(
            TEAM, "researcher", "Do research",
            "/usr/local/bin/opencode", SESSION_ID,
            base_dir=team_dir,
            model="moonshot-ai/kimi-k2.5",
        )
        # Verify tmux was called with opencode run command
        call_args = mock_subprocess.run.call_args
        tmux_cmd = call_args[0][0]
        assert tmux_cmd[0] == "tmux"
        assert tmux_cmd[1] == "split-window"
        assert "opencode run" in tmux_cmd[-1]  # SPAWN-06/07
        assert "--agent researcher" in tmux_cmd[-1]

    @patch("claude_teams.spawner.subprocess")
    def test_spawn_captures_pane_id(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        member = spawn_teammate(
            TEAM, "researcher", "Do research",
            "/usr/local/bin/opencode", SESSION_ID,
            base_dir=team_dir,
        )
        assert member.tmux_pane_id == "%42"  # SPAWN-08

    @patch("claude_teams.spawner.subprocess")
    def test_inbox_populated_before_spawn(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        spawn_teammate(
            TEAM, "researcher", "Do research",
            "/usr/local/bin/opencode", SESSION_ID,
            base_dir=team_dir,
        )
        msgs = messaging.read_inbox(TEAM, "researcher", base_dir=team_dir)
        assert len(msgs) == 1
        assert msgs[0].text == "Do research"  # SPAWN-09

    @patch("claude_teams.spawner.subprocess")
    def test_command_includes_timeout(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        spawn_teammate(
            TEAM, "researcher", "Do research",
            "/usr/local/bin/opencode", SESSION_ID,
            base_dir=team_dir,
        )
        call_args = mock_subprocess.run.call_args
        tmux_cmd = call_args[0][0]
        assert "timeout" in tmux_cmd[-1]  # RELY-01
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `build_spawn_command()` with Claude CLI flags | `build_opencode_run_command()` with `opencode run` flags | Phase 3 (now) | Command string changes, tmux mechanism unchanged |
| No timeout on spawn | `timeout 300` wrapper on opencode run | Phase 3 (now) | Hung processes killed after 5 minutes |
| `CLAUDECODE=1` env var in spawn | No env vars needed for OpenCode | Phase 3 (now) | Simpler command construction |
| `--agent-id`, `--team-name` CLI flags | `--agent` flag referencing config file | Phase 3 (now) | Team context via config file, not CLI flags |
| `--model sonnet` (Claude native) | `--model moonshot-ai/kimi-k2.5` (provider/model) | Phase 3 (now) | Model specified in provider/model format |
| `claude_binary` parameter name | `opencode_binary` parameter name | Phase 3 (now) | Naming consistency with Phase 1/2 |

**Deprecated/outdated:**
- `build_spawn_command()` function with Claude Code flags -- replaced entirely
- `CLAUDECODE=1` and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` env vars -- removed
- `--agent-id`, `--agent-name`, `--team-name`, `--agent-color`, `--parent-session-id`, `--agent-type` CLI flags -- none exist in OpenCode
- `--plan-mode-required` flag -- no equivalent in OpenCode; plan mode is handled via agent config

## Requirements Mapping

| Requirement | How Satisfied | Verification |
|-------------|---------------|--------------|
| **SPAWN-06**: Construct valid `opencode run --agent <name>` command | `build_opencode_run_command()` generates command with `--agent`, `--model`, `--format` flags | Unit test: command string contains expected flags |
| **SPAWN-07**: Spawn creates tmux pane with OpenCode process | Existing `tmux split-window -dP -F "#{pane_id}"` pattern unchanged | Unit test: subprocess.run called with tmux args |
| **SPAWN-08**: Pane ID captured and stored in team config | Existing pane ID parsing from stdout unchanged | Unit test: member.tmux_pane_id matches subprocess output |
| **SPAWN-09**: Initial prompt delivered to inbox before spawn | Existing `messaging.append_message()` call before tmux command unchanged | Unit test: inbox has message before subprocess.run |
| **RELY-01**: Timeout wrapping on spawn commands | `timeout 300` prepended to command string | Unit test: "timeout" in command string |

## Open Questions

1. **Timeout command availability on macOS**
   - What we know: `timeout` is GNU coreutils, available on Linux and WSL. macOS has `gtimeout` via Homebrew.
   - What's unclear: Whether all target users have `timeout` available.
   - Recommendation: Use `timeout` as the default. Document macOS requirement for `brew install coreutils`. If portability is critical, add a fallback that checks for `gtimeout` or implements Python-based timeout monitoring. However, since the project requires tmux and fcntl (both POSIX), macOS users already need additional tooling.

2. **Optimal timeout duration**
   - What we know: The pitfalls research suggests 300-600 seconds. `opencode run` can loop up to 1000 steps.
   - What's unclear: How long a typical team agent session runs before completing its work loop.
   - Recommendation: Default to 300 seconds (5 minutes) with a configurable parameter. This is long enough for substantial work but short enough to catch API error hangs. Make it configurable so it can be tuned per-deployment.

3. **Whether --format json is necessary for team agents**
   - What we know: `--format json` produces structured output, `default` produces spinner + formatted text. In a tmux pane, the output is visible but not parsed by our system.
   - What's unclear: Whether `--format json` affects the agent's behavior (tool calls, session management) or only its stdout output format.
   - Recommendation: Use `--format json` for cleaner non-interactive output. If it causes issues, `default` with `--quiet` (suppress spinner) is the alternative. The agent's behavior (tool calls, MCP usage) should be identical regardless of output format.

4. **lead_session_id parameter -- still needed?**
   - What we know: The existing function takes `lead_session_id` and passes it via `--parent-session-id` to Claude Code. OpenCode has no equivalent flag.
   - What's unclear: Whether to remove the parameter or keep it for config tracking purposes.
   - Recommendation: Keep the parameter in `spawn_teammate()` since it's stored in the team config and used by the team system for session tracking. Just don't pass it to the command. This is a Phase 8 cleanup concern.

## Sources

### Primary (HIGH confidence)
- [OpenCode CLI docs](https://opencode.ai/docs/cli/) -- `opencode run` flags: `--agent`, `--model`, `--format`, `--attach`, `--command`
- [OpenCode Agents docs](https://opencode.ai/docs/agents/) -- Agent config loading, `mode: primary` requirement, fallback behavior
- [OpenCode internals deep-dive](https://cefboud.com/posts/coding-agents-internals-opencode-deepdive/) -- Agent loop runs up to 1000 steps with tool calls, not one-shot
- Existing codebase `spawner.py` -- tmux spawn pattern at lines 190-207, verified working
- Existing codebase `test_spawner.py` -- Test patterns for command construction and spawn flow

### Secondary (MEDIUM confidence)
- [tmux split-window guide](https://gist.github.com/sdondley/b01cc5bb1169c8c83401e438a652b84e) -- Pane closes when command exits, `-dP -F` flags for ID capture
- [tmux man page](https://man7.org/linux/man-pages/man1/tmux.1.html) -- `remain-on-exit` option, `split-window` vs `new-window` behavior
- [OpenCode non-interactive mode issue #10411](https://github.com/anomalyco/opencode/issues/10411) -- Permissions auto-approved in run mode, no formal `--non-interactive` flag
- [opencode run hangs on errors #8203](https://github.com/anomalyco/opencode/issues/8203) -- Timeout wrapping is essential mitigation

### Tertiary (LOW confidence)
- Optimal timeout duration (300s) -- engineering judgment, no empirical data for team agent workloads
- `--format json` behavior interaction with agent loop -- not explicitly documented, inferred from CLI docs

## Metadata

**Confidence breakdown:**
- Command construction: HIGH -- `opencode run` flags verified from official CLI docs, existing `build_spawn_command` pattern well understood
- Tmux spawning: HIGH -- existing pattern is unchanged, just different command string
- Pane ID tracking: HIGH -- existing pattern is unchanged
- Inbox delivery: HIGH -- existing pattern is unchanged
- Timeout wrapping: HIGH -- `timeout` command is well-documented, confirmed as mitigation for known OpenCode hang bugs
- Agent loop behavior: MEDIUM-HIGH -- verified that `opencode run` loops with tool calls until completion, not one-shot

**Research date:** 2026-02-07
**Valid until:** 2026-02-21 (14 days -- OpenCode CLI flags stable, tmux interface stable)
