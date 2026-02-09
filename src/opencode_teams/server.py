import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan

from opencode_teams import messaging, tasks, teams
from opencode_teams.models import (
    AgentHealthStatus,
    COLOR_PALETTE,
    InboxMessage,
    SendMessageResult,
    ShutdownApproved,
    SpawnResult,
    TeammateMember,
)
from opencode_teams.spawner import (
    check_process_alive,
    check_single_agent_health,
    cleanup_agent_config,
    discover_desktop_binary,
    discover_opencode_binary,
    is_tmux_available,
    is_windows,
    kill_desktop_process,
    kill_tmux_pane,
    launch_desktop_app,
    load_health_state,
    save_health_state,
    spawn_teammate,
    translate_model,
)


@lifespan
async def app_lifespan(server):
    import logging
    logger = logging.getLogger("opencode-teams")
    
    opencode_binary = None
    try:
        opencode_binary = discover_opencode_binary()
    except (FileNotFoundError, RuntimeError) as e:
        # Log but don't fail - the error will be reported when tools are called
        logger.warning(f"OpenCode binary not available: {e}")
    
    session_id = str(uuid.uuid4())
    yield {
        "opencode_binary": opencode_binary,
        "session_id": session_id,
        "active_team": None,
        "provider": "moonshot-ai"
    }


mcp = FastMCP(
    name="opencode-teams",
    instructions="""\
MCP server for orchestrating OpenCode agent teams.

CRITICAL: You MUST use `opencode-teams_*` MCP tools for ALL team coordination.
Do NOT use built-in Task/General Agent tools to spawn subagents.
Do NOT use built-in TodoWrite/TodoRead for task tracking.
Do NOT create your own coordination frameworks or agent patterns.

## Available Tools (prefixed `opencode-teams_` in OpenCode)

### Team Management
- `team_create(team_name, description)` — Create a new team. Always do this first.
- `team_delete(team_name)` — Delete a team (remove all members first).
- `read_config(team_name)` — Read team config and members.
- `server_status()` — Check MCP server health.

### Agent Spawning
- `spawn_teammate(team_name, name, prompt, instructions, model, backend)` — Spawn a new agent.
- `force_kill_teammate(team_name, agent_name)` — Force-stop an agent.
- `check_agent_health(team_name, agent_name)` — Check if agent is alive/dead/hung.
- `check_all_agents_health(team_name)` — Check health of all agents.

### Messaging
- `send_message(team_name, type, recipient, content, summary, sender)` — Send messages.
- `read_inbox(team_name, agent_name)` — Read an agent's inbox.
- `poll_inbox(team_name, agent_name, timeout_ms)` — Long-poll for new messages.

### Task Tracking
- `task_create(team_name, subject, description)` — Create a task.
- `task_update(team_name, task_id, status, owner, ...)` — Update a task.
- `task_list(team_name)` — List all tasks.
- `task_get(team_name, task_id)` — Get task details.

## Workflow
1. `team_create` — create the team
2. `task_create` — create tasks for the work
3. `spawn_teammate` — spawn agents with task-specific `instructions` tailored to the problem
4. `check_all_agents_health` + `read_inbox` — monitor progress
5. `send_message(type="shutdown_request")` — shut down agents when done
6. `team_delete` — clean up

Agent configs are generated dynamically per-spawn and purged on shutdown/kill.

IMPORTANT: These are MCP tools. Call them as tool invocations, not slash commands.""",
    lifespan=app_lifespan,
)


def _get_lifespan(ctx: Context) -> dict[str, Any]:
    return ctx.lifespan_context


@mcp.tool
def server_status(ctx: Context) -> dict:
    """Check MCP server health. Returns session info, active team, and server version.
    Use this tool to verify the MCP connection is working correctly."""
    ls = _get_lifespan(ctx)
    return {
        "status": "ok",
        "server": "opencode-teams",
        "session_id": ls.get("session_id", "unknown"),
        "active_team": ls.get("active_team"),
        "opencode_binary": ls.get("opencode_binary") or "not found",
        "provider": ls.get("provider", "unknown"),
    }


@mcp.tool
def team_create(
    team_name: str,
    ctx: Context,
    description: str = "",
) -> dict:
    """Create a new agent team. Sets up team config and task directories under ~/.opencode-teams/.
    One team per server session. Team names must be filesystem-safe
    (letters, numbers, hyphens, underscores)."""
    ls = _get_lifespan(ctx)
    if ls.get("active_team"):
        raise ToolError(f"Session already has active team: {ls['active_team']}. One team per session.")
    result = teams.create_team(
        name=team_name, session_id=ls["session_id"], description=description,
        project_dir=Path.cwd(),
    )
    ls["active_team"] = team_name
    return result.model_dump()


@mcp.tool
def team_delete(team_name: str, ctx: Context) -> dict:
    """Delete a team and all its data. Fails if any teammates are still active.
    Removes both team config and task directories."""
    try:
        result = teams.delete_team(team_name)
    except (RuntimeError, FileNotFoundError) as e:
        raise ToolError(str(e))
    _get_lifespan(ctx)["active_team"] = None
    return result.model_dump()


@mcp.tool(name="spawn_teammate")
def spawn_teammate_tool(
    team_name: str,
    name: str,
    prompt: str,
    ctx: Context,
    instructions: str = "",  # Task-specific system prompt instructions for this agent
    model: str = "sonnet",  # Accepts: "sonnet", "opus", "haiku", or "provider/model"
    plan_mode_required: bool = False,
    backend: str = "auto",  # "auto", "tmux", "windows_terminal", or "desktop"
) -> dict:
    """Spawn a new OpenCode teammate with dynamically generated configuration.

    Agent configs are created on spawn and purged on shutdown/kill.
    Use `instructions` to tailor the agent's role and behavior for the specific task.

    Backend options:
    - 'auto' (default): Uses tmux if available, windows_terminal on Windows, otherwise desktop app
    - 'tmux': Spawn in a tmux pane (requires tmux installed)
    - 'windows_terminal': Spawn in a new PowerShell window (Windows only)
    - 'desktop': Launch the OpenCode desktop app (GUI, requires manual interaction)

    All spawned agents connect to this MCP server via the project's opencode.json,
    enabling communication through file-based inboxes.

    The teammate receives its initial prompt via inbox and begins working
    autonomously. Names must be unique within the team."""
    ls = _get_lifespan(ctx)
    opencode_binary = ls.get("opencode_binary")
    if opencode_binary is None:
        raise ToolError(
            "OpenCode binary not found or version too old. "
            "Please ensure opencode CLI v1.1.52+ is installed and on PATH. "
            "Install with: npm install -g opencode@latest"
        )
    resolved_model = translate_model(model, provider=ls.get("provider", "moonshot-ai"))

    # Resolve backend: auto-detect best option
    effective_backend = backend
    if backend == "auto":
        if is_tmux_available():
            effective_backend = "tmux"
        elif is_windows():
            # On Windows without tmux, use windows_terminal (new PowerShell windows)
            effective_backend = "windows_terminal"
        else:
            # On non-Windows without tmux, fall back to desktop app
            effective_backend = "desktop"

    # Validate tmux availability before attempting spawn
    if effective_backend == "tmux" and not is_tmux_available():
        raise ToolError(
            "tmux is not available on this system. "
            "Either install tmux, use backend='windows_terminal' (Windows only), "
            "or use backend='desktop' to spawn via the OpenCode desktop app."
        )

    # Desktop binary discovery
    desktop_binary = None
    if effective_backend == "desktop":
        try:
            desktop_binary = discover_desktop_binary()
        except FileNotFoundError as e:
            raise ToolError(str(e))

    # Backfill project_dir on team config if not already set (pre-existing teams)
    try:
        config = teams.read_config(team_name)
        if config.project_dir is None:
            config.project_dir = str(Path.cwd())
            teams.write_config(team_name, config)
    except Exception:
        pass  # Best effort

    member = spawn_teammate(
        team_name=team_name,
        name=name,
        prompt=prompt,
        opencode_binary=opencode_binary,
        model=resolved_model,
        subagent_type="general-purpose",
        role_instructions="",  # No predefined templates; use dynamic instructions
        custom_instructions=instructions,
        backend_type=effective_backend,
        desktop_binary=desktop_binary,
        plan_mode_required=plan_mode_required,
        project_dir=Path.cwd(),
    )
    return SpawnResult(
        agent_id=member.agent_id,
        name=member.name,
        team_name=team_name,
    ).model_dump()


@mcp.tool
def send_message(
    team_name: str,
    type: Literal["message", "broadcast", "shutdown_request", "shutdown_response", "plan_approval_response"],
    recipient: str = "",
    content: str = "",
    summary: str = "",
    request_id: str = "",
    approve: bool | None = None,
    sender: str = "team-lead",
) -> dict:
    """Send a message to a teammate or respond to a protocol request.
    Type 'message' sends a direct message (requires recipient, summary).
    Type 'broadcast' sends to all teammates (requires summary).
    Type 'shutdown_request' asks a teammate to shut down (requires recipient; content used as reason).
    Type 'shutdown_response' responds to a shutdown request (requires sender, request_id, approve).
    Type 'plan_approval_response' responds to a plan approval request (requires recipient, request_id, approve)."""

    if type == "message":
        if not content:
            raise ToolError("Message content must not be empty")
        if not summary:
            raise ToolError("Message summary must not be empty")
        if not recipient:
            raise ToolError("Message recipient must not be empty")
        config = teams.read_config(team_name)
        member_names = {m.name for m in config.members}
        if recipient not in member_names:
            raise ToolError(f"Recipient {recipient!r} is not a member of team {team_name!r}")
        target_color = None
        for m in config.members:
            if m.name == recipient and isinstance(m, TeammateMember):
                target_color = m.color
                break
        messaging.send_plain_message(
            team_name, sender, recipient, content, summary=summary, color=target_color,
        )
        return SendMessageResult(
            success=True,
            message=f"Message sent to {recipient}",
            routing={
                "sender": sender,
                "target": recipient,
                "targetColor": target_color,
                "summary": summary,
                "content": content,
            },
        ).model_dump(exclude_none=True)

    elif type == "broadcast":
        if not summary:
            raise ToolError("Broadcast summary must not be empty")
        config = teams.read_config(team_name)
        count = 0
        for m in config.members:
            if isinstance(m, TeammateMember):
                messaging.send_plain_message(
                    team_name, "team-lead", m.name, content, summary=summary, color=None,
                )
                count += 1
        return SendMessageResult(
            success=True,
            message=f"Broadcast sent to {count} teammate(s)",
        ).model_dump(exclude_none=True)

    elif type == "shutdown_request":
        if not recipient:
            raise ToolError("Shutdown request recipient must not be empty")
        if recipient == "team-lead":
            raise ToolError("Cannot send shutdown request to team-lead")
        config = teams.read_config(team_name)
        member_names = {m.name for m in config.members}
        if recipient not in member_names:
            raise ToolError(f"Recipient {recipient!r} is not a member of team {team_name!r}")
        req_id = messaging.send_shutdown_request(team_name, recipient, reason=content)
        return SendMessageResult(
            success=True,
            message=f"Shutdown request sent to {recipient}",
            request_id=req_id,
            target=recipient,
        ).model_dump(exclude_none=True)

    elif type == "shutdown_response":
        if approve:
            config = teams.read_config(team_name)
            member = None
            for m in config.members:
                if isinstance(m, TeammateMember) and m.name == sender:
                    member = m
                    break
            pane_id = member.tmux_pane_id if member else ""
            backend = member.backend_type if member else "tmux"
            payload = ShutdownApproved(
                request_id=request_id,
                from_=sender,
                timestamp=messaging.now_iso(),
                pane_id=pane_id,
                backend_type=backend,
            )
            messaging.send_structured_message(team_name, sender, "team-lead", payload)
            return SendMessageResult(
                success=True,
                message=f"Shutdown approved for request {request_id}",
            ).model_dump(exclude_none=True)
        else:
            messaging.send_plain_message(
                team_name, sender, "team-lead",
                content or "Shutdown rejected",
                summary="shutdown_rejected",
            )
            return SendMessageResult(
                success=True,
                message=f"Shutdown rejected for request {request_id}",
            ).model_dump(exclude_none=True)

    elif type == "plan_approval_response":
        if not recipient:
            raise ToolError("Plan approval recipient must not be empty")
        config = teams.read_config(team_name)
        member_names = {m.name for m in config.members}
        if recipient not in member_names:
            raise ToolError(f"Recipient {recipient!r} is not a member of team {team_name!r}")
        if approve:
            messaging.send_plain_message(
                team_name, sender, recipient,
                '{"type":"plan_approval","approved":true}',
                summary="plan_approved",
            )
        else:
            messaging.send_plain_message(
                team_name, sender, recipient,
                content or "Plan rejected",
                summary="plan_rejected",
            )
        return SendMessageResult(
            success=True,
            message=f"Plan {'approved' if approve else 'rejected'} for {recipient}",
        ).model_dump(exclude_none=True)

    raise ToolError(f"Unknown message type: {type}")


@mcp.tool
def task_create(
    team_name: str,
    subject: str,
    description: str,
    active_form: str = "",
    metadata: dict | None = None,
) -> dict:
    """Create a new task for the team. Tasks are auto-assigned incrementing IDs.
    Optional metadata dict is stored alongside the task."""
    try:
        task = tasks.create_task(team_name, subject, description, active_form, metadata)
    except ValueError as e:
        raise ToolError(str(e))
    return task.model_dump(by_alias=True, exclude_none=True)


@mcp.tool
def task_update(
    team_name: str,
    task_id: str,
    status: Literal["pending", "in_progress", "completed", "deleted"] | None = None,
    owner: str | None = None,
    subject: str | None = None,
    description: str | None = None,
    active_form: str | None = None,
    add_blocks: list[str] | None = None,
    add_blocked_by: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Update a task's fields. Setting owner auto-notifies the assignee via
    inbox. Setting status to 'deleted' removes the task file from disk.
    Metadata keys are merged into existing metadata (set a key to null to delete it)."""
    try:
        task = tasks.update_task(
            team_name, task_id,
            status=status, owner=owner, subject=subject, description=description,
            active_form=active_form, add_blocks=add_blocks, add_blocked_by=add_blocked_by,
            metadata=metadata,
        )
    except FileNotFoundError:
        raise ToolError(f"Task {task_id!r} not found in team {team_name!r}")
    except ValueError as e:
        raise ToolError(str(e))
    if owner is not None and task.owner is not None and task.status != "deleted":
        messaging.send_task_assignment(team_name, task, assigned_by="team-lead")
    return task.model_dump(by_alias=True, exclude_none=True)


@mcp.tool
def task_list(team_name: str) -> list[dict]:
    """List all tasks for a team with their current status and assignments."""
    try:
        result = tasks.list_tasks(team_name)
    except ValueError as e:
        raise ToolError(str(e))
    return [t.model_dump(by_alias=True, exclude_none=True) for t in result]


@mcp.tool
def task_get(team_name: str, task_id: str) -> dict:
    """Get full details of a specific task by ID."""
    try:
        task = tasks.get_task(team_name, task_id)
    except FileNotFoundError:
        raise ToolError(f"Task {task_id!r} not found in team {team_name!r}")
    return task.model_dump(by_alias=True, exclude_none=True)


@mcp.tool
def read_inbox(
    team_name: str,
    agent_name: str,
    unread_only: bool = False,
    mark_as_read: bool = True,
) -> list[dict]:
    """Read messages from an agent's inbox. Returns all messages by default.
    Set unread_only=True to get only unprocessed messages."""
    msgs = messaging.read_inbox(team_name, agent_name, unread_only=unread_only, mark_as_read=mark_as_read)
    return [m.model_dump(by_alias=True, exclude_none=True) for m in msgs]


@mcp.tool
def read_config(team_name: str) -> dict:
    """Read the current team configuration including all members."""
    try:
        config = teams.read_config(team_name)
    except FileNotFoundError:
        raise ToolError(f"Team {team_name!r} not found")
    return config.model_dump(by_alias=True)


@mcp.tool
def force_kill_teammate(team_name: str, agent_name: str) -> dict:
    """Forcibly kill a teammate. For tmux backend, kills the tmux pane.
    For desktop backend, terminates the desktop process. Removes member
    from config and resets their tasks."""
    config = teams.read_config(team_name)
    member = None
    for m in config.members:
        if isinstance(m, TeammateMember) and m.name == agent_name:
            member = m
            break
    if member is None:
        raise ToolError(f"Teammate {agent_name!r} not found in team {team_name!r}")

    if member.backend_type == "desktop":
        if member.process_id:
            kill_desktop_process(member.process_id)
    else:
        if member.tmux_pane_id:
            kill_tmux_pane(member.tmux_pane_id)

    project_dir = teams.get_project_dir(team_name)
    teams.remove_member(team_name, agent_name)
    tasks.reset_owner_tasks(team_name, agent_name)
    cleanup_agent_config(project_dir, agent_name)
    return {"success": True, "message": f"{agent_name} has been stopped."}


@mcp.tool
async def poll_inbox(
    team_name: str,
    agent_name: str,
    timeout_ms: int = 30000,
) -> list[dict]:
    """Poll an agent's inbox for new unread messages, waiting up to timeout_ms.
    Returns unread messages and marks them as read. Convenience tool for MCP
    clients that cannot watch the filesystem."""
    msgs = messaging.read_inbox(team_name, agent_name, unread_only=True, mark_as_read=True)
    if msgs:
        return [m.model_dump(by_alias=True, exclude_none=True) for m in msgs]
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        msgs = messaging.read_inbox(team_name, agent_name, unread_only=True, mark_as_read=True)
        if msgs:
            return [m.model_dump(by_alias=True, exclude_none=True) for m in msgs]
    return []


@mcp.tool
def process_shutdown_approved(team_name: str, agent_name: str) -> dict:
    """Process a teammate's shutdown by removing them from config and resetting
    their tasks. Call this after confirming shutdown_approved in the lead inbox."""
    if agent_name == "team-lead":
        raise ToolError("Cannot process shutdown for team-lead")
    project_dir = teams.get_project_dir(team_name)
    teams.remove_member(team_name, agent_name)
    tasks.reset_owner_tasks(team_name, agent_name)
    cleanup_agent_config(project_dir, agent_name)
    return {"success": True, "message": f"{agent_name} removed from team."}


@mcp.tool
def check_agent_health(
    team_name: str,
    agent_name: str,
) -> dict:
    """Check health status of a specific agent. Returns status: 'alive', 'dead',
    'hung', or 'unknown'. Dead means the tmux pane no longer exists. Hung means
    the pane is alive but has produced no new output for over 120 seconds.
    Use force_kill_teammate to kill dead or hung agents."""
    config = teams.read_config(team_name)
    member = None
    for m in config.members:
        if isinstance(m, TeammateMember) and m.name == agent_name:
            member = m
            break
    if member is None:
        raise ToolError(f"Agent {agent_name!r} not found in team {team_name!r}")

    # Load previous health state for hung detection
    health_state = load_health_state(team_name)
    agent_state = health_state.get(agent_name, {})
    previous_hash = agent_state.get("hash")
    last_change_time = agent_state.get("last_change_time")

    result = check_single_agent_health(
        member,
        previous_hash=previous_hash,
        last_change_time=last_change_time,
    )

    # Update health state
    if result.last_content_hash is not None:
        if result.last_content_hash != previous_hash:
            health_state[agent_name] = {
                "hash": result.last_content_hash,
                "last_change_time": time.time(),
            }
        elif agent_name not in health_state:
            health_state[agent_name] = {
                "hash": result.last_content_hash,
                "last_change_time": time.time(),
            }
    save_health_state(team_name, health_state)

    return result.model_dump(by_alias=True, exclude_none=True)


@mcp.tool
def check_all_agents_health(
    team_name: str,
) -> list[dict]:
    """Check health of all teammates in the team. Returns a list of health
    status objects. Each includes agentName, paneId, status, and detail.
    Useful for monitoring team health. Automatically persists health state
    for hung detection across calls."""
    config = teams.read_config(team_name)
    health_state = load_health_state(team_name)
    results = []

    for m in config.members:
        if not isinstance(m, TeammateMember):
            continue
        agent_state = health_state.get(m.name, {})
        previous_hash = agent_state.get("hash")
        last_change_time = agent_state.get("last_change_time")

        status = check_single_agent_health(
            m,
            previous_hash=previous_hash,
            last_change_time=last_change_time,
        )

        # Update health state for this agent
        if status.last_content_hash is not None:
            if status.last_content_hash != previous_hash:
                health_state[m.name] = {
                    "hash": status.last_content_hash,
                    "last_change_time": time.time(),
                }
            elif m.name not in health_state:
                health_state[m.name] = {
                    "hash": status.last_content_hash,
                    "last_change_time": time.time(),
                }

        results.append(status.model_dump(by_alias=True, exclude_none=True))

    save_health_state(team_name, health_state)
    return results


def main():
    mcp.run()


if __name__ == "__main__":
    main()
