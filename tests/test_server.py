from __future__ import annotations

import json
import time
import unittest.mock
from pathlib import Path

import pytest
from fastmcp import Client

from claude_teams import messaging, tasks, teams
from claude_teams.models import AgentHealthStatus, TeammateMember
from claude_teams.server import mcp


def _make_teammate(name: str, team_name: str, pane_id: str = "%1") -> TeammateMember:
    return TeammateMember(
        agent_id=f"{name}@{team_name}",
        name=name,
        agent_type="teammate",
        model="claude-sonnet-4-20250514",
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


class TestErrorPropagation:
    async def test_should_reject_second_team_in_same_session(self, client: Client):
        await client.call_tool("team_create", {"team_name": "alpha"})
        result = await client.call_tool(
            "team_create", {"team_name": "beta"}, raise_on_error=False
        )
        assert result.is_error is True
        assert "alpha" in result.content[0].text

    async def test_should_reject_unknown_agent_in_force_kill(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t1"})
        result = await client.call_tool(
            "force_kill_teammate",
            {"team_name": "t1", "agent_name": "ghost"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "ghost" in result.content[0].text

    async def test_should_reject_invalid_message_type(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t_msg"})
        result = await client.call_tool(
            "send_message",
            {"team_name": "t_msg", "type": "bogus"},
            raise_on_error=False,
        )
        assert result.is_error is True


class TestDeletedTaskGuard:
    async def test_should_not_send_assignment_when_task_deleted(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t2"})
        created = _data(
            await client.call_tool(
                "task_create",
                {"team_name": "t2", "subject": "doomed", "description": "will delete"},
            )
        )
        await client.call_tool(
            "task_update",
            {
                "team_name": "t2",
                "task_id": created["id"],
                "status": "deleted",
                "owner": "worker",
            },
        )
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t2", "agent_name": "worker"}
            )
        )
        assert inbox == []

    async def test_should_send_assignment_when_owner_set_on_live_task(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t2b"})
        created = _data(
            await client.call_tool(
                "task_create",
                {"team_name": "t2b", "subject": "live", "description": "stays"},
            )
        )
        await client.call_tool(
            "task_update",
            {"team_name": "t2b", "task_id": created["id"], "owner": "worker"},
        )
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t2b", "agent_name": "worker"}
            )
        )
        assert len(inbox) == 1
        payload = json.loads(inbox[0]["text"])
        assert payload["type"] == "task_assignment"
        assert payload["taskId"] == created["id"]


class TestShutdownResponseSender:
    async def test_should_populate_correct_from_and_pane_id_on_approve(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t3"})
        teams.add_member("t3", _make_teammate("worker", "t3", pane_id="%42"))
        await client.call_tool(
            "send_message",
            {
                "team_name": "t3",
                "type": "shutdown_response",
                "sender": "worker",
                "request_id": "req-1",
                "approve": True,
            },
        )
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t3", "agent_name": "team-lead"}
            )
        )
        assert len(inbox) == 1
        payload = json.loads(inbox[0]["text"])
        assert payload["type"] == "shutdown_approved"
        assert payload["from"] == "worker"
        assert payload["paneId"] == "%42"
        assert payload["requestId"] == "req-1"

    async def test_should_attribute_rejection_to_sender(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t3b"})
        teams.add_member("t3b", _make_teammate("rebel", "t3b"))
        await client.call_tool(
            "send_message",
            {
                "team_name": "t3b",
                "type": "shutdown_response",
                "sender": "rebel",
                "request_id": "req-2",
                "approve": False,
                "content": "still busy",
            },
        )
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t3b", "agent_name": "team-lead"}
            )
        )
        assert len(inbox) == 1
        assert inbox[0]["from"] == "rebel"
        assert inbox[0]["text"] == "still busy"


class TestPlanApprovalSender:
    async def test_should_use_sender_as_from_on_approve(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t_plan"})
        teams.add_member("t_plan", _make_teammate("dev", "t_plan"))
        await client.call_tool(
            "send_message",
            {
                "team_name": "t_plan",
                "type": "plan_approval_response",
                "sender": "team-lead",
                "recipient": "dev",
                "request_id": "plan-1",
                "approve": True,
            },
        )
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t_plan", "agent_name": "dev"}
            )
        )
        assert len(inbox) == 1
        assert inbox[0]["from"] == "team-lead"
        payload = json.loads(inbox[0]["text"])
        assert payload["type"] == "plan_approval"
        assert payload["approved"] is True

    async def test_should_use_sender_as_from_on_reject(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t_plan2"})
        teams.add_member("t_plan2", _make_teammate("dev2", "t_plan2"))
        await client.call_tool(
            "send_message",
            {
                "team_name": "t_plan2",
                "type": "plan_approval_response",
                "sender": "team-lead",
                "recipient": "dev2",
                "approve": False,
                "content": "needs error handling",
            },
        )
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t_plan2", "agent_name": "dev2"}
            )
        )
        assert len(inbox) == 1
        assert inbox[0]["from"] == "team-lead"
        assert inbox[0]["text"] == "needs error handling"


class TestWiring:
    async def test_should_round_trip_task_create_and_list(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t4"})
        await client.call_tool(
            "task_create",
            {"team_name": "t4", "subject": "first", "description": "d1"},
        )
        await client.call_tool(
            "task_create",
            {"team_name": "t4", "subject": "second", "description": "d2"},
        )
        result = _data(await client.call_tool("task_list", {"team_name": "t4"}))
        assert len(result) == 2
        assert result[0]["subject"] == "first"
        assert result[1]["subject"] == "second"

    async def test_should_round_trip_send_message_and_read_inbox(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t5"})
        teams.add_member("t5", _make_teammate("bob", "t5"))
        await client.call_tool(
            "send_message",
            {
                "team_name": "t5",
                "type": "message",
                "recipient": "bob",
                "content": "hello bob",
                "summary": "greeting",
            },
        )
        inbox = _data(
            await client.call_tool(
                "read_inbox", {"team_name": "t5", "agent_name": "bob"}
            )
        )
        assert len(inbox) == 1
        assert inbox[0]["text"] == "hello bob"
        assert inbox[0]["from"] == "team-lead"


class TestTeamDeleteClearsSession:
    async def test_should_allow_new_team_after_delete(self, client: Client):
        await client.call_tool("team_create", {"team_name": "first"})
        await client.call_tool("team_delete", {"team_name": "first"})
        result = await client.call_tool("team_create", {"team_name": "second"})
        data = _data(result)
        assert data["team_name"] == "second"


class TestSendMessageValidation:
    async def test_should_reject_empty_content(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tv1"})
        teams.add_member("tv1", _make_teammate("bob", "tv1"))
        result = await client.call_tool(
            "send_message",
            {"team_name": "tv1", "type": "message", "recipient": "bob", "content": "", "summary": "hi"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "content" in result.content[0].text.lower()

    async def test_should_reject_empty_summary(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tv2"})
        teams.add_member("tv2", _make_teammate("bob", "tv2"))
        result = await client.call_tool(
            "send_message",
            {"team_name": "tv2", "type": "message", "recipient": "bob", "content": "hi", "summary": ""},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "summary" in result.content[0].text.lower()

    async def test_should_reject_empty_recipient(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tv3"})
        result = await client.call_tool(
            "send_message",
            {"team_name": "tv3", "type": "message", "recipient": "", "content": "hi", "summary": "hi"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "recipient" in result.content[0].text.lower()

    async def test_should_reject_nonexistent_recipient(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tv4"})
        result = await client.call_tool(
            "send_message",
            {"team_name": "tv4", "type": "message", "recipient": "ghost", "content": "hi", "summary": "hi"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "ghost" in result.content[0].text

    async def test_should_pass_target_color(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tv5"})
        teams.add_member("tv5", _make_teammate("bob", "tv5"))
        result = await client.call_tool(
            "send_message",
            {"team_name": "tv5", "type": "message", "recipient": "bob", "content": "hey", "summary": "greet"},
        )
        data = _data(result)
        assert data["routing"]["targetColor"] == "blue"

    async def test_should_reject_broadcast_empty_summary(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tv6"})
        result = await client.call_tool(
            "send_message",
            {"team_name": "tv6", "type": "broadcast", "content": "hello", "summary": ""},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "summary" in result.content[0].text.lower()

    async def test_should_reject_shutdown_request_to_team_lead(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tv7"})
        result = await client.call_tool(
            "send_message",
            {"team_name": "tv7", "type": "shutdown_request", "recipient": "team-lead"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "team-lead" in result.content[0].text

    async def test_should_reject_shutdown_request_to_nonexistent(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tv8"})
        result = await client.call_tool(
            "send_message",
            {"team_name": "tv8", "type": "shutdown_request", "recipient": "ghost"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "ghost" in result.content[0].text


class TestProcessShutdownGuard:
    async def test_should_reject_shutdown_of_team_lead(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tsg"})
        result = await client.call_tool(
            "process_shutdown_approved",
            {"team_name": "tsg", "agent_name": "team-lead"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "team-lead" in result.content[0].text


class TestErrorWrapping:
    async def test_read_config_wraps_file_not_found(self, client: Client):
        result = await client.call_tool(
            "read_config", {"team_name": "nonexistent"}, raise_on_error=False,
        )
        assert result.is_error is True
        assert "not found" in result.content[0].text.lower()

    async def test_task_get_wraps_file_not_found(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tew"})
        result = await client.call_tool(
            "task_get", {"team_name": "tew", "task_id": "999"}, raise_on_error=False,
        )
        assert result.is_error is True
        assert "not found" in result.content[0].text.lower()

    async def test_task_update_wraps_file_not_found(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tew2"})
        result = await client.call_tool(
            "task_update",
            {"team_name": "tew2", "task_id": "999", "status": "completed"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "not found" in result.content[0].text.lower()

    async def test_task_create_wraps_nonexistent_team(self, client: Client):
        result = await client.call_tool(
            "task_create",
            {"team_name": "ghost-team", "subject": "x", "description": "y"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "does not exist" in result.content[0].text.lower()

    async def test_task_update_wraps_validation_error(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tew3"})
        created = _data(
            await client.call_tool(
                "task_create",
                {"team_name": "tew3", "subject": "S", "description": "d"},
            )
        )
        await client.call_tool(
            "task_update",
            {"team_name": "tew3", "task_id": created["id"], "status": "in_progress"},
        )
        result = await client.call_tool(
            "task_update",
            {"team_name": "tew3", "task_id": created["id"], "status": "pending"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "cannot transition" in result.content[0].text.lower()

    async def test_task_list_wraps_nonexistent_team(self, client: Client):
        result = await client.call_tool(
            "task_list", {"team_name": "ghost-team"}, raise_on_error=False,
        )
        assert result.is_error is True
        assert "does not exist" in result.content[0].text.lower()


class TestPollInbox:
    async def test_should_return_empty_on_timeout(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t6"})
        result = _data(
            await client.call_tool(
                "poll_inbox",
                {"team_name": "t6", "agent_name": "nobody", "timeout_ms": 100},
            )
        )
        assert result == []

    async def test_should_return_messages_when_present(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t6b"})
        teams.add_member("t6b", _make_teammate("alice", "t6b"))
        await client.call_tool(
            "send_message",
            {
                "team_name": "t6b",
                "type": "message",
                "recipient": "alice",
                "content": "wake up",
                "summary": "nudge",
            },
        )
        result = _data(
            await client.call_tool(
                "poll_inbox",
                {"team_name": "t6b", "agent_name": "alice", "timeout_ms": 100},
            )
        )
        assert len(result) == 1
        assert result[0]["text"] == "wake up"

    async def test_should_return_existing_messages_with_zero_timeout(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t6c"})
        teams.add_member("t6c", _make_teammate("bob", "t6c"))
        await client.call_tool(
            "send_message",
            {
                "team_name": "t6c",
                "type": "message",
                "recipient": "bob",
                "content": "instant",
                "summary": "fast",
            },
        )
        result = _data(
            await client.call_tool(
                "poll_inbox",
                {"team_name": "t6c", "agent_name": "bob", "timeout_ms": 0},
            )
        )
        assert len(result) == 1
        assert result[0]["text"] == "instant"


class TestTeamDeleteErrorWrapping:
    async def test_should_reject_delete_with_active_members(self, client: Client):
        await client.call_tool("team_create", {"team_name": "td1"})
        teams.add_member("td1", _make_teammate("worker", "td1"))
        result = await client.call_tool(
            "team_delete", {"team_name": "td1"}, raise_on_error=False,
        )
        assert result.is_error is True
        assert "member" in result.content[0].text.lower()

    async def test_should_reject_delete_nonexistent_team(self, client: Client):
        result = await client.call_tool(
            "team_delete", {"team_name": "ghost-team"}, raise_on_error=False,
        )
        assert result.is_error is True
        assert "Traceback" not in result.content[0].text


class TestPlanApprovalValidation:
    async def test_should_reject_plan_approval_to_nonexistent_recipient(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tp1"})
        result = await client.call_tool(
            "send_message",
            {
                "team_name": "tp1",
                "type": "plan_approval_response",
                "recipient": "ghost",
                "approve": True,
            },
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "ghost" in result.content[0].text

    async def test_should_reject_plan_approval_with_empty_recipient(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tp2"})
        result = await client.call_tool(
            "send_message",
            {
                "team_name": "tp2",
                "type": "plan_approval_response",
                "recipient": "",
                "approve": True,
            },
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "recipient" in result.content[0].text.lower()


class TestModelTranslationWiring:
    async def test_spawn_passes_translated_model(self, client: Client):
        """Verify that spawn_teammate_tool translates 'sonnet' to provider/model format."""
        await client.call_tool("team_create", {"team_name": "tm1"})
        # Mock spawn_teammate to capture the model argument without actually spawning
        import unittest.mock
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn:
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@tm1", name="worker", agent_type="general-purpose",
                model="moonshot-ai/kimi-k2.5", prompt="do work", color="blue",
                joined_at=0, tmux_pane_id="%1", cwd="/tmp",
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "tm1", "name": "worker", "prompt": "do work", "model": "sonnet",
            })
            # The model passed to spawn_teammate should be the translated version
            call_kwargs = mock_spawn.call_args
            assert call_kwargs is not None
            # Check that 'model' kwarg is the translated string
            if call_kwargs.kwargs:
                assert call_kwargs.kwargs.get("model") == "moonshot-ai/kimi-k2.5"

    async def test_spawn_passes_through_direct_model(self, client: Client):
        """Verify that a direct provider/model string passes through unchanged."""
        await client.call_tool("team_create", {"team_name": "tm2"})
        import unittest.mock
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn:
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@tm2", name="worker", agent_type="general-purpose",
                model="openrouter/moonshotai/kimi-k2.5", prompt="do work", color="blue",
                joined_at=0, tmux_pane_id="%1", cwd="/tmp",
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "tm2", "name": "worker", "prompt": "do work",
                "model": "openrouter/moonshotai/kimi-k2.5",
            })
            call_kwargs = mock_spawn.call_args
            assert call_kwargs is not None
            if call_kwargs.kwargs:
                assert call_kwargs.kwargs.get("model") == "openrouter/moonshotai/kimi-k2.5"


class TestListAgentTemplates:
    async def test_returns_all_four_templates(self, client: Client):
        result = _data(await client.call_tool("list_agent_templates", {}))
        assert len(result) >= 4
        names = {t["name"] for t in result}
        assert {"researcher", "implementer", "reviewer", "tester"} <= names
        for t in result:
            assert "name" in t
            assert "description" in t

    async def test_returns_list_of_dicts(self, client: Client):
        result = _data(await client.call_tool("list_agent_templates", {}))
        assert isinstance(result, list)
        for entry in result:
            assert isinstance(entry, dict)


class TestSpawnWithTemplateTool:
    async def test_spawn_with_researcher_template(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tpl1"})
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn:
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@tpl1", name="worker", agent_type="researcher",
                model="moonshot-ai/kimi-k2.5", prompt="do research", color="blue",
                joined_at=0, tmux_pane_id="%1", cwd="/tmp",
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "tpl1", "name": "worker", "prompt": "do research",
                "template": "researcher",
            })
            call_kwargs = mock_spawn.call_args.kwargs
            assert "# Role: Researcher" in call_kwargs["role_instructions"]
            assert call_kwargs["subagent_type"] == "researcher"

    async def test_spawn_with_custom_instructions(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tpl2"})
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn:
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@tpl2", name="worker", agent_type="general-purpose",
                model="moonshot-ai/kimi-k2.5", prompt="do work", color="blue",
                joined_at=0, tmux_pane_id="%1", cwd="/tmp",
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "tpl2", "name": "worker", "prompt": "do work",
                "custom_instructions": "Focus on Python",
            })
            call_kwargs = mock_spawn.call_args.kwargs
            assert call_kwargs["custom_instructions"] == "Focus on Python"

    async def test_spawn_with_template_and_custom_instructions(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tpl3"})
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn:
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@tpl3", name="worker", agent_type="tester",
                model="moonshot-ai/kimi-k2.5", prompt="test stuff", color="blue",
                joined_at=0, tmux_pane_id="%1", cwd="/tmp",
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "tpl3", "name": "worker", "prompt": "test stuff",
                "template": "tester", "custom_instructions": "Also check performance",
            })
            call_kwargs = mock_spawn.call_args.kwargs
            assert "# Role: Tester" in call_kwargs["role_instructions"]
            assert call_kwargs["custom_instructions"] == "Also check performance"

    async def test_spawn_with_unknown_template_raises_error(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tpl4"})
        result = await client.call_tool(
            "spawn_teammate",
            {"team_name": "tpl4", "name": "worker", "prompt": "do work",
             "template": "nonexistent"},
            raise_on_error=False,
        )
        assert result.is_error is True
        text = result.content[0].text
        assert "Unknown template" in text
        assert "nonexistent" in text
        # Should list available templates
        assert "researcher" in text
        assert "implementer" in text

    async def test_spawn_without_template_uses_general_purpose(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tpl5"})
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn:
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@tpl5", name="worker", agent_type="general-purpose",
                model="moonshot-ai/kimi-k2.5", prompt="do work", color="blue",
                joined_at=0, tmux_pane_id="%1", cwd="/tmp",
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "tpl5", "name": "worker", "prompt": "do work",
            })
            call_kwargs = mock_spawn.call_args.kwargs
            assert call_kwargs["subagent_type"] == "general-purpose"
            assert call_kwargs["role_instructions"] == ""

    async def test_spawn_template_sets_subagent_type(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tpl6"})
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn:
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@tpl6", name="worker", agent_type="tester",
                model="moonshot-ai/kimi-k2.5", prompt="test", color="blue",
                joined_at=0, tmux_pane_id="%1", cwd="/tmp",
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "tpl6", "name": "worker", "prompt": "test",
                "template": "tester",
            })
            call_kwargs = mock_spawn.call_args.kwargs
            assert call_kwargs["subagent_type"] == "tester"


class TestConfigCleanup:
    """Tests for config cleanup integration in server lifecycle operations."""

    async def test_force_kill_cleans_up_agent_config(self, client: Client):
        """Verify force_kill_teammate calls cleanup_agent_config"""
        await client.call_tool("team_create", {"team_name": "tk1"})
        teams.add_member("tk1", _make_teammate("worker", "tk1", pane_id="%99"))

        import unittest.mock
        with unittest.mock.patch("claude_teams.server.cleanup_agent_config") as mock_cleanup, \
             unittest.mock.patch("claude_teams.server.kill_tmux_pane"):
            await client.call_tool(
                "force_kill_teammate",
                {"team_name": "tk1", "agent_name": "worker"},
            )
            # Verify cleanup was called with the agent name
            mock_cleanup.assert_called_once()
            call_args = mock_cleanup.call_args
            assert call_args is not None
            # Second positional arg should be agent name
            assert call_args[0][1] == "worker"

    async def test_process_shutdown_cleans_up_agent_config(self, client: Client):
        """Verify process_shutdown_approved calls cleanup_agent_config"""
        await client.call_tool("team_create", {"team_name": "tk2"})
        teams.add_member("tk2", _make_teammate("worker2", "tk2"))

        import unittest.mock
        with unittest.mock.patch("claude_teams.server.cleanup_agent_config") as mock_cleanup:
            await client.call_tool(
                "process_shutdown_approved",
                {"team_name": "tk2", "agent_name": "worker2"},
            )
            # Verify cleanup was called with the agent name
            mock_cleanup.assert_called_once()
            call_args = mock_cleanup.call_args
            assert call_args is not None
            # Second positional arg should be agent name
            assert call_args[0][1] == "worker2"


def _make_alive_status(name: str, pane_id: str = "%1", content_hash: str = "abc123") -> AgentHealthStatus:
    return AgentHealthStatus(
        agent_name=name,
        pane_id=pane_id,
        status="alive",
        last_content_hash=content_hash,
        detail="Pane is active",
    )


def _make_dead_status(name: str, pane_id: str = "%1") -> AgentHealthStatus:
    return AgentHealthStatus(
        agent_name=name,
        pane_id=pane_id,
        status="dead",
        detail="Pane is missing or dead",
    )


def _make_hung_status(name: str, pane_id: str = "%1", content_hash: str = "abc123") -> AgentHealthStatus:
    return AgentHealthStatus(
        agent_name=name,
        pane_id=pane_id,
        status="hung",
        last_content_hash=content_hash,
        detail="Content unchanged for 130s (threshold: 120s)",
    )


class TestCheckAgentHealth:
    async def test_returns_alive_for_live_agent(self, client: Client):
        await client.call_tool("team_create", {"team_name": "th1"})
        teams.add_member("th1", _make_teammate("worker", "th1", pane_id="%10"))

        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            return_value=_make_alive_status("worker", "%10"),
        ):
            result = _data(
                await client.call_tool(
                    "check_agent_health",
                    {"team_name": "th1", "agent_name": "worker"},
                )
            )
        assert result["status"] == "alive"
        assert result["agentName"] == "worker"
        assert result["paneId"] == "%10"

    async def test_returns_dead_for_missing_pane(self, client: Client):
        await client.call_tool("team_create", {"team_name": "th2"})
        teams.add_member("th2", _make_teammate("worker", "th2", pane_id="%20"))

        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            return_value=_make_dead_status("worker", "%20"),
        ):
            result = _data(
                await client.call_tool(
                    "check_agent_health",
                    {"team_name": "th2", "agent_name": "worker"},
                )
            )
        assert result["status"] == "dead"
        assert result["agentName"] == "worker"

    async def test_raises_for_unknown_agent(self, client: Client):
        await client.call_tool("team_create", {"team_name": "th3"})
        result = await client.call_tool(
            "check_agent_health",
            {"team_name": "th3", "agent_name": "ghost"},
            raise_on_error=False,
        )
        assert result.is_error is True
        assert "ghost" in result.content[0].text

    async def test_returns_hung_on_second_call_with_unchanged_content(self, client: Client):
        await client.call_tool("team_create", {"team_name": "th4"})
        teams.add_member("th4", _make_teammate("worker", "th4", pane_id="%30"))

        # First call returns alive with a content hash
        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            return_value=_make_alive_status("worker", "%30", content_hash="samehash"),
        ):
            result1 = _data(
                await client.call_tool(
                    "check_agent_health",
                    {"team_name": "th4", "agent_name": "worker"},
                )
            )
        assert result1["status"] == "alive"

        # Second call: same hash, enough time passed -> hung
        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            return_value=_make_hung_status("worker", "%30", content_hash="samehash"),
        ):
            result2 = _data(
                await client.call_tool(
                    "check_agent_health",
                    {"team_name": "th4", "agent_name": "worker"},
                )
            )
        assert result2["status"] == "hung"

    async def test_health_state_persists_between_calls(self, client: Client):
        """Verify that health state is saved and loaded between calls."""
        await client.call_tool("team_create", {"team_name": "th5"})
        teams.add_member("th5", _make_teammate("worker", "th5", pane_id="%40"))

        call_args_list = []

        def capture_check(member, previous_hash=None, last_change_time=None):
            call_args_list.append({
                "previous_hash": previous_hash,
                "last_change_time": last_change_time,
            })
            return _make_alive_status(member.name, member.tmux_pane_id, content_hash="hash1")

        # First call: no previous state
        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            side_effect=capture_check,
        ):
            await client.call_tool(
                "check_agent_health",
                {"team_name": "th5", "agent_name": "worker"},
            )

        assert call_args_list[0]["previous_hash"] is None
        assert call_args_list[0]["last_change_time"] is None

        # Second call: should have persisted state from first call
        def capture_check_2(member, previous_hash=None, last_change_time=None):
            call_args_list.append({
                "previous_hash": previous_hash,
                "last_change_time": last_change_time,
            })
            return _make_alive_status(member.name, member.tmux_pane_id, content_hash="hash2")

        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            side_effect=capture_check_2,
        ):
            await client.call_tool(
                "check_agent_health",
                {"team_name": "th5", "agent_name": "worker"},
            )

        assert call_args_list[1]["previous_hash"] == "hash1"
        assert call_args_list[1]["last_change_time"] is not None

    async def test_uses_camel_case_aliases_in_response(self, client: Client):
        await client.call_tool("team_create", {"team_name": "th6"})
        teams.add_member("th6", _make_teammate("worker", "th6", pane_id="%50"))

        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            return_value=_make_alive_status("worker", "%50", content_hash="xyz"),
        ):
            result = _data(
                await client.call_tool(
                    "check_agent_health",
                    {"team_name": "th6", "agent_name": "worker"},
                )
            )
        # Should use camelCase keys (by_alias=True)
        assert "agentName" in result
        assert "paneId" in result
        assert "lastContentHash" in result
        # Should NOT have snake_case keys
        assert "agent_name" not in result
        assert "pane_id" not in result


class TestCheckAllAgentsHealth:
    async def test_returns_status_for_all_teammates(self, client: Client):
        await client.call_tool("team_create", {"team_name": "ta1"})
        teams.add_member("ta1", _make_teammate("worker1", "ta1", pane_id="%60"))
        teams.add_member("ta1", _make_teammate("worker2", "ta1", pane_id="%61"))

        def mock_check(member, previous_hash=None, last_change_time=None):
            return _make_alive_status(member.name, member.tmux_pane_id)

        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            side_effect=mock_check,
        ):
            result = _data(
                await client.call_tool(
                    "check_all_agents_health",
                    {"team_name": "ta1"},
                )
            )
        assert len(result) == 2
        names = {r["agentName"] for r in result}
        assert names == {"worker1", "worker2"}
        assert all(r["status"] == "alive" for r in result)

    async def test_excludes_lead_member(self, client: Client):
        """Lead member should not appear in health check results."""
        await client.call_tool("team_create", {"team_name": "ta2"})
        teams.add_member("ta2", _make_teammate("worker", "ta2", pane_id="%70"))

        def mock_check(member, previous_hash=None, last_change_time=None):
            return _make_alive_status(member.name, member.tmux_pane_id)

        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            side_effect=mock_check,
        ):
            result = _data(
                await client.call_tool(
                    "check_all_agents_health",
                    {"team_name": "ta2"},
                )
            )
        # Only teammate, not team-lead
        assert len(result) == 1
        assert result[0]["agentName"] == "worker"

    async def test_returns_empty_list_for_no_teammates(self, client: Client):
        await client.call_tool("team_create", {"team_name": "ta3"})
        result = _data(
            await client.call_tool(
                "check_all_agents_health",
                {"team_name": "ta3"},
            )
        )
        assert result == []

    async def test_persists_health_state_for_all_agents(self, client: Client):
        """Verify health state is saved for all agents after batch check."""
        await client.call_tool("team_create", {"team_name": "ta4"})
        teams.add_member("ta4", _make_teammate("w1", "ta4", pane_id="%80"))
        teams.add_member("ta4", _make_teammate("w2", "ta4", pane_id="%81"))

        call_count = {"n": 0}

        def mock_check(member, previous_hash=None, last_change_time=None):
            call_count["n"] += 1
            return _make_alive_status(member.name, member.tmux_pane_id, content_hash=f"hash_{member.name}")

        # First call
        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            side_effect=mock_check,
        ):
            await client.call_tool(
                "check_all_agents_health",
                {"team_name": "ta4"},
            )

        assert call_count["n"] == 2

        # Second call: verify state was passed (previous_hash should be set)
        captured_args = []

        def mock_check_2(member, previous_hash=None, last_change_time=None):
            captured_args.append({
                "name": member.name,
                "previous_hash": previous_hash,
            })
            return _make_alive_status(member.name, member.tmux_pane_id, content_hash=f"hash2_{member.name}")

        with unittest.mock.patch(
            "claude_teams.server.check_single_agent_health",
            side_effect=mock_check_2,
        ):
            await client.call_tool(
                "check_all_agents_health",
                {"team_name": "ta4"},
            )

        # Both agents should have previous hashes from first call
        for arg in captured_args:
            assert arg["previous_hash"] is not None, f"No previous hash for {arg['name']}"


class TestSpawnDesktopBackendTool:
    async def test_spawn_with_desktop_backend(self, client: Client):
        await client.call_tool("team_create", {"team_name": "td1"})
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn, \
             unittest.mock.patch("claude_teams.server.discover_desktop_binary", return_value="/fake/desktop"):
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@td1", name="worker", agent_type="general-purpose",
                model="moonshot-ai/kimi-k2.5", prompt="do work", color="blue",
                joined_at=0, tmux_pane_id="", cwd="/tmp",
                backend_type="desktop", process_id=9999,
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "td1", "name": "worker", "prompt": "do work",
                "backend": "desktop",
            })
            call_kwargs = mock_spawn.call_args.kwargs
            assert call_kwargs["backend_type"] == "desktop"
            assert call_kwargs["desktop_binary"] == "/fake/desktop"

    async def test_spawn_with_tmux_backend_default(self, client: Client):
        await client.call_tool("team_create", {"team_name": "td2"})
        with unittest.mock.patch("claude_teams.server.spawn_teammate") as mock_spawn:
            mock_spawn.return_value = TeammateMember(
                agent_id="worker@td2", name="worker", agent_type="general-purpose",
                model="moonshot-ai/kimi-k2.5", prompt="do work", color="blue",
                joined_at=0, tmux_pane_id="%1", cwd="/tmp",
            )
            await client.call_tool("spawn_teammate", {
                "team_name": "td2", "name": "worker", "prompt": "do work",
            })
            call_kwargs = mock_spawn.call_args.kwargs
            assert call_kwargs["backend_type"] == "tmux"
            assert call_kwargs["desktop_binary"] is None

    async def test_spawn_desktop_discovery_failure(self, client: Client):
        await client.call_tool("team_create", {"team_name": "td3"})
        with unittest.mock.patch(
            "claude_teams.server.discover_desktop_binary",
            side_effect=FileNotFoundError("Desktop binary not found"),
        ):
            result = await client.call_tool(
                "spawn_teammate",
                {"team_name": "td3", "name": "worker", "prompt": "do work",
                 "backend": "desktop"},
                raise_on_error=False,
            )
            assert result.is_error is True
            assert "not found" in result.content[0].text.lower()


class TestForceKillDesktopBackend:
    async def test_force_kill_desktop_agent(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tk_d1"})
        member = TeammateMember(
            agent_id="worker@tk_d1", name="worker", agent_type="general-purpose",
            model="kimi-k2.5", prompt="work", color="blue",
            joined_at=int(time.time() * 1000), tmux_pane_id="", cwd="/tmp",
            backend_type="desktop", process_id=5555,
        )
        teams.add_member("tk_d1", member)

        with unittest.mock.patch("claude_teams.server.kill_desktop_process") as mock_kill_desktop, \
             unittest.mock.patch("claude_teams.server.kill_tmux_pane") as mock_kill_tmux:
            await client.call_tool(
                "force_kill_teammate",
                {"team_name": "tk_d1", "agent_name": "worker"},
            )
            mock_kill_desktop.assert_called_once_with(5555)
            mock_kill_tmux.assert_not_called()

    async def test_force_kill_tmux_agent_unchanged(self, client: Client):
        await client.call_tool("team_create", {"team_name": "tk_d2"})
        member = TeammateMember(
            agent_id="worker@tk_d2", name="worker", agent_type="general-purpose",
            model="kimi-k2.5", prompt="work", color="blue",
            joined_at=int(time.time() * 1000), tmux_pane_id="%42", cwd="/tmp",
            backend_type="tmux",
        )
        teams.add_member("tk_d2", member)

        with unittest.mock.patch("claude_teams.server.kill_tmux_pane") as mock_kill_tmux, \
             unittest.mock.patch("claude_teams.server.kill_desktop_process") as mock_kill_desktop:
            await client.call_tool(
                "force_kill_teammate",
                {"team_name": "tk_d2", "agent_name": "worker"},
            )
            mock_kill_tmux.assert_called_once_with("%42")
            mock_kill_desktop.assert_not_called()
