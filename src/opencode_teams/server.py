import asyncio
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan

from opencode_teams import messaging, tasks, teams
from opencode_teams.model_discovery import discover_models, resolve_model_string
from opencode_teams.task_analysis import infer_model_preference
from opencode_teams.models import (
    AgentHealthStatus,
    COLOR_PALETTE,
    InboxMessage,
    ModelPreference,
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
)


@lifespan
async def app_lifespan(server):
    import logging
    logger = logging.getLogger("opencode-teams")

    _log_activity("SERVER STARTING - lifespan begin")

    opencode_binary = None
    try:
        opencode_binary = discover_opencode_binary()
        _log_activity(f"OpenCode binary found: {opencode_binary}")
    except (FileNotFoundError, RuntimeError) as e:
        # Log but don't fail - the error will be reported when tools are called
        logger.warning(f"OpenCode binary not available: {e}")
        _log_activity(f"OpenCode binary not found: {e}")

    # Discover available models from OpenCode config
    available_models = discover_models()
    if not available_models:
        logger.warning(
            "No models found in OpenCode config. "
            "Configure providers in ~/.config/opencode/opencode.json"
        )
        _log_activity("No models found in OpenCode config")
    else:
        _log_activity(f"Discovered {len(available_models)} models")

    session_id = str(uuid.uuid4())
    _log_activity(f"SERVER READY - session_id={session_id}")
    try:
        yield {
            "opencode_binary": opencode_binary,
            "session_id": session_id,
            "active_team": None,
            "available_models": available_models,
        }
    finally:
        _log_activity("SERVER SHUTTING DOWN - lifespan end")


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

### Model Discovery
- `list_available_models(provider?, reasoning_effort?)` — List available models from OpenCode config.

### Agent Spawning
- `spawn_teammate(team_name, name, prompt, instructions, model, reasoning_effort, prefer_speed, backend)` — Spawn agent.
  - `model="auto"` (default): Selects best model based on preferences.
  - `reasoning_effort`: "none", "low", "medium", "high", "xhigh" — guides auto-selection.
  - `prefer_speed=True`: Prefer faster models over more capable ones.
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
1. `list_available_models` — (optional) see what models are configured
2. `team_create` — create the team
3. `task_create` — create tasks for the work
4. `spawn_teammate` — spawn agents with task-specific `instructions` tailored to the problem
5. `check_all_agents_health` + `read_inbox` — monitor progress
6. `send_message(type="shutdown_request")` — shut down agents when done
7. `team_delete` — clean up

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
    models = ls.get("available_models", [])
    return {
        "status": "ok",
        "server": "opencode-teams",
        "session_id": ls.get("session_id", "unknown"),
        "active_team": ls.get("active_team"),
        "opencode_binary": ls.get("opencode_binary") or "not found",
        "available_models_count": len(models),
    }


@mcp.tool
def list_available_models(
    ctx: Context,
    provider: str | None = None,
    reasoning_effort: str | None = None,
) -> list[dict]:
    """List all available models from OpenCode configuration.

    Models are discovered from ~/.config/opencode/opencode.json and project opencode.json.
    Use this to see what models can be used with spawn_teammate.

    Args:
        provider: Optional filter by provider (e.g., "openai", "google").
        reasoning_effort: Optional filter by reasoning level ("none", "low", "medium", "high", "xhigh").

    Returns:
        List of model info dicts with provider, modelId, name, contextWindow, etc.
    """
    ls = _get_lifespan(ctx)
    models = ls.get("available_models", [])

    # Apply filters
    filtered = models
    if provider:
        filtered = [m for m in filtered if m.provider == provider]
    if reasoning_effort:
        filtered = [m for m in filtered if m.reasoning_effort == reasoning_effort]

    return [m.model_dump(by_alias=True) for m in filtered]


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
    model: str = "auto",  # "auto", model_id, or full "provider/model" string
    reasoning_effort: str | None = None,  # Preference: "none", "low", "medium", "high", "xhigh"
    prefer_speed: bool = False,  # Prefer faster models over more capable ones
    plan_mode_required: bool = False,
    backend: str = "auto",  # "auto", "tmux", "windows_terminal", or "desktop"
) -> dict:
    """Spawn a new OpenCode teammate with dynamically generated configuration.

    Model selection:
    - 'auto' (default): Automatically selects best available model based on preferences.
    - model_id: Use a specific model (e.g., "gpt-5.2-medium", "gemini-3-flash").
    - provider/model: Full model string (e.g., "openai/gpt-5.2-high").

    Use `reasoning_effort` and `prefer_speed` to guide automatic model selection.

    Backend options:
    - 'auto' (default): Uses tmux if available, windows_terminal on Windows, otherwise desktop app
    - 'tmux': Spawn in a tmux pane (requires tmux installed)
    - 'windows_terminal': Spawn in a new PowerShell window (Windows only)
    - 'desktop': Launch the OpenCode desktop app (GUI, requires manual interaction)

    Agent configs are created on spawn and purged on shutdown/kill.
    Use `instructions` to tailor the agent's role and behavior for the specific task.

    The teammate receives its initial prompt via inbox and begins working
    autonomously. Names must be unique within the team."""
    _log_activity(f"TOOL CALL: spawn_teammate team={team_name} name={name} model={model}")
    ls = _get_lifespan(ctx)
    opencode_binary = ls.get("opencode_binary")
    if opencode_binary is None:
        raise ToolError(
            "OpenCode binary not found or version too old. "
            "Please ensure opencode CLI v1.1.52+ is installed and on PATH. "
            "Install with: npm install -g opencode@latest"
        )

    # Build preference for model selection
    # Infer from prompt; explicit params override inferred values
    explicit_pref = None
    if reasoning_effort or prefer_speed:
        explicit_pref = ModelPreference(
            reasoning_effort=reasoning_effort,
            prefer_speed=prefer_speed,
        )
    preference = infer_model_preference(prompt, explicit=explicit_pref)
    available_models = ls.get("available_models", [])

    try:
        resolved_model = resolve_model_string(model, available_models, preference)
    except ValueError as e:
        raise ToolError(str(e))

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
    _log_activity(f"TOOL DONE: spawn_teammate agent_id={member.agent_id}")
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


def _get_log_dir() -> Path:
    """Get path to log directory."""
    log_dir = Path.home() / ".opencode-teams" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _get_crash_log_path() -> Path:
    """Get path to crash log file."""
    return _get_log_dir() / "crash.log"


def _get_activity_log_path() -> Path:
    """Get path to activity log file."""
    return _get_log_dir() / "activity.log"


def _log_activity(message: str):
    """Log MCP activity for debugging disconnects."""
    log_path = _get_activity_log_path()
    timestamp = datetime.now().isoformat()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def _log_crash(exc_type, exc_value, exc_tb):
    """Log unhandled exceptions to crash.log for debugging MCP disconnects."""
    log_path = _get_crash_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"CRASH at {datetime.now().isoformat()}\n")
        f.write(f"{'='*60}\n")
        traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        f.write("\n")


def _handle_async_exception(loop, context):
    """Handle exceptions in async tasks that would otherwise be silently dropped."""
    log_path = _get_crash_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"ASYNC EXCEPTION at {datetime.now().isoformat()}\n")
        f.write(f"{'='*60}\n")
        f.write(f"Message: {context.get('message', 'No message')}\n")
        if "exception" in context:
            f.write("Exception:\n")
            traceback.print_exception(
                type(context["exception"]),
                context["exception"],
                context["exception"].__traceback__,
                file=f,
            )
        f.write(f"Context: {context}\n\n")


def main():
    # Install crash handlers for debugging MCP disconnects
    sys.excepthook = _log_crash

    # Also catch unhandled exceptions in asyncio tasks
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(_handle_async_exception)
    asyncio.set_event_loop(loop)

    mcp.run()


if __name__ == "__main__":
    main()
