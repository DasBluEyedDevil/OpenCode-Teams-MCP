from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from pathlib import Path

from claude_teams import messaging, teams
from claude_teams.models import COLOR_PALETTE, InboxMessage, TeammateMember


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


def spawn_teammate(
    team_name: str,
    name: str,
    prompt: str,
    claude_binary: str,
    lead_session_id: str,
    *,
    model: str = "sonnet",
    subagent_type: str = "general-purpose",
    cwd: str | None = None,
    plan_mode_required: bool = False,
    base_dir: Path | None = None,
) -> TeammateMember:
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

    cmd = build_spawn_command(member, claude_binary, lead_session_id)
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
