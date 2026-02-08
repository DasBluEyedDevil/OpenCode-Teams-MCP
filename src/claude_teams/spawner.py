from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from claude_teams import messaging, teams
from claude_teams.config_gen import generate_agent_config, write_agent_config, ensure_opencode_json
from claude_teams.models import AgentHealthStatus, COLOR_PALETTE, InboxMessage, TeammateMember
from claude_teams.teams import _VALID_NAME_RE


# OpenCode binary discovery and configuration constants
MINIMUM_OPENCODE_VERSION = (1, 1, 52)
DEFAULT_PROVIDER = "moonshot-ai"
SPAWN_TIMEOUT_SECONDS = 300

# Kimi K2.5 is the only supported model; all Claude aliases are equivalent
MODEL_ALIASES: dict[str, str] = {
    "sonnet": "kimi-k2.5",
    "opus": "kimi-k2.5",
    "haiku": "kimi-k2.5",
}

PROVIDER_MODEL_MAP: dict[str, str] = {
    "moonshot-ai": "moonshot-ai/kimi-k2.5",
    "moonshot-ai-china": "moonshot-ai-china/kimi-k2.5",
    "openrouter": "openrouter/moonshotai/kimi-k2.5",  # Note: no hyphen in moonshotai
    "novita": "novita/moonshotai/kimi-k2.5",
}

PROVIDER_CONFIGS: dict[str, dict] = {
    "moonshot-ai": {
        "apiKey": "{env:MOONSHOT_API_KEY}",
        "models": {
            "kimi-k2.5": {
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
            },
        },
    },
    "moonshot-ai-china": {
        "apiKey": "{env:MOONSHOT_API_KEY}",
        "options": {
            "baseURL": "https://api.moonshot.cn/v1",
        },
        "models": {
            "kimi-k2.5": {
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
            },
        },
    },
    "openrouter": {
        "apiKey": "{env:OPENROUTER_API_KEY}",
        "models": {
            "moonshotai/kimi-k2.5": {
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
            },
        },
    },
    "novita": {
        "npm": "@opencode/provider-novita",
        "name": "Novita AI",
        "apiKey": "{env:NOVITA_API_KEY}",
        "options": {
            "baseURL": "https://api.novita.ai/openai",
        },
        "models": {
            "moonshotai/kimi-k2.5": {
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
            },
        },
    },
}

_PROVIDER_ENV_VARS: dict[str, str] = {
    "moonshot-ai": "MOONSHOT_API_KEY",
    "moonshot-ai-china": "MOONSHOT_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "novita": "NOVITA_API_KEY",
}

# Desktop app binary discovery constants
DESKTOP_BINARY_ENV_VAR = "OPENCODE_DESKTOP_BINARY"

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
    ],
}

DESKTOP_BINARY_NAMES: dict[str, list[str]] = {
    "darwin": ["opencode-desktop"],
    "win32": ["opencode-desktop.exe", "opencode-desktop"],
    "linux": ["opencode-desktop", "OpenCode-Desktop.AppImage"],
}


def assign_color(team_name: str, base_dir: Path | None = None) -> str:
    config = teams.read_config(team_name, base_dir)
    count = sum(1 for m in config.members if isinstance(m, TeammateMember))
    return COLOR_PALETTE[count % len(COLOR_PALETTE)]


def build_opencode_run_command(
    member: TeammateMember,
    opencode_binary: str,
    timeout_seconds: int = SPAWN_TIMEOUT_SECONDS,
) -> str:
    """Build the shell command to run an OpenCode agent in a tmux pane.

    Constructs a command with cd, timeout wrapping, and opencode run flags.
    Does NOT include any Claude Code flags or environment variables.

    Args:
        member: The teammate member with name, model, prompt, and cwd.
        opencode_binary: Path to the opencode binary.
        timeout_seconds: Maximum seconds before the process is killed (default: 300).

    Returns:
        Shell command string suitable for tmux split-window.
    """
    return (
        f"cd {shlex.quote(member.cwd)} && "
        f"timeout {timeout_seconds} "
        f"{shlex.quote(opencode_binary)} run "
        f"--agent {shlex.quote(member.name)} "
        f"--model {shlex.quote(member.model)} "
        f"--format json "
        f"{shlex.quote(member.prompt)}"
    )


def spawn_teammate(
    team_name: str,
    name: str,
    prompt: str,
    opencode_binary: str,
    lead_session_id: str,
    *,
    model: str = "sonnet",
    subagent_type: str = "general-purpose",
    role_instructions: str = "",
    custom_instructions: str = "",
    backend_type: str = "tmux",
    desktop_binary: str | None = None,
    cwd: str | None = None,
    plan_mode_required: bool = False,
    base_dir: Path | None = None,
    project_dir: Path | None = None,
) -> TeammateMember:
    if not _VALID_NAME_RE.match(name):
        raise ValueError(f"Invalid agent name: {name!r}. Use only letters, numbers, hyphens, underscores.")
    if len(name) > 64:
        raise ValueError(f"Agent name too long ({len(name)} chars, max 64)")
    if name == "team-lead":
        raise ValueError("Agent name 'team-lead' is reserved")

    color = assign_color(team_name, base_dir)
    now_ms = int(time.time() * 1000)

    member = TeammateMember(
        agent_id=f"{name}@{team_name}",
        name=name,
        agent_type=subagent_type,
        model=model,
        prompt=prompt,
        color=color,
        plan_mode_required=plan_mode_required,
        joined_at=now_ms,
        tmux_pane_id="",
        cwd=cwd or str(Path.cwd()),
        backend_type=backend_type,
        is_active=False,
    )

    teams.add_member(team_name, member, base_dir)

    messaging.ensure_inbox(team_name, name, base_dir)
    initial_msg = InboxMessage(
        from_="team-lead",
        text=prompt,
        timestamp=messaging.now_iso(),
        read=False,
    )
    messaging.append_message(team_name, name, initial_msg, base_dir)

    # Generate agent config for OpenCode
    project = project_dir or Path.cwd()
    config_content = generate_agent_config(
        agent_id=member.agent_id,
        name=name,
        team_name=team_name,
        color=color,
        model=model,
        role_instructions=role_instructions,
        custom_instructions=custom_instructions,
    )
    write_agent_config(project, name, config_content)
    ensure_opencode_json(project, mcp_server_command="uv run claude-teams")

    if backend_type == "desktop":
        if not desktop_binary:
            raise ValueError("desktop_binary is required when backend_type='desktop'")
        pid = launch_desktop_app(desktop_binary, member.cwd)
        config = teams.read_config(team_name, base_dir)
        for m in config.members:
            if isinstance(m, TeammateMember) and m.name == name:
                m.process_id = pid
                m.backend_type = "desktop"
                break
        teams.write_config(team_name, config, base_dir)
        member.process_id = pid
    else:
        cmd = build_opencode_run_command(member, opencode_binary)
        result = subprocess.run(
            ["tmux", "split-window", "-dP", "-F", "#{pane_id}", cmd],
            capture_output=True,
            text=True,
            check=True,
        )
        pane_id = result.stdout.strip()
        config = teams.read_config(team_name, base_dir)
        for m in config.members:
            if isinstance(m, TeammateMember) and m.name == name:
                m.tmux_pane_id = pane_id
                break
        teams.write_config(team_name, config, base_dir)
        member.tmux_pane_id = pane_id

    return member


def kill_tmux_pane(pane_id: str) -> None:
    subprocess.run(["tmux", "kill-pane", "-t", pane_id], check=False)


def cleanup_agent_config(project_dir: Path, name: str) -> None:
    """Clean up agent config file when agent is killed or removed.

    Args:
        project_dir: Project root directory containing .opencode/agents/
        name: Agent name (used to derive config filename)
    """
    config_file = project_dir / ".opencode" / "agents" / f"{name}.md"
    config_file.unlink(missing_ok=True)


# Agent health detection constants and functions

DEFAULT_HUNG_TIMEOUT_SECONDS = 120
DEFAULT_GRACE_PERIOD_SECONDS = 60


def check_pane_alive(pane_id: str) -> bool:
    """Check whether a tmux pane is alive.

    Uses ``tmux display-message`` to query ``pane_dead`` for the given pane.

    Args:
        pane_id: tmux pane identifier (e.g. ``%42``).

    Returns:
        True if the pane exists and is not dead, False otherwise.
    """
    if not pane_id:
        return False
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_dead}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    if result.returncode != 0:
        return False
    return result.stdout.strip() == "0"


def capture_pane_content_hash(pane_id: str) -> str | None:
    """Capture visible pane content and return its SHA-256 hex digest.

    Uses ``tmux capture-pane -p`` (visible content only -- no ``-S-`` flag
    to avoid known hangs with large scroll-back buffers).

    Args:
        pane_id: tmux pane identifier (e.g. ``%42``).

    Returns:
        64-character hex digest of the pane content, or None on failure.
    """
    if not pane_id:
        return None
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", pane_id],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout.encode()).hexdigest()


def load_health_state(team_name: str, base_dir: Path | None = None) -> dict:
    """Load persisted health state for a team.

    Args:
        team_name: Name of the team.
        base_dir: Override base directory (for testing). Defaults to ``~/.claude``.

    Returns:
        Dict keyed by agent name, each value ``{"hash": str, "last_change_time": float}``.
        Returns empty dict if no health file exists.
    """
    teams_dir = (base_dir / "teams") if base_dir else teams.TEAMS_DIR
    health_path = teams_dir / team_name / "health.json"
    if not health_path.exists():
        return {}
    return json.loads(health_path.read_text())


def save_health_state(team_name: str, state: dict, base_dir: Path | None = None) -> None:
    """Persist health state for a team.

    Args:
        team_name: Name of the team.
        state: Dict keyed by agent name with hash and timestamp.
        base_dir: Override base directory (for testing). Defaults to ``~/.claude``.
    """
    teams_dir = (base_dir / "teams") if base_dir else teams.TEAMS_DIR
    health_path = teams_dir / team_name / "health.json"
    health_path.parent.mkdir(parents=True, exist_ok=True)
    health_path.write_text(json.dumps(state, indent=2))


def check_single_agent_health(
    member: TeammateMember,
    previous_hash: str | None,
    last_change_time: float | None,
    hung_timeout: int = DEFAULT_HUNG_TIMEOUT_SECONDS,
    grace_period: int = DEFAULT_GRACE_PERIOD_SECONDS,
) -> AgentHealthStatus:
    """Determine the health status of a single agent.

    Combines pane liveness, content hashing for hung detection, and a grace
    period for newly spawned agents.

    Args:
        member: The teammate member to check.
        previous_hash: Last known content hash (or None if first check).
        last_change_time: Epoch timestamp when content last changed (or None).
        hung_timeout: Seconds of unchanged content before declaring hung.
        grace_period: Seconds after spawn during which the agent is not
            considered hung (allows for startup time).

    Returns:
        AgentHealthStatus with the determined status and detail.
    """
    # Desktop backend: process-based liveness only, no hung detection
    if member.backend_type == "desktop":
        pid = member.process_id
        if not check_process_alive(pid):
            return AgentHealthStatus(
                agent_name=member.name,
                pane_id=str(pid),
                status="dead",
                detail="Desktop process is no longer running",
            )
        return AgentHealthStatus(
            agent_name=member.name,
            pane_id=str(pid),
            status="alive",
            detail="Desktop process is running",
        )

    # Tmux backend: existing logic (unchanged)
    pane_id = member.tmux_pane_id

    # Step 1: pane liveness
    if not check_pane_alive(pane_id):
        return AgentHealthStatus(
            agent_name=member.name,
            pane_id=pane_id,
            status="dead",
            detail="Pane is missing or dead",
        )

    # Step 2: capture content hash
    current_hash = capture_pane_content_hash(pane_id)
    if current_hash is None:
        return AgentHealthStatus(
            agent_name=member.name,
            pane_id=pane_id,
            status="unknown",
            detail="Failed to capture pane content",
        )

    # Step 3: grace period -- recently spawned agents are always "alive"
    age_seconds = (time.time() * 1000 - member.joined_at) / 1000
    if age_seconds < grace_period:
        return AgentHealthStatus(
            agent_name=member.name,
            pane_id=pane_id,
            status="alive",
            last_content_hash=current_hash,
            detail=f"Within grace period ({age_seconds:.0f}s / {grace_period}s)",
        )

    # Step 4: hung detection
    if (
        previous_hash is not None
        and current_hash == previous_hash
        and last_change_time is not None
        and time.time() - last_change_time >= hung_timeout
    ):
        return AgentHealthStatus(
            agent_name=member.name,
            pane_id=pane_id,
            status="hung",
            last_content_hash=current_hash,
            detail=f"Content unchanged for {time.time() - last_change_time:.0f}s (threshold: {hung_timeout}s)",
        )

    # Step 5: alive
    return AgentHealthStatus(
        agent_name=member.name,
        pane_id=pane_id,
        status="alive",
        last_content_hash=current_hash,
        detail="Pane is active",
    )


# OpenCode binary discovery and configuration functions


def discover_opencode_binary() -> str:
    """Discover the opencode binary on PATH and validate its version.

    Returns:
        Path to the opencode binary.

    Raises:
        FileNotFoundError: If opencode is not found on PATH.
        RuntimeError: If the version is too old or cannot be validated.
    """
    path = shutil.which("opencode")
    if path is None:
        raise FileNotFoundError(
            "Could not find 'opencode' binary on PATH. "
            "Install from https://opencode.ai"
        )
    validate_opencode_version(path)
    return path


def discover_desktop_binary() -> str:
    """Discover the OpenCode Desktop binary on the current platform.

    Discovery order:
    1. OPENCODE_DESKTOP_BINARY environment variable (explicit override)
    2. Known installation paths for the current platform
    3. PATH search via shutil.which

    Returns:
        Path to the desktop binary.

    Raises:
        FileNotFoundError: If the desktop app is not found.
    """
    # 1. Environment variable override
    env_path = os.environ.get(DESKTOP_BINARY_ENV_VAR)
    if env_path:
        p = Path(env_path)
        if p.exists() and p.is_file():
            return str(p)
        raise FileNotFoundError(
            f"{DESKTOP_BINARY_ENV_VAR} is set to {env_path!r} but the file does not exist"
        )

    platform = sys.platform

    # 2. Known installation paths
    for path_str in DESKTOP_PATHS.get(platform, []):
        p = Path(path_str)
        if p.exists() and p.is_file():
            return str(p)

    # 3. PATH fallback
    for name in DESKTOP_BINARY_NAMES.get(platform, ["opencode-desktop"]):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        f"Could not find OpenCode Desktop on {platform}. "
        f"Install from https://opencode.ai/download or set {DESKTOP_BINARY_ENV_VAR}"
    )


def launch_desktop_app(binary_path: str, cwd: str) -> int:
    """Launch OpenCode Desktop and return its PID.

    Uses subprocess.Popen for direct process creation to get the actual
    PID. Avoids platform launcher commands (open, start) that don't
    return the real app PID.

    Args:
        binary_path: Path to the desktop binary.
        cwd: Working directory (project root).

    Returns:
        PID of the launched desktop process.
    """
    kwargs: dict = {
        "cwd": cwd,
    }

    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen([binary_path], **kwargs)
    return proc.pid


def check_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running.

    Cross-platform: uses os.kill(pid, 0) which sends no signal but
    checks process existence. Raises OSError if the process does not
    exist.

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
    except (OSError, SystemError):
        return False


def kill_desktop_process(pid: int) -> None:
    """Terminate a desktop process by PID.

    Sends SIGTERM on POSIX or calls TerminateProcess on Windows.
    Does not raise if the process is already dead.

    Args:
        pid: Process ID to terminate.
    """
    if pid <= 0:
        return
    try:
        if sys.platform == "win32":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, SystemError):
        pass  # Process already dead


def validate_opencode_version(binary_path: str) -> str:
    """Validate that the opencode binary meets minimum version requirements.

    Args:
        binary_path: Path to the opencode binary.

    Returns:
        The version string (e.g., "1.1.52").

    Raises:
        RuntimeError: If version is too old, cannot be parsed, or binary hangs/fails.
    """
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Timed out waiting for {binary_path} --version. "
            "The binary may be hung or unresponsive."
        )
    except FileNotFoundError:
        raise RuntimeError(
            f"Binary not found at {binary_path}. "
            "The path may be invalid or the binary was removed."
        )

    output = result.stdout + result.stderr
    match = re.search(r"v?(\d+\.\d+\.\d+)", output)

    if not match:
        raise RuntimeError(
            f"Could not parse version from opencode --version output: {output!r}"
        )

    version_str = match.group(1)
    version_tuple = tuple(int(x) for x in version_str.split("."))

    if version_tuple < MINIMUM_OPENCODE_VERSION:
        min_version_str = ".".join(str(x) for x in MINIMUM_OPENCODE_VERSION)
        raise RuntimeError(
            f"opencode version {version_str} is too old. "
            f"Minimum required: {min_version_str}. "
            f"Update with: npm install -g opencode@latest"
        )

    return version_str


def translate_model(model_alias: str, provider: str = DEFAULT_PROVIDER) -> str:
    """Translate a model alias to a provider-specific model string.

    Args:
        model_alias: Model name or alias (e.g., "sonnet", "opus", "moonshot-ai/kimi-k2.5").
        provider: Provider name (default: moonshot-ai).

    Returns:
        Full provider/model string (e.g., "moonshot-ai/kimi-k2.5").
    """
    # Passthrough if already in provider/model format
    if "/" in model_alias:
        return model_alias

    # Resolve alias to base model name
    model_name = MODEL_ALIASES.get(model_alias, model_alias)

    # Look up provider-specific model string
    if provider in PROVIDER_MODEL_MAP:
        return PROVIDER_MODEL_MAP[provider]

    # Fallback for unknown providers
    return f"{provider}/{model_name}"


def get_provider_config(provider: str) -> dict:
    """Get the configuration block for a specific provider.

    Args:
        provider: Provider name (e.g., "moonshot-ai", "openrouter").

    Returns:
        Dictionary with provider configuration (credentials use {env:VAR_NAME} syntax).

    Raises:
        ValueError: If the provider is not supported.
    """
    if provider not in PROVIDER_CONFIGS:
        supported = ", ".join(PROVIDER_CONFIGS.keys())
        raise ValueError(
            f"Unknown provider: {provider!r}. Supported providers: {supported}"
        )

    return {provider: PROVIDER_CONFIGS[provider]}


def get_credential_env_var(provider: str) -> str:
    """Get the environment variable name for a provider's API key.

    Args:
        provider: Provider name (e.g., "moonshot-ai").

    Returns:
        Environment variable name (e.g., "MOONSHOT_API_KEY").
    """
    if provider in _PROVIDER_ENV_VARS:
        return _PROVIDER_ENV_VARS[provider]

    # Fallback for unknown providers
    return f"{provider.upper().replace('-', '_')}_API_KEY"
