from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from claude_teams import messaging, teams
from claude_teams.config_gen import generate_agent_config, write_agent_config, ensure_opencode_json
from claude_teams.models import COLOR_PALETTE, InboxMessage, TeammateMember
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


def discover_claude_binary() -> str:
    path = shutil.which("claude")
    if path is None:
        raise FileNotFoundError(
            "Could not find 'claude' binary on PATH. "
            "Install Claude Code or ensure it is in your PATH."
        )
    return path


def assign_color(team_name: str, base_dir: Path | None = None) -> str:
    config = teams.read_config(team_name, base_dir)
    count = sum(1 for m in config.members if isinstance(m, TeammateMember))
    return COLOR_PALETTE[count % len(COLOR_PALETTE)]


def build_spawn_command(
    member: TeammateMember,
    claude_binary: str,
    lead_session_id: str,
) -> str:
    team_name = member.agent_id.split("@", 1)[1]
    cmd = (
        f"cd {shlex.quote(member.cwd)} && "
        f"CLAUDECODE=1 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 "
        f"{shlex.quote(claude_binary)} "
        f"--agent-id {shlex.quote(member.agent_id)} "
        f"--agent-name {shlex.quote(member.name)} "
        f"--team-name {shlex.quote(team_name)} "
        f"--agent-color {shlex.quote(member.color)} "
        f"--parent-session-id {shlex.quote(lead_session_id)} "
        f"--agent-type {shlex.quote(member.agent_type)} "
        f"--model {shlex.quote(member.model)}"
    )
    if member.plan_mode_required:
        cmd += " --plan-mode-required"
    return cmd


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
        backend_type="tmux",
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
    )
    write_agent_config(project, name, config_content)
    ensure_opencode_json(project, mcp_server_command="uv run claude-teams")

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
