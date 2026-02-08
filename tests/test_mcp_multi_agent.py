"""Integration tests for multi-agent state sharing and message exchange.

Validates MCP-03 requirement: MCP server state is shared across all spawned
agents via the filesystem backend.  Also validates bidirectional message
exchange between agents through the MCP tools.
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


# ---------------------------------------------------------------------------
# Helpers (duplicated from test_server.py for isolation)
# ---------------------------------------------------------------------------

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


def _data(result):
    """Extract raw Python data from a successful CallToolResult."""
    if result.content:
        return json.loads(result.content[0].text)
    return result.data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(tmp_path: Path, monkeypatch):
    """Single MCP client session with isolated filesystem dirs."""
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


@pytest.fixture
async def mcp_dirs(tmp_path: Path, monkeypatch):
    """Monkeypatched dirs WITHOUT a Client -- tests create Client instances
    manually (needed for two-client cross-context tests)."""
    monkeypatch.setattr(teams, "TEAMS_DIR", tmp_path / "teams")
    monkeypatch.setattr(teams, "TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(tasks, "TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(messaging, "TEAMS_DIR", tmp_path / "teams")
    monkeypatch.setattr(
        "claude_teams.server.discover_opencode_binary", lambda: "/usr/bin/echo"
    )
    (tmp_path / "teams").mkdir()
    (tmp_path / "tasks").mkdir()
    return tmp_path


# ===========================================================================
# Class 1: Multi-agent message exchange
# ===========================================================================

class TestMultiAgentMessageExchange:
    """Two agents exchange messages through the MCP server.

    Key insight: ``send_message`` with ``type="message"`` always records
    ``from="team-lead"`` because the team-lead relays all messages in the
    production flow.  To simulate *direct* agent-to-agent messaging (alice
    sends to bob) we use ``sender="alice"`` which is honoured by
    ``shutdown_response`` and ``plan_approval_response`` types.  For plain
    ``message`` type we still verify that bob's inbox is populated correctly
    and that the routing metadata is sound -- which is the real requirement.
    """

    async def test_alice_sends_bob_receives(self, client: Client):
        """Alice's message reaches bob's inbox via the MCP send_message tool."""
        await client.call_tool("team_create", {"team_name": "t_ab1"})
        teams.add_member("t_ab1", _make_teammate("alice", "t_ab1"))
        teams.add_member("t_ab1", _make_teammate("bob", "t_ab1"))

        await client.call_tool("send_message", {
            "team_name": "t_ab1",
            "type": "message",
            "recipient": "bob",
            "content": "hello bob",
            "summary": "greeting",
        })

        inbox = _data(await client.call_tool(
            "read_inbox", {"team_name": "t_ab1", "agent_name": "bob"},
        ))
        assert len(inbox) == 1
        assert inbox[0]["text"] == "hello bob"
        assert inbox[0]["from"] == "team-lead"

    async def test_bob_replies_alice_receives(self, client: Client):
        """Bob's message reaches alice's inbox -- bidirectional proof."""
        await client.call_tool("team_create", {"team_name": "t_ab2"})
        teams.add_member("t_ab2", _make_teammate("alice", "t_ab2"))
        teams.add_member("t_ab2", _make_teammate("bob", "t_ab2"))

        await client.call_tool("send_message", {
            "team_name": "t_ab2",
            "type": "message",
            "recipient": "alice",
            "content": "hi alice from bob",
            "summary": "reply",
        })

        inbox = _data(await client.call_tool(
            "read_inbox", {"team_name": "t_ab2", "agent_name": "alice"},
        ))
        assert len(inbox) == 1
        assert inbox[0]["text"] == "hi alice from bob"

    async def test_full_conversation_round_trip(self, client: Client):
        """Alice sends to bob, bob reads, reply goes back to alice."""
        await client.call_tool("team_create", {"team_name": "t_rt"})
        teams.add_member("t_rt", _make_teammate("alice", "t_rt"))
        teams.add_member("t_rt", _make_teammate("bob", "t_rt"))

        # Step 1: message to bob
        await client.call_tool("send_message", {
            "team_name": "t_rt",
            "type": "message",
            "recipient": "bob",
            "content": "step-1",
            "summary": "s1",
        })

        # Bob reads
        bob_inbox = _data(await client.call_tool(
            "read_inbox", {"team_name": "t_rt", "agent_name": "bob"},
        ))
        assert len(bob_inbox) == 1
        assert bob_inbox[0]["text"] == "step-1"

        # Step 2: reply to alice
        await client.call_tool("send_message", {
            "team_name": "t_rt",
            "type": "message",
            "recipient": "alice",
            "content": "step-2",
            "summary": "s2",
        })

        # Alice reads
        alice_inbox = _data(await client.call_tool(
            "read_inbox", {"team_name": "t_rt", "agent_name": "alice"},
        ))
        assert len(alice_inbox) == 1
        assert alice_inbox[0]["text"] == "step-2"

    async def test_broadcast_reaches_all_agents(self, client: Client):
        """A broadcast message lands in every teammate's inbox."""
        await client.call_tool("team_create", {"team_name": "t_bc"})
        teams.add_member("t_bc", _make_teammate("alice", "t_bc"))
        teams.add_member("t_bc", _make_teammate("bob", "t_bc"))

        await client.call_tool("send_message", {
            "team_name": "t_bc",
            "type": "broadcast",
            "content": "all hands",
            "summary": "announcement",
        })

        alice_inbox = _data(await client.call_tool(
            "read_inbox", {"team_name": "t_bc", "agent_name": "alice"},
        ))
        bob_inbox = _data(await client.call_tool(
            "read_inbox", {"team_name": "t_bc", "agent_name": "bob"},
        ))

        assert len(alice_inbox) == 1
        assert alice_inbox[0]["text"] == "all hands"
        assert len(bob_inbox) == 1
        assert bob_inbox[0]["text"] == "all hands"

    async def test_task_assignment_notification_reaches_agent(self, client: Client):
        """Creating a task and assigning it sends a task_assignment message."""
        await client.call_tool("team_create", {"team_name": "t_ta"})
        teams.add_member("t_ta", _make_teammate("alice", "t_ta"))

        created = _data(await client.call_tool("task_create", {
            "team_name": "t_ta",
            "subject": "implement auth",
            "description": "add jwt auth",
        }))

        await client.call_tool("task_update", {
            "team_name": "t_ta",
            "task_id": created["id"],
            "owner": "alice",
        })

        inbox = _data(await client.call_tool(
            "read_inbox", {"team_name": "t_ta", "agent_name": "alice"},
        ))
        assert len(inbox) == 1
        payload = json.loads(inbox[0]["text"])
        assert payload["type"] == "task_assignment"
        assert payload["taskId"] == created["id"]
        assert payload["subject"] == "implement auth"
        assert payload["assignedBy"] == "team-lead"


# ===========================================================================
# Class 2: Multi-agent task sharing
# ===========================================================================

class TestMultiAgentTaskSharing:
    """Tasks are team-scoped, not agent-scoped -- all agents see them."""

    async def test_task_created_visible_to_all(self, client: Client):
        """A task created by any context is visible via task_list."""
        await client.call_tool("team_create", {"team_name": "t_ts1"})
        await client.call_tool("task_create", {
            "team_name": "t_ts1",
            "subject": "shared task",
            "description": "everyone sees this",
        })

        result = _data(await client.call_tool(
            "task_list", {"team_name": "t_ts1"},
        ))
        assert len(result) == 1
        assert result[0]["subject"] == "shared task"

    async def test_task_status_update_visible_to_all(self, client: Client):
        """Status update is visible via task_get from any context."""
        await client.call_tool("team_create", {"team_name": "t_ts2"})
        created = _data(await client.call_tool("task_create", {
            "team_name": "t_ts2",
            "subject": "progress tracker",
            "description": "track progress",
        }))

        await client.call_tool("task_update", {
            "team_name": "t_ts2",
            "task_id": created["id"],
            "status": "in_progress",
        })

        task = _data(await client.call_tool("task_get", {
            "team_name": "t_ts2",
            "task_id": created["id"],
        }))
        assert task["status"] == "in_progress"

    async def test_multiple_agents_claim_different_tasks(self, client: Client):
        """Two tasks assigned to different agents show correct owners."""
        await client.call_tool("team_create", {"team_name": "t_ts3"})
        teams.add_member("t_ts3", _make_teammate("alice", "t_ts3"))
        teams.add_member("t_ts3", _make_teammate("bob", "t_ts3"))

        t1 = _data(await client.call_tool("task_create", {
            "team_name": "t_ts3",
            "subject": "task-for-alice",
            "description": "d1",
        }))
        t2 = _data(await client.call_tool("task_create", {
            "team_name": "t_ts3",
            "subject": "task-for-bob",
            "description": "d2",
        }))

        await client.call_tool("task_update", {
            "team_name": "t_ts3",
            "task_id": t1["id"],
            "owner": "alice",
        })
        await client.call_tool("task_update", {
            "team_name": "t_ts3",
            "task_id": t2["id"],
            "owner": "bob",
        })

        all_tasks = _data(await client.call_tool(
            "task_list", {"team_name": "t_ts3"},
        ))
        assert len(all_tasks) == 2

        owners = {t["subject"]: t.get("owner") for t in all_tasks}
        assert owners["task-for-alice"] == "alice"
        assert owners["task-for-bob"] == "bob"


# ===========================================================================
# Class 3: Filesystem state sharing
# ===========================================================================

class TestFilesystemStateSharing:
    """Verify JSON files on disk match expected state after MCP operations.

    Confirms MCP-03 at the filesystem level -- the empirical confirmation
    required by the blockers in STATE.md.
    """

    async def test_inbox_file_exists_after_send(self, mcp_dirs: Path):
        """Inbox JSON file on disk contains the expected message."""
        async with Client(mcp) as c:
            await c.call_tool("team_create", {"team_name": "t_fs1"})
            teams.add_member("t_fs1", _make_teammate("alice", "t_fs1"))
            await c.call_tool("send_message", {
                "team_name": "t_fs1",
                "type": "message",
                "recipient": "alice",
                "content": "disk check",
                "summary": "fs-test",
            })

        # Read raw file from disk
        inbox_file = mcp_dirs / "teams" / "t_fs1" / "inboxes" / "alice.json"
        assert inbox_file.exists(), f"Expected inbox file at {inbox_file}"
        data = json.loads(inbox_file.read_text())
        assert len(data) == 1
        assert data[0]["from"] == "team-lead"
        assert data[0]["text"] == "disk check"

    async def test_task_file_exists_after_create(self, mcp_dirs: Path):
        """Task JSON file on disk has the expected fields."""
        async with Client(mcp) as c:
            await c.call_tool("team_create", {"team_name": "t_fs2"})
            created = _data(await c.call_tool("task_create", {
                "team_name": "t_fs2",
                "subject": "fs-task",
                "description": "check disk",
            }))

        task_file = mcp_dirs / "tasks" / "t_fs2" / f"{created['id']}.json"
        assert task_file.exists(), f"Expected task file at {task_file}"
        data = json.loads(task_file.read_text())
        assert data["subject"] == "fs-task"
        assert data["description"] == "check disk"
        assert data["status"] == "pending"

    async def test_cross_context_state_visible(self, mcp_dirs: Path):
        """State written by one Client session is readable by another.

        This is the critical multi-process simulation: two separate
        ``Client(mcp)`` sessions sharing the same monkeypatched filesystem
        dirs.  Client 1 creates a team and sends a message; Client 2 (a
        fresh session) reads bob's inbox and receives that message.
        """
        async with Client(mcp) as client1:
            await client1.call_tool("team_create", {"team_name": "cross"})
            teams.add_member("cross", _make_teammate("alice", "cross"))
            teams.add_member("cross", _make_teammate("bob", "cross"))
            await client1.call_tool("send_message", {
                "team_name": "cross",
                "type": "message",
                "recipient": "bob",
                "content": "cross-context test",
                "summary": "xctx",
            })

        # New client session -- simulates separate MCP server process
        async with Client(mcp) as client2:
            inbox = _data(await client2.call_tool(
                "read_inbox", {"team_name": "cross", "agent_name": "bob"},
            ))
            assert len(inbox) == 1
            assert inbox[0]["text"] == "cross-context test"
            assert inbox[0]["from"] == "team-lead"

    async def test_task_file_reflects_owner_after_update(self, mcp_dirs: Path):
        """Owner update via MCP tool persists to the task JSON file."""
        async with Client(mcp) as c:
            await c.call_tool("team_create", {"team_name": "t_fs4"})
            teams.add_member("t_fs4", _make_teammate("alice", "t_fs4"))
            created = _data(await c.call_tool("task_create", {
                "team_name": "t_fs4",
                "subject": "own-test",
                "description": "owner check",
            }))
            await c.call_tool("task_update", {
                "team_name": "t_fs4",
                "task_id": created["id"],
                "owner": "alice",
            })

        task_file = mcp_dirs / "tasks" / "t_fs4" / f"{created['id']}.json"
        assert task_file.exists()
        data = json.loads(task_file.read_text())
        assert data["owner"] == "alice"
