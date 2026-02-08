"""Integration tests for single-agent MCP tool access.

Validates that every MCP tool callable by a spawned agent works correctly
from the agent's perspective (MCP-02 requirement).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastmcp import Client

from claude_teams import messaging, tasks, teams
from claude_teams.models import TeammateMember
from claude_teams.server import mcp


def _make_teammate(name: str, team_name: str, pane_id: str = "%1") -> TeammateMember:
    return TeammateMember(
        agent_id=f"{name}@{team_name}",
        name=name,
        agent_type="teammate",
        model="moonshot-ai/kimi-k2.5",
        prompt="Do stuff",
        color="blue",
        plan_mode_required=False,
        joined_at=int(time.time() * 1000),
        tmux_pane_id=pane_id,
        cwd="/tmp",
    )


@pytest.fixture
async def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(teams, "TEAMS_DIR", tmp_path / "teams")
    monkeypatch.setattr(teams, "TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(tasks, "TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(messaging, "TEAMS_DIR", tmp_path / "teams")
    monkeypatch.setattr(
        "claude_teams.server.discover_opencode_binary", lambda: "/usr/bin/echo"
    )
    (tmp_path / "teams").mkdir()
    (tmp_path / "tasks").mkdir()
    async with Client(mcp) as c:
        yield c


def _data(result):
    """Extract raw Python data from a successful CallToolResult."""
    if result.content:
        return json.loads(result.content[0].text)
    return result.data


class TestSingleAgentToolAccess:
    """Validates each MCP tool from a spawned agent's perspective."""

    async def test_agent_inbox_starts_empty(self, client: Client):
        """An agent's inbox is empty before any messages are sent."""
        await client.call_tool("team_create", {"team_name": "t_empty"})
        teams.add_member("t_empty", _make_teammate("alice", "t_empty"))

        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t_empty", "agent_name": "alice"}
            )
        )
        assert inbox == []

    async def test_agent_can_read_own_inbox(self, client: Client):
        """Agent reads inbox and sees message sent to it with correct from/text."""
        await client.call_tool("team_create", {"team_name": "t_read"})
        teams.add_member("t_read", _make_teammate("alice", "t_read"))

        # Team lead sends a message to alice
        await client.call_tool(
            "send_message",
            {
                "team_name": "t_read",
                "type": "message",
                "recipient": "alice",
                "content": "Please start task A",
                "summary": "task assignment",
            },
        )

        # Alice reads her inbox
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t_read", "agent_name": "alice"}
            )
        )
        assert len(inbox) == 1
        assert inbox[0]["from"] == "team-lead"
        assert inbox[0]["text"] == "Please start task A"

    async def test_agent_can_send_message_to_teammate(self, client: Client):
        """Agent sends a message with sender=<name> and recipient sees from=<name>."""
        await client.call_tool("team_create", {"team_name": "t_send"})
        teams.add_member("t_send", _make_teammate("alice", "t_send"))
        teams.add_member("t_send", _make_teammate("bob", "t_send"))

        # Alice sends a message to bob with explicit sender
        result = _data(
            await client.call_tool(
                "send_message",
                {
                    "team_name": "t_send",
                    "type": "message",
                    "recipient": "bob",
                    "content": "hello from alice",
                    "summary": "greeting",
                    "sender": "alice",
                },
            )
        )
        assert result["success"] is True

        # Bob reads his inbox and sees the message from alice
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t_send", "agent_name": "bob"}
            )
        )
        assert len(inbox) == 1
        assert inbox[0]["from"] == "alice"
        assert inbox[0]["text"] == "hello from alice"

    async def test_agent_can_create_task(self, client: Client):
        """Agent can create a task and receives id and subject in response."""
        await client.call_tool("team_create", {"team_name": "t_taskcreate"})

        result = _data(
            await client.call_tool(
                "task_create",
                {
                    "team_name": "t_taskcreate",
                    "subject": "test task",
                    "description": "do something important",
                },
            )
        )
        assert "id" in result
        assert result["subject"] == "test task"

    async def test_agent_can_update_task_status(self, client: Client):
        """Agent can update a task's status to in_progress."""
        await client.call_tool("team_create", {"team_name": "t_taskstatus"})

        created = _data(
            await client.call_tool(
                "task_create",
                {
                    "team_name": "t_taskstatus",
                    "subject": "status task",
                    "description": "will update status",
                },
            )
        )

        updated = _data(
            await client.call_tool(
                "task_update",
                {
                    "team_name": "t_taskstatus",
                    "task_id": created["id"],
                    "status": "in_progress",
                },
            )
        )
        assert updated["status"] == "in_progress"

    async def test_agent_can_claim_task_via_owner(self, client: Client):
        """Agent claims a task by setting owner, and receives task_assignment in inbox."""
        await client.call_tool("team_create", {"team_name": "t_claim"})
        teams.add_member("t_claim", _make_teammate("alice", "t_claim"))

        created = _data(
            await client.call_tool(
                "task_create",
                {
                    "team_name": "t_claim",
                    "subject": "claimed task",
                    "description": "alice will own this",
                },
            )
        )

        updated = _data(
            await client.call_tool(
                "task_update",
                {
                    "team_name": "t_claim",
                    "task_id": created["id"],
                    "owner": "alice",
                },
            )
        )
        assert updated["owner"] == "alice"

        # Alice should have a task_assignment message in her inbox
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t_claim", "agent_name": "alice"}
            )
        )
        assert len(inbox) == 1
        payload = json.loads(inbox[0]["text"])
        assert payload["type"] == "task_assignment"
        assert payload["taskId"] == created["id"]

    async def test_agent_can_list_tasks(self, client: Client):
        """Agent can list all tasks and sees the correct count."""
        await client.call_tool("team_create", {"team_name": "t_tasklist"})

        await client.call_tool(
            "task_create",
            {
                "team_name": "t_tasklist",
                "subject": "task one",
                "description": "first",
            },
        )
        await client.call_tool(
            "task_create",
            {
                "team_name": "t_tasklist",
                "subject": "task two",
                "description": "second",
            },
        )

        result = _data(
            await client.call_tool("task_list", {"team_name": "t_tasklist"})
        )
        assert len(result) == 2
        subjects = {t["subject"] for t in result}
        assert subjects == {"task one", "task two"}

    async def test_agent_can_get_task_by_id(self, client: Client):
        """Agent can retrieve a specific task by its ID."""
        await client.call_tool("team_create", {"team_name": "t_taskget"})

        created = _data(
            await client.call_tool(
                "task_create",
                {
                    "team_name": "t_taskget",
                    "subject": "specific task",
                    "description": "fetch this one",
                },
            )
        )

        fetched = _data(
            await client.call_tool(
                "task_get",
                {
                    "team_name": "t_taskget",
                    "task_id": created["id"],
                },
            )
        )
        assert fetched["id"] == created["id"]
        assert fetched["subject"] == "specific task"
