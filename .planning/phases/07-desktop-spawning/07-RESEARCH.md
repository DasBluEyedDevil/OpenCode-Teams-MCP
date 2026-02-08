# Phase 7: Desktop Spawning - Research

**Researched:** 2026-02-08
**Domain:** Cross-platform desktop app launching, process lifecycle management, OpenCode desktop architecture (Tauri v2)
**Confidence:** MEDIUM

## Summary

Phase 7 adds a desktop app spawn path as an alternative to the existing tmux-based CLI spawn. The core challenge is that the OpenCode desktop app is a Tauri v2 application (not a CLI tool) that bundles its own sidecar CLI binary and communicates with the OpenCode backend server via HTTP/SSE. It does NOT support the same `opencode run --agent <name> "<prompt>"` flow that the CLI uses. There is no way to programmatically pass an agent name and prompt to the desktop app at launch time the way you can with `opencode run`.

This creates two viable implementation strategies:

**Strategy A: Launch desktop app + use `opencode serve` HTTP API to inject prompt.** Start `opencode serve` on a known port with the agent config already written, then launch the desktop app configured to connect to that server, then POST the prompt via the HTTP API. This is architecturally clean but complex -- it requires managing a server process, knowing its port, and orchestrating a multi-step launch sequence.

**Strategy B: Launch desktop app as a visual container, rely on existing inbox-based communication.** Launch the desktop app pointed at the project directory (which already has `.opencode/agents/<name>.md` and `opencode.json` with the MCP server), and send the initial task via the MCP inbox just as the CLI flow does. The agent reads its inbox on startup via the MCP tools configured in its agent config. This is simpler but requires the desktop app to open to the correct project and agent -- which may not be fully controllable without deep link support (currently absent, tracked as GitHub issue #6232).

**The most practical approach for v1 is a hybrid:** Use `subprocess.Popen` to launch the desktop app binary directly (not via `open -a` on macOS, to get the actual PID), with the working directory set to the project root, and rely on the agent config file + MCP inbox for task delivery. The desktop binary discovery uses platform-specific known paths (macOS `/Applications`, Windows `%LOCALAPPDATA%\Programs`, Linux `/usr/bin` or `~/.local/bin`) with `shutil.which` as a fallback for PATH-installed binaries.

**Primary recommendation:** Implement a `DesktopSpawner` class alongside the existing tmux spawner, sharing the agent config generation from Phase 2 and the inbox delivery from the existing spawn flow. Use `subprocess.Popen` for cross-platform process launch with PID tracking. The `backend_type` field on `TeammateMember` (already present, currently always "tmux") switches to "desktop" to enable different lifecycle management. Store the desktop process PID instead of `tmux_pane_id` for lifecycle checks (process alive via `os.kill(pid, 0)` or `psutil.pid_exists(pid)`).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `subprocess` | 3.12+ | `subprocess.Popen` for desktop app launch with PID tracking | Already used in spawner.py for tmux |
| Python stdlib `sys` / `platform` | 3.12+ | Platform detection for desktop binary discovery | Stdlib, no dependency |
| Python stdlib `os` | 3.12+ | `os.kill(pid, 0)` for process liveness check | Cross-platform signal 0 check |
| Python stdlib `shutil` | 3.12+ | `shutil.which()` for PATH-based binary discovery | Already used for opencode CLI discovery |
| Python stdlib `pathlib` | 3.12+ | Path construction for platform-specific install locations | Already used throughout codebase |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Existing `config_gen.py` | Phase 2 | Generate agent config before desktop spawn | Shared with CLI spawn flow |
| Existing `messaging.py` | Codebase | Inbox creation and initial prompt delivery | Shared with CLI spawn flow |
| Existing `teams.py` | Codebase | Member registration with `backend_type="desktop"` | Shared with CLI spawn flow |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `subprocess.Popen` + PID | `psutil.Popen` | psutil adds a dependency; stdlib Popen.pid + os.kill(pid, 0) is sufficient for basic lifecycle checks |
| Direct binary launch | `open -a` on macOS / `start` on Windows | OS launcher commands return immediately without the real app PID; direct binary launch gives us the actual PID |
| Desktop app binary | `opencode serve` + `opencode web` | Web UI is an alternative but requires managing a server process and browser; desktop app is a cleaner UX |
| Platform-specific paths | Only `shutil.which` | Desktop apps are not always on PATH; known install paths provide better discovery |

**Installation:**
```bash
# No new dependencies -- all stdlib + existing codebase modules
```

## Architecture Patterns

### Recommended Project Structure
```
src/claude_teams/
    spawner.py          # MODIFY: Add desktop spawn functions alongside tmux functions
    server.py           # MODIFY: Add backend_type parameter to spawn_teammate_tool
    models.py           # MODIFY: Add desktop_pid field to TeammateMember (or reuse tmux_pane_id)
    config_gen.py       # UNCHANGED (shared with CLI flow)
    messaging.py        # UNCHANGED (shared with CLI flow)
    teams.py            # UNCHANGED
    templates.py        # UNCHANGED
```

### Pattern 1: Desktop Binary Discovery (Platform-Specific)
**What:** Discover the OpenCode Desktop binary on Windows, macOS, and Linux using known installation paths with PATH fallback.
**When to use:** At server startup (in lifespan) or at first desktop spawn.
**Confidence:** MEDIUM -- binary names and install paths are inferred from Tauri conventions and release artifact names, not from official OpenCode documentation. Validation needed.
**Example:**
```python
import sys
import shutil
from pathlib import Path

# Known installation paths per platform
DESKTOP_PATHS: dict[str, list[str]] = {
    "darwin": [
        "/Applications/OpenCode Desktop.app/Contents/MacOS/OpenCode Desktop",
        str(Path.home() / "Applications/OpenCode Desktop.app/Contents/MacOS/OpenCode Desktop"),
    ],
    "win32": [
        str(Path.home() / "AppData/Local/Programs/opencode-desktop/opencode-desktop.exe"),
        str(Path.home() / "AppData/Local/opencode-desktop/opencode-desktop.exe"),
    ],
    "linux": [
        "/usr/bin/opencode-desktop",
        str(Path.home() / ".local/bin/opencode-desktop"),
        # AppImage may be anywhere -- rely on PATH
    ],
}

# PATH-searchable binary names per platform
DESKTOP_BINARY_NAMES: dict[str, list[str]] = {
    "darwin": ["opencode-desktop"],
    "win32": ["opencode-desktop.exe", "opencode-desktop"],
    "linux": ["opencode-desktop", "OpenCode-Desktop.AppImage"],
}


def discover_desktop_binary() -> str:
    """Discover the OpenCode Desktop binary on the current platform.

    Searches known installation paths first, then falls back to PATH.

    Returns:
        Path to the desktop binary.

    Raises:
        FileNotFoundError: If the desktop app is not found.
    """
    platform = sys.platform

    # 1. Check known installation paths
    for path_str in DESKTOP_PATHS.get(platform, []):
        p = Path(path_str)
        if p.exists() and p.is_file():
            return str(p)

    # 2. Fall back to PATH search
    for name in DESKTOP_BINARY_NAMES.get(platform, ["opencode-desktop"]):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        f"Could not find OpenCode Desktop on {platform}. "
        f"Install from https://opencode.ai/download"
    )
```

### Pattern 2: Cross-Platform Desktop App Launch with PID Tracking
**What:** Launch the desktop app binary using `subprocess.Popen` to get the actual process PID, with platform-specific flags to avoid blocking the parent.
**When to use:** When `backend_type="desktop"` is selected for spawn.
**Example:**
```python
import subprocess
import sys
from pathlib import Path


def launch_desktop_app(
    binary_path: str,
    cwd: str,
) -> int:
    """Launch OpenCode Desktop and return its PID.

    Uses subprocess.Popen for direct process creation, avoiding
    platform launcher commands (open, start) that don't return
    the actual app PID.

    Args:
        binary_path: Path to the desktop binary.
        cwd: Working directory (project root).

    Returns:
        PID of the launched desktop process.
    """
    kwargs: dict = {
        "cwd": cwd,
        "start_new_session": True,  # Detach from parent on POSIX
    }

    if sys.platform == "win32":
        # On Windows, CREATE_NEW_PROCESS_GROUP detaches the process
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs.pop("start_new_session", None)

    proc = subprocess.Popen(
        [binary_path],
        **kwargs,
    )
    return proc.pid
```

### Pattern 3: Process Liveness Check (Replaces tmux pane_alive)
**What:** Check if a desktop process is still running using its PID.
**When to use:** For health checking desktop-spawned agents.
**Example:**
```python
import os
import sys


def check_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running.

    Cross-platform: uses os.kill(pid, 0) on POSIX, which sends no signal
    but checks process existence. On Windows, uses os.kill which
    calls TerminateProcess on signal != 0, but signal 0 raises
    OSError if process doesn't exist.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists, False otherwise.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except SystemError:
        return False
```

### Pattern 4: Spawn Flow Branching (tmux vs. desktop)
**What:** Branch the spawn_teammate function to use either tmux or desktop based on a `backend_type` parameter.
**When to use:** In `spawn_teammate()` and `spawn_teammate_tool()`.
**Example:**
```python
def spawn_teammate(
    # ... existing params ...
    backend_type: str = "tmux",  # NEW: "tmux" or "desktop"
    desktop_binary: str | None = None,  # NEW: path to desktop app
) -> TeammateMember:
    # ... validation, member creation, inbox, config gen (SHARED) ...

    if backend_type == "tmux":
        # Existing tmux spawn path
        cmd = build_opencode_run_command(member, opencode_binary)
        result = subprocess.run(
            ["tmux", "split-window", "-dP", "-F", "#{pane_id}", cmd],
            capture_output=True, text=True, check=True,
        )
        member.tmux_pane_id = result.stdout.strip()

    elif backend_type == "desktop":
        # New desktop spawn path
        if not desktop_binary:
            raise ValueError("desktop_binary required for backend_type='desktop'")
        pid = launch_desktop_app(desktop_binary, member.cwd)
        member.tmux_pane_id = str(pid)  # Reuse field for PID storage
        # OR use a new field: member.desktop_pid = pid

    # ... config update (SHARED) ...
    return member
```

### Anti-Patterns to Avoid
- **Using `open -a` on macOS to launch the desktop app:** The `open` command is a wrapper that returns immediately. Its PID is the `open` process, not the actual desktop app. Use the binary path inside the `.app` bundle directly (`Contents/MacOS/<binary>`) to get the real PID.
- **Using `os.startfile()` or `start` on Windows:** These are "fire and forget" launchers that don't return a process handle. Use `subprocess.Popen` for PID tracking.
- **Assuming desktop binary is on PATH:** Desktop apps installed via .dmg, .exe installer, or .deb are typically NOT on PATH. They live in platform-specific application directories. Only CLI tools are on PATH. Use known paths + PATH fallback.
- **Trying to pass prompt as command-line argument to desktop app:** The desktop app is NOT `opencode run`. It has no `--agent` or `--model` CLI flags documented. The agent config and MCP inbox are the communication channels.
- **Adding psutil as a dependency for process checking:** `os.kill(pid, 0)` is sufficient for liveness checks. psutil adds ~10MB and a compiled C extension. Only add it if the project genuinely needs advanced process monitoring (CPU usage, memory, process tree).
- **Storing desktop PID in `tmux_pane_id` without documentation:** If reusing the existing field, add a clear comment and update the model docstring. Better: add a dedicated `process_id` field to `TeammateMember` and use `tmux_pane_id` only for tmux backend.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Process launch with PID | Custom fork/exec | `subprocess.Popen` | Cross-platform, stdlib, well-tested |
| Process liveness check | Platform-specific ps/tasklist parsing | `os.kill(pid, 0)` | Works on Windows and POSIX with zero parsing |
| Platform detection | Custom OS fingerprinting | `sys.platform` | Reliable values: "win32", "darwin", "linux" |
| Desktop binary discovery | Registry/plist parsing | Known paths + `shutil.which` | Simple, no external tools, covers 95% of installs |
| Process termination | Custom signal handling | `os.kill(pid, signal.SIGTERM)` on POSIX, `proc.terminate()` on Windows | Cross-platform via subprocess.Popen or os.kill |

**Key insight:** The desktop spawn is architecturally simpler than tmux spawn in one way (no tmux dependency) but harder in another (no way to programmatically pass agent/prompt to the desktop app). The system relies on the agent config file being pre-written to `.opencode/agents/<name>.md` and the MCP inbox for task delivery, which are already implemented in the shared spawn flow.

## Common Pitfalls

### Pitfall 1: Desktop App Does Not Auto-Load Agent Config
**What goes wrong:** The desktop app launches but does not automatically activate the agent defined in `.opencode/agents/<name>.md`. The user sees the default OpenCode UI, not the team agent.
**Why it happens:** The desktop app may require explicit agent selection via its UI. The `opencode run --agent <name>` flag is a CLI-only feature. The desktop app's agent selection mechanism may differ.
**How to avoid:** Research whether the desktop app reads `.opencode/agents/` on startup and presents them as available agents. If not, this is a fundamental blocker -- the user may need to manually select the agent in the desktop UI. Document this limitation clearly. A potential workaround is using `opencode serve --port <N>` + `POST /session` via the HTTP API to create a session with the correct agent.
**Warning signs:** Desktop-spawned agent has no team context. Agent doesn't poll inbox.
**Confidence:** LOW -- this is the biggest unknown. Need empirical validation.

### Pitfall 2: macOS Gatekeeper Blocks Direct Binary Launch
**What goes wrong:** Launching the binary at `Contents/MacOS/OpenCode Desktop` directly via subprocess.Popen may trigger macOS Gatekeeper or quarantine flags, showing a "damaged app" dialog.
**Why it happens:** macOS quarantines apps downloaded from the internet. The `.app` bundle has the quarantine extended attribute. Direct binary execution may bypass the normal launch flow that clears quarantine.
**How to avoid:** On macOS, consider using `subprocess.Popen(["open", "-a", "OpenCode Desktop", "--args", ...])` and accepting the PID limitation. Alternatively, use `xattr -cr` to clear quarantine before first launch. Or detect this and fall back to `open -a` with a post-launch PID scan.
**Warning signs:** "OpenCode Desktop.app is damaged" dialog on macOS.

### Pitfall 3: Windows Process Group and Console Window
**What goes wrong:** Launching the desktop app with `subprocess.Popen` on Windows creates a visible console window alongside the desktop app, or the desktop app inherits the parent's console.
**Why it happens:** Tauri apps on Windows may or may not have a console subsystem. If launched from a Python process that has a console, the child may inherit it.
**How to avoid:** Use `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS` on Windows to fully detach the desktop app from the parent console.
**Warning signs:** Unexpected console window appears alongside the desktop app.

### Pitfall 4: PID Does Not Match Actual Desktop Process
**What goes wrong:** The PID returned by `subprocess.Popen` is for a launcher/wrapper process, not the actual desktop app. When checking liveness, the launcher exits but the real app continues, making the system think the agent is dead.
**Why it happens:** Some installers (especially on Linux with AppImage, or macOS with `.app` bundles) use wrapper scripts or launcher binaries that exec the real process. Tauri apps may also fork during startup.
**How to avoid:** After launching, wait 2-3 seconds and then verify the PID is still alive. If the initial PID dies, scan for the desktop process by name using `psutil.process_iter()` or `pgrep`. This is a known limitation of process-based lifecycle tracking vs. tmux pane tracking.
**Warning signs:** Agent shows as "dead" immediately after spawn even though the desktop window is visible.

### Pitfall 5: Desktop App Requires User Interaction to Start Working
**What goes wrong:** The desktop app launches and displays the UI, but waits for the user to type a prompt or select a session. The agent never starts working autonomously because no prompt was programmatically submitted.
**Why it happens:** The desktop app is designed for interactive use, not headless agent execution. Unlike `opencode run` which takes a prompt argument, the desktop app waits for user input.
**How to avoid:** Two options: (1) Use the MCP inbox -- the agent config instructs the agent to check its inbox on startup, so the prompt delivered to the inbox triggers autonomous work. This requires the desktop app to activate the agent and start MCP tools without user interaction. (2) Use `opencode serve` + HTTP API to programmatically submit the prompt via `POST /session/:id/message`.
**Warning signs:** Desktop app is open but agent is idle. No MCP tool calls in logs.
**Confidence:** LOW -- needs empirical testing.

### Pitfall 6: No Deep Link Support Prevents Project-Specific Launch
**What goes wrong:** The desktop app launches but opens to the last-used project, not the one where the agent config and MCP server are configured.
**Why it happens:** OpenCode Desktop does not support deep links (GitHub issue #6232). There is no `opencode://project/<path>` URI scheme. The desktop app opens whatever project it last had open.
**How to avoid:** Set the `cwd` of the subprocess to the project directory and hope the desktop app uses `cwd` as the initial project. If not, the user may need to manually navigate to the correct project in the desktop UI. Alternatively, investigate whether the desktop app accepts a directory path as a CLI argument (the TUI does: `opencode [project]`).
**Warning signs:** Desktop app opens to the wrong project. Agent config not found.

## Code Examples

### Existing Spawn Flow (What Gets Extended)
```python
# Source: src/claude_teams/spawner.py, lines 160-243
# Current spawn_teammate() handles: validation, member creation, inbox,
# config gen, tmux spawn, pane ID tracking.
# Desktop spawn shares everything EXCEPT the tmux lines (227-233).
def spawn_teammate(
    team_name: str,
    name: str,
    prompt: str,
    opencode_binary: str,
    lead_session_id: str,
    *,
    model: str = "sonnet",
    # ... other params ...
) -> TeammateMember:
    # Lines 176-181: Validation (SHARED)
    # Lines 183-198: Member creation (SHARED)
    # Lines 200-210: Inbox + initial prompt (SHARED)
    # Lines 213-224: Config generation (SHARED)

    # Lines 226-233: Tmux spawn (DESKTOP ALTERNATIVE NEEDED)
    cmd = build_opencode_run_command(member, opencode_binary)
    result = subprocess.run(
        ["tmux", "split-window", "-dP", "-F", "#{pane_id}", cmd],
        capture_output=True, text=True, check=True,
    )
    pane_id = result.stdout.strip()

    # Lines 235-240: Config update (SHARED, but store PID instead of pane_id)
```

### Existing Model Fields (What Gets Extended)
```python
# Source: src/claude_teams/models.py, lines 30-45
class TeammateMember(BaseModel):
    # ... existing fields ...
    tmux_pane_id: str = Field(alias="tmuxPaneId")  # Currently always a tmux pane ID
    backend_type: str = Field(alias="backendType", default="tmux")  # Already exists!
    is_active: bool = Field(alias="isActive", default=False)
    # NEW: Desktop process ID (0 means not launched via desktop)
    # Option A: Add desktop_pid field
    # Option B: Reuse tmux_pane_id to store PID as string
```

### Existing Health Check (What Gets Adapted for Desktop)
```python
# Source: src/claude_teams/spawner.py, lines 354-431
# Currently uses tmux-specific checks. Desktop needs process-based checks.
def check_single_agent_health(member, previous_hash, last_change_time, ...):
    # Step 1: tmux pane liveness -- NEEDS DESKTOP BRANCH
    if not check_pane_alive(pane_id):  # tmux-specific
        return AgentHealthStatus(status="dead", ...)
    # Step 2: content hash -- tmux-specific, NO EQUIVALENT for desktop
    # Step 3-5: grace period, hung detection, alive -- SIMILAR logic

# Desktop version would check:
# 1. Process liveness via os.kill(pid, 0)
# 2. No content hash equivalent (desktop has no capturable terminal output)
# 3. Grace period works the same way
# 4. Hung detection CANNOT use content hashing -- would need alternative
#    (e.g., inbox activity, task status changes, MCP tool call recency)
```

### Existing MCP Tool Signature (What Gets Modified)
```python
# Source: src/claude_teams/server.py, lines 84-131
# Currently always spawns via tmux. Needs backend_type parameter.
@mcp.tool(name="spawn_teammate")
def spawn_teammate_tool(
    team_name: str,
    name: str,
    prompt: str,
    ctx: Context,
    model: str = "sonnet",
    template: str = "",
    custom_instructions: str = "",
    plan_mode_required: bool = False,
    # NEW: backend_type: str = "tmux"  -- "tmux" or "desktop"
) -> dict:
```

### Existing Kill Function (What Gets Extended)
```python
# Source: src/claude_teams/spawner.py, lines 246-248
# Currently tmux-only. Desktop needs process kill.
def kill_tmux_pane(pane_id: str) -> None:
    subprocess.run(["tmux", "kill-pane", "-t", pane_id], check=False)

# Desktop equivalent:
def kill_desktop_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass  # Process already dead
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| tmux-only agent spawning | tmux + desktop spawning | Phase 7 (now) | Users on Windows (no tmux) can use desktop app |
| `tmux_pane_id` for lifecycle | `tmux_pane_id` OR `process_id` based on backend_type | Phase 7 (now) | Lifecycle management adapts to spawn backend |
| `check_pane_alive()` tmux-only health | Process-based health check for desktop | Phase 7 (now) | Health monitoring works for desktop agents |
| No desktop binary discovery | Platform-specific binary discovery | Phase 7 (now) | System can find and launch desktop app |

**OpenCode Desktop architecture context:** The desktop app is built with Tauri v2 (Rust backend + SolidJS frontend). It bundles the OpenCode CLI as a sidecar binary and communicates with the backend server via HTTP/SSE. The desktop app does NOT support deep links (GitHub issue #6232). The app stores data in `~/.local/share/opencode/` (macOS/Linux) or `%USERPROFILE%\.local\share\opencode\` (Windows). The app auto-updates from GitHub Releases.

**Deprecated/outdated:**
- Nothing deprecated -- this is net-new functionality providing an alternative to tmux spawning.

## Design Decisions

### Decision 1: Reuse tmux_pane_id Field vs. Add New process_id Field
**Recommendation:** Add a new `process_id` field (`processId` in JSON alias) of type `int` with default `0`. Keep `tmux_pane_id` for tmux backend.

**Rationale:** The `tmux_pane_id` stores strings like `%42` (tmux pane format). Desktop PIDs are integers. Storing a PID as a string in `tmux_pane_id` works but is confusing -- the field name implies tmux. A separate `process_id` field is cleaner and the `backend_type` field (already present) tells the system which field to use.

**Alternative:** Rename `tmux_pane_id` to `backend_handle` and store either pane ID or PID as a string. This is cleaner but requires migration of existing team config JSON files.

**Recommendation strength:** MEDIUM -- either approach works. Separate field is cleaner; rename is more principled.

### Decision 2: Desktop Health Monitoring Without Content Hashing
**Recommendation:** For desktop backend, health status is: "alive" if `os.kill(pid, 0)` succeeds, "dead" if it raises. Skip hung detection entirely for v1 desktop agents.

**Rationale:** The tmux hung detection relies on `tmux capture-pane` to hash terminal content. Desktop apps have no equivalent -- you cannot programmatically capture what the desktop app is displaying. Alternative hung detection approaches (monitoring inbox activity, MCP tool call recency, task status changes) are possible but add significant complexity. For v1, knowing the process is alive or dead is sufficient. Hung detection for desktop can be added in v2 by monitoring MCP tool call timestamps from the server logs.

**Recommendation strength:** HIGH -- content hashing is fundamentally tmux-specific. Process liveness is the cross-platform minimum.

### Decision 3: Desktop Binary Discovery Strategy
**Recommendation:** Use a three-tier discovery: (1) environment variable `OPENCODE_DESKTOP_BINARY` override, (2) platform-specific known paths, (3) `shutil.which` PATH fallback.

**Rationale:** The environment variable override follows the established pattern (similar to `OPENCODE_EXECUTABLE` in the OpenCode ecosystem, GitHub issue #11283). Known paths cover standard installations. PATH fallback covers custom installations and package manager installs. This is the same pattern used by IDE integrations (VS Code looks for `code`, Cursor looks for `cursor`).

**Recommendation strength:** HIGH -- matches ecosystem conventions and provides good fallback chain.

### Decision 4: Backend Type Selection in MCP Tool
**Recommendation:** Add a `backend` parameter (default "tmux") to `spawn_teammate_tool()`. When set to "desktop", use the desktop spawn path.

**Rationale:** The team lead (MCP client) decides whether to use CLI or desktop based on the user's setup. Making it an explicit parameter keeps the decision visible. An alternative is auto-detecting based on tmux availability, but this removes user control and can be surprising.

**Recommendation strength:** HIGH -- explicit is better than implicit for infrastructure choices.

### Decision 5: Handling the "Desktop App Doesn't Auto-Run Agent" Problem
**Recommendation:** For v1, document that the desktop spawn opens the OpenCode Desktop app with the project directory containing the agent config. The user may need to select the agent manually in the desktop UI. The system delivers the prompt via MCP inbox, which the agent reads once activated.

**Rationale:** The fundamental uncertainty (Pitfall 1 and 5) is whether the desktop app will auto-activate an agent and start processing its MCP inbox autonomously. Without deep link support or documented CLI arguments for the desktop app, there is no guaranteed way to programmatically start a specific agent session. The safest approach for v1 is to handle what we CAN control (binary launch, PID tracking, agent config, inbox delivery) and document what requires user interaction. Full automation would require either (a) deep link support from OpenCode (not available) or (b) using `opencode serve` + HTTP API to create sessions programmatically.

**Recommendation strength:** MEDIUM -- this is a pragmatic v1 approach. The user experience is not fully automated. A future v2 could use `opencode serve` + HTTP API for full automation.

## Open Questions

1. **Does the OpenCode Desktop app accept a project directory as a CLI argument?**
   - What we know: The CLI TUI accepts `opencode [project]` to open a specific project. The desktop app is a Tauri binary.
   - What's unclear: Whether passing a directory path as an argument to the desktop binary causes it to open that project.
   - Recommendation: Test empirically: `"/Applications/OpenCode Desktop.app/Contents/MacOS/OpenCode Desktop" /path/to/project`. If this works, it solves the project targeting problem.
   - **Confidence:** LOW -- needs empirical validation.

2. **Does the OpenCode Desktop app auto-activate agents from `.opencode/agents/`?**
   - What we know: The CLI `opencode run --agent <name>` explicitly selects an agent. The desktop app shows agents in its UI.
   - What's unclear: Whether the desktop app will automatically start an agent session and begin processing MCP inbox messages without user interaction.
   - Recommendation: Test empirically with a pre-written agent config. If the desktop app requires manual agent selection, the desktop spawn path is a "launch and prepare" mechanism, not a fully automated spawn.
   - **Confidence:** LOW -- this is the critical uncertainty for the phase.

3. **What is the exact binary name/path for OpenCode Desktop on each platform?**
   - What we know: macOS releases as `.dmg` with name pattern `opencode-desktop-darwin-{arch}.dmg`. Homebrew cask is `opencode-desktop`. The app name in the `.dmg` is likely "OpenCode Desktop.app".
   - What's unclear: The exact binary name inside the Tauri app bundle on each platform. Windows installer creates what executable name. Linux installs to what path.
   - Recommendation: Install the desktop app on each platform and inspect the binary paths. Implement discovery with fallbacks and document the expected paths.
   - **Confidence:** LOW -- inferred from Tauri conventions and release artifact names, not from official documentation.

4. **Should `opencode serve` + HTTP API be used instead of launching the desktop app?**
   - What we know: `opencode serve` provides a full HTTP API including `POST /session/:id/message` for programmatic prompt submission. `opencode run --attach` can connect to a running server.
   - What's unclear: Whether this is more reliable than launching the desktop app directly. It would require managing a separate server process per agent.
   - Recommendation: Defer to v2. The HTTP API approach is more complex but more controllable. For v1, use direct desktop app launch for simplicity. If empirical testing reveals that the desktop app cannot be adequately controlled, pivot to the HTTP API approach.
   - **Confidence:** HIGH for the API capabilities (well-documented); LOW for whether it's the right choice for v1.

5. **How does desktop spawn interact with the existing `force_kill_teammate` and `process_shutdown_approved` tools?**
   - What we know: `force_kill_teammate` calls `kill_tmux_pane`. `process_shutdown_approved` calls `teams.remove_member`. Both need to handle desktop backend.
   - What's unclear: Whether killing the desktop process (SIGTERM) causes a clean exit or data loss.
   - Recommendation: Add a `kill_desktop_process(pid)` function and branch `force_kill_teammate` based on `backend_type`. Use SIGTERM (graceful) first, SIGKILL if the process doesn't exit within 5 seconds.
   - **Confidence:** HIGH for the implementation pattern; MEDIUM for graceful exit behavior.

## Sources

### Primary (HIGH confidence)
- [OpenCode CLI docs](https://opencode.ai/docs/cli/) -- `opencode run`, `opencode serve`, `--attach`, `--agent` flags
- [OpenCode Server docs](https://opencode.ai/docs/server/) -- HTTP API endpoints, SSE events, port configuration
- [OpenCode Download page](https://opencode.ai/download) -- Desktop app platform support, installer formats
- [OpenCode Desktop Architecture (DeepWiki)](https://deepwiki.com/sst/opencode/6.7-desktop-application) -- Tauri v2, sidecar CLI, SolidJS frontend, platform targets
- [OpenCode Installation and Setup (DeepWiki)](https://deepwiki.com/anomalyco/opencode/1.3-installation-and-setup) -- Sidecar binary bundling, data paths, troubleshooting
- [Python subprocess docs](https://docs.python.org/3/library/subprocess.html) -- Popen, PID tracking, cross-platform process creation
- Existing codebase: `src/claude_teams/spawner.py` -- tmux spawn pattern, health checks, binary discovery
- Existing codebase: `src/claude_teams/models.py` -- `TeammateMember.backend_type` field already exists

### Secondary (MEDIUM confidence)
- [OpenCode Distribution Channels (DeepWiki)](https://deepwiki.com/sst/opencode/10.3-distribution-channels) -- Desktop artifact naming pattern, platform targets
- [Tauri v2 Deep Linking docs](https://v2.tauri.app/plugin/deep-linking/) -- Deep link plugin architecture (not yet used by OpenCode)
- [Tauri v2 Windows Installer docs](https://v2.tauri.app/distribute/windows-installer/) -- NSIS installer, installation paths
- [Tauri v2 macOS Bundle docs](https://v2.tauri.app/distribute/macos-application-bundle/) -- `.app` bundle structure, resource paths
- [OpenCode Desktop deep link feature request (#6232)](https://github.com/anomalyco/opencode/issues/6232) -- Confirms no deep link support currently
- [psutil documentation](https://psutil.readthedocs.io/) -- Cross-platform process monitoring (considered but not recommended for v1)

### Tertiary (LOW confidence)
- Desktop binary names and installation paths -- Inferred from Tauri conventions, release artifact names, and package manager entries. Not verified by installing the actual app on each platform.
- Desktop app behavior when launched with project directory argument -- Untested hypothesis based on CLI TUI behavior.
- Agent auto-activation in desktop app -- Untested hypothesis. Critical unknown.

## Metadata

**Confidence breakdown:**
- Binary discovery: LOW -- paths inferred from conventions, not verified on actual installations
- Process launch + PID tracking: HIGH -- `subprocess.Popen` is well-documented, cross-platform stdlib
- Process lifecycle management: HIGH -- `os.kill(pid, 0)` and `proc.terminate()` are reliable cross-platform
- Desktop-agent integration: LOW -- whether the desktop app auto-loads agents and processes MCP inbox is unknown
- Architecture patterns: MEDIUM -- the spawn flow branching is straightforward, but desktop-specific edge cases (Gatekeeper, console windows, PID mismatch) need empirical validation

**Research date:** 2026-02-08
**Valid until:** 2026-02-22 (14 days -- OpenCode desktop is in beta and evolving rapidly; binary paths and CLI args may change between releases)
