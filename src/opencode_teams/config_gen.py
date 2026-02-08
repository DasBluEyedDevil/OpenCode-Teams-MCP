from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import yaml


OPENCODE_JSON_SCHEMA = "https://opencode-files.s3.amazonaws.com/schemas/opencode.json"


def generate_agent_config(
    agent_id: str,
    name: str,
    team_name: str,
    color: str,
    model: str,
    role_instructions: str = "",
    custom_instructions: str = "",
) -> str:
    """Generate OpenCode agent config markdown with YAML frontmatter and system prompt.

    Args:
        agent_id: Full agent identifier (e.g., "alice@team1")
        name: Agent name
        team_name: Team name
        color: Agent color from COLOR_PALETTE
        model: Model string (e.g., "moonshot-ai/kimi-k2.5")
        role_instructions: Optional role-specific instructions from a template.
            Injected between Identity and Communication Protocol sections.
        custom_instructions: Optional user-provided instructions per spawn.
            Wrapped with "# Additional Instructions" heading.

    Returns:
        Complete markdown config string with frontmatter and body
    """
    # Build frontmatter dict
    frontmatter = {
        "description": f"Team agent {name} on team {team_name}",
        "model": model,
        "mode": "primary",
        "permission": "allow",  # Must be string "allow", not boolean
        "tools": {
            # All builtin tools enabled
            "read": True,
            "write": True,
            "edit": True,
            "bash": True,
            "glob": True,
            "grep": True,
            "list": True,
            "webfetch": True,
            "websearch": True,
            "todoread": True,
            "todowrite": True,
            # opencode-teams MCP tools (wildcard enables all)
            "opencode-teams_*": True,
        },
    }

    # Convert frontmatter to YAML
    frontmatter_yaml = yaml.dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    # Build system prompt body from sections
    body_parts: list[str] = []

    # Section 1: Agent Identity
    body_parts.append(textwrap.dedent(f"""\
        # Agent Identity

        You are **{name}**, a member of team **{team_name}**.

        - Agent ID: `{agent_id}`
        - Color: {color}"""))

    # Section 2: Role instructions (from template, if provided)
    if role_instructions:
        body_parts.append(role_instructions.strip())

    # Section 3: Custom instructions (user per-spawn customization, if provided)
    if custom_instructions:
        body_parts.append(
            f"# Additional Instructions\n\n{custom_instructions.strip()}"
        )

    # Section 4: Communication Protocol
    body_parts.append(textwrap.dedent(f"""\
        # Communication Protocol

        ## Inbox Polling

        Check your inbox regularly by calling `opencode-teams_read_inbox` every 3-5 tool calls.
        Always check your inbox before starting new work to see if you have messages or task assignments.

        Example:
        ```
        opencode-teams_read_inbox(team_name="{team_name}", agent_name="{name}")
        ```

        ## Sending Messages

        Use `opencode-teams_send_message` to communicate with team members or the team lead.

        Example:
        ```
        opencode-teams_send_message(
            team_name="{team_name}",
            type="message",
            recipient="team-lead",
            content="Status update: task completed",
            summary="status update",
            sender="{name}"
        )
        ```"""))

    # Section 5: Task Management
    body_parts.append(textwrap.dedent(f"""\
        # Task Management

        ## Viewing Tasks

        Use `opencode-teams_task_list` to see available tasks.

        Example:
        ```
        opencode-teams_task_list(team_name="{team_name}")
        ```

        ## Claiming and Updating Tasks

        Use `opencode-teams_task_update` to claim tasks or update their status.

        Status values:
        - `in_progress`: You are working on this task
        - `completed`: Task is finished

        Example:
        ```
        opencode-teams_task_update(
            team_name="{team_name}",
            task_id="task-123",
            status="in_progress",
            owner="{name}"
        )
        ```"""))

    # Section 6: Shutdown Protocol
    body_parts.append(textwrap.dedent("""\
        # Shutdown Protocol

        When you receive a `shutdown_request` message, acknowledge it and prepare to exit gracefully."""))

    body = "\n\n".join(body_parts)

    # Combine frontmatter and body
    config = f"---\n{frontmatter_yaml}---\n\n{body}\n"

    return config


def cleanup_agent_config(project_dir: Path, name: str) -> None:
    """Clean up agent config file when agent is killed or removed.

    Args:
        project_dir: Project root directory containing .opencode/agents/
        name: Agent name (used to derive config filename)
    """
    config_file = project_dir / ".opencode" / "agents" / f"{name}.md"
    config_file.unlink(missing_ok=True)


def write_agent_config(
    project_dir: Path,
    name: str,
    config_content: str,
) -> Path:
    """Write agent config to .opencode/agents/<name>.md

    Creates the .opencode/agents directory if it doesn't exist.
    Overwrites existing file (re-spawn scenario).

    Args:
        project_dir: Project root directory
        name: Agent name (used for filename)
        config_content: Complete markdown config content

    Returns:
        Path to the created config file
    """
    agents_dir = project_dir / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    config_path = agents_dir / f"{name}.md"
    config_path.write_text(config_content, encoding="utf-8")

    return config_path


def ensure_opencode_json(
    project_dir: Path,
    mcp_server_command: str,
    mcp_server_env: dict[str, str] | None = None,
) -> Path:
    """Create or update opencode.json in the project root with opencode-teams MCP server entry.

    OpenCode reads its configuration from ``opencode.json`` (or ``opencode.jsonc``)
    in the project root — NOT from ``.opencode/config.json``.
    See: https://opencode.ai/docs/config/

    If opencode.json exists, preserves all existing keys and merges the opencode-teams
    MCP entry. If it doesn't exist, creates a new file with schema and MCP config.

    Args:
        project_dir: Project root directory
        mcp_server_command: Command to start MCP server (e.g., "uv run opencode-teams")
        mcp_server_env: Optional environment variables for MCP server

    Returns:
        Path to opencode.json
    """
    opencode_json_path = project_dir / "opencode.json"

    # Read existing or create new
    if opencode_json_path.exists():
        content = json.loads(opencode_json_path.read_text(encoding="utf-8"))
    else:
        content = {
            "$schema": OPENCODE_JSON_SCHEMA,
        }

    # Ensure mcp section exists
    content.setdefault("mcp", {})

    # OpenCode expects MCP entries as McpLocalConfig objects with type + command array
    # See: @opencode-ai/sdk types.gen.d.ts McpLocalConfig
    command_parts = mcp_server_command.split()

    mcp_entry: dict[str, Any] = {
        "type": "local",
        "command": command_parts,
        "enabled": True,
    }
    if mcp_server_env:
        mcp_entry["environment"] = mcp_server_env

    content["mcp"]["opencode-teams"] = mcp_entry

    # Write back
    opencode_json_path.write_text(
        json.dumps(content, indent=2) + "\n",
        encoding="utf-8",
    )

    return opencode_json_path
