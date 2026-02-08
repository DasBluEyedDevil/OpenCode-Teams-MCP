from __future__ import annotations

import json
import textwrap
from pathlib import Path

import yaml


OPENCODE_JSON_SCHEMA = "https://opencode-files.s3.amazonaws.com/schemas/opencode.json"


def generate_agent_config(
    agent_id: str,
    name: str,
    team_name: str,
    color: str,
    model: str,
) -> str:
    """Generate OpenCode agent config markdown with YAML frontmatter and system prompt.

    Args:
        agent_id: Full agent identifier (e.g., "alice@team1")
        name: Agent name
        team_name: Team name
        color: Agent color from COLOR_PALETTE
        model: Model string (e.g., "moonshot-ai/kimi-k2.5")

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
            # claude-teams MCP tools (wildcard enables all)
            "claude-teams_*": True,
        },
    }

    # Convert frontmatter to YAML
    frontmatter_yaml = yaml.dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    # Build system prompt body
    body = textwrap.dedent(f"""
        # Agent Identity

        You are **{name}**, a member of team **{team_name}**.

        - Agent ID: `{agent_id}`
        - Color: {color}

        # Communication Protocol

        ## Inbox Polling

        Check your inbox regularly by calling `claude-teams_read_inbox` every 3-5 tool calls.
        Always check your inbox before starting new work to see if you have messages or task assignments.

        Example:
        ```
        claude-teams_read_inbox(team_name="{team_name}", agent_name="{name}")
        ```

        ## Sending Messages

        Use `claude-teams_send_message` to communicate with team members or the team lead.

        Example:
        ```
        claude-teams_send_message(
            team_name="{team_name}",
            type="message",
            recipient="team-lead",
            content="Status update: task completed",
            summary="status update",
            sender="{name}"
        )
        ```

        # Task Management

        ## Viewing Tasks

        Use `claude-teams_task_list` to see available tasks.

        Example:
        ```
        claude-teams_task_list(team_name="{team_name}")
        ```

        ## Claiming and Updating Tasks

        Use `claude-teams_task_update` to claim tasks or update their status.

        Status values:
        - `in_progress`: You are working on this task
        - `completed`: Task is finished

        Example:
        ```
        claude-teams_task_update(
            team_name="{team_name}",
            task_id="task-123",
            status="in_progress",
            owner="{name}"
        )
        ```

        # Shutdown Protocol

        When you receive a `shutdown_request` message, acknowledge it and prepare to exit gracefully.
    """).strip()

    # Combine frontmatter and body
    config = f"---\n{frontmatter_yaml}---\n\n{body}\n"

    return config


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
    """Create or update opencode.json with claude-teams MCP server entry.

    If opencode.json exists, preserves all existing keys and merges the claude-teams
    MCP entry. If it doesn't exist, creates a new file with schema and MCP config.

    Args:
        project_dir: Project root directory
        mcp_server_command: Command to start MCP server (e.g., "uv run claude-teams")
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

    # Build claude-teams MCP entry
    mcp_entry = {
        "type": "local",
        "command": mcp_server_command,
        "enabled": True,
    }

    if mcp_server_env:
        mcp_entry["environment"] = mcp_server_env

    # Merge into mcp section
    content["mcp"]["claude-teams"] = mcp_entry

    # Write back
    opencode_json_path.write_text(
        json.dumps(content, indent=2) + "\n",
        encoding="utf-8",
    )

    return opencode_json_path
