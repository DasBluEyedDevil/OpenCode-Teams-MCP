from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from opencode_teams.config_gen import (
    cleanup_agent_config,
    generate_agent_config,
    write_agent_config,
    ensure_opencode_json,
)


class TestGenerateAgentConfig:
    """Tests for generate_agent_config() - the markdown config builder."""

    def test_returns_string(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_starts_with_frontmatter_delimiter(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        assert result.startswith("---\n")

    def test_has_frontmatter_closing_delimiter(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        # Should have closing delimiter followed by body
        assert "\n---\n\n" in result

    def test_frontmatter_contains_mode_primary(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        frontmatter = self._extract_frontmatter(result)
        assert frontmatter["mode"] == "primary"

    def test_frontmatter_contains_model(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        frontmatter = self._extract_frontmatter(result)
        assert frontmatter["model"] == "moonshot-ai/kimi-k2.5"

    def test_frontmatter_permission_is_string_allow(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        frontmatter = self._extract_frontmatter(result)
        assert frontmatter["permission"] == "allow"
        assert isinstance(frontmatter["permission"], str)

    def test_frontmatter_contains_tools_dict(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        frontmatter = self._extract_frontmatter(result)
        assert "tools" in frontmatter
        assert isinstance(frontmatter["tools"], dict)

    def test_frontmatter_all_builtin_tools_enabled(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        frontmatter = self._extract_frontmatter(result)
        tools = frontmatter["tools"]

        # All builtin tools should be enabled
        builtins = [
            "read", "write", "edit", "bash", "glob", "grep",
            "list", "webfetch", "websearch", "todoread", "todowrite"
        ]
        for tool in builtins:
            assert tools[tool] is True

    def test_frontmatter_opencode_teams_tools_enabled(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        frontmatter = self._extract_frontmatter(result)
        tools = frontmatter["tools"]

        # opencode-teams MCP tools should be enabled with wildcard
        assert "opencode-teams_*" in tools
        assert tools["opencode-teams_*"] is True

    def test_body_contains_agent_name(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "**alice**" in body

    def test_body_contains_team_name(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "**team1**" in body

    def test_body_contains_agent_id(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "`alice@team1`" in body

    def test_body_contains_color(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "blue" in body

    def test_body_contains_inbox_polling_instructions(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "opencode-teams_read_inbox" in body
        assert "3-5 tool calls" in body

    def test_body_contains_send_message_instructions(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "opencode-teams_send_message" in body

    def test_body_contains_task_list_instructions(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "opencode-teams_task_list" in body

    def test_body_contains_task_update_instructions(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "opencode-teams_task_update" in body

    def test_body_contains_status_values(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "in_progress" in body
        assert "completed" in body

    def test_body_contains_shutdown_protocol(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        assert "shutdown_request" in body

    def _extract_frontmatter(self, config: str) -> dict:
        """Extract and parse YAML frontmatter."""
        lines = config.split("\n")
        assert lines[0] == "---"

        # Find closing delimiter
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break

        assert end_idx is not None, "No closing frontmatter delimiter found"

        frontmatter_text = "\n".join(lines[1:end_idx])
        return yaml.safe_load(frontmatter_text)

    def _extract_body(self, config: str) -> str:
        """Extract the body text after frontmatter."""
        parts = config.split("\n---\n\n", 1)
        assert len(parts) == 2, "Could not split frontmatter from body"
        return parts[1]


class TestGenerateAgentConfigWithTemplate:
    """Tests for generate_agent_config() with role_instructions and custom_instructions."""

    def test_role_instructions_injected_in_body(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
            role_instructions="# Role: Researcher\n\nYou focus on research.",
        )
        body = self._extract_body(result)
        assert "# Role: Researcher" in body
        assert "You focus on research." in body

    def test_role_instructions_appear_before_communication_protocol(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
            role_instructions="# Role: Researcher\n\nResearch focus.",
        )
        body = self._extract_body(result)
        role_pos = body.index("# Role: Researcher")
        comm_pos = body.index("# Communication Protocol")
        assert role_pos < comm_pos

    def test_custom_instructions_injected_in_body(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
            custom_instructions="Focus specifically on Python type hints.",
        )
        body = self._extract_body(result)
        assert "Focus specifically on Python type hints." in body

    def test_custom_instructions_wrapped_with_heading(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
            custom_instructions="Focus specifically on Python type hints.",
        )
        body = self._extract_body(result)
        heading_pos = body.index("# Additional Instructions")
        custom_pos = body.index("Focus specifically on Python type hints.")
        assert heading_pos < custom_pos

    def test_custom_instructions_appear_after_role_instructions(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
            role_instructions="# Role: Reviewer\n\nReview focus.",
            custom_instructions="Also check for type safety.",
        )
        body = self._extract_body(result)
        role_pos = body.index("# Role: Reviewer")
        custom_pos = body.index("# Additional Instructions")
        assert role_pos < custom_pos

    def test_custom_instructions_appear_before_communication_protocol(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
            custom_instructions="Focus on security.",
        )
        body = self._extract_body(result)
        custom_pos = body.index("# Additional Instructions")
        comm_pos = body.index("# Communication Protocol")
        assert custom_pos < comm_pos

    def test_no_template_preserves_existing_behavior(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        body = self._extract_body(result)
        # Should still have all existing sections
        assert "# Agent Identity" in body
        assert "# Communication Protocol" in body
        assert "# Task Management" in body
        assert "# Shutdown Protocol" in body
        # Should NOT contain template-specific content
        assert "# Additional Instructions" not in body
        assert "# Role:" not in body

    def test_role_instructions_only_no_custom(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
            role_instructions="# Role: Tester\n\nTesting focus.",
        )
        body = self._extract_body(result)
        assert "# Role: Tester" in body
        assert "Testing focus." in body
        assert "# Additional Instructions" not in body

    def test_custom_instructions_only_no_role(self) -> None:
        result = generate_agent_config(
            agent_id="alice@team1",
            name="alice",
            team_name="team1",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
            custom_instructions="Pay attention to edge cases.",
        )
        body = self._extract_body(result)
        assert "# Additional Instructions" in body
        assert "Pay attention to edge cases." in body
        # No role instructions injected
        assert "# Role:" not in body

    def _extract_frontmatter(self, config: str) -> dict:
        """Extract and parse YAML frontmatter."""
        lines = config.split("\n")
        assert lines[0] == "---"

        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break

        assert end_idx is not None, "No closing frontmatter delimiter found"

        frontmatter_text = "\n".join(lines[1:end_idx])
        return yaml.safe_load(frontmatter_text)

    def _extract_body(self, config: str) -> str:
        """Extract the body text after frontmatter."""
        parts = config.split("\n---\n\n", 1)
        assert len(parts) == 2, "Could not split frontmatter from body"
        return parts[1]


class TestWriteAgentConfig:
    """Tests for write_agent_config() - writes config to .opencode/agents/<name>.md"""

    def test_creates_agents_directory(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config_content = "---\nmode: primary\n---\n\nTest config"

        write_agent_config(project_dir, "alice", config_content)

        agents_dir = project_dir / ".opencode" / "agents"
        assert agents_dir.exists()
        assert agents_dir.is_dir()

    def test_writes_file_with_correct_name(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config_content = "---\nmode: primary\n---\n\nTest config"

        result_path = write_agent_config(project_dir, "alice", config_content)

        expected = project_dir / ".opencode" / "agents" / "alice.md"
        assert result_path == expected
        assert result_path.exists()

    def test_writes_correct_content(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config_content = "---\nmode: primary\n---\n\nTest config"

        result_path = write_agent_config(project_dir, "alice", config_content)

        written_content = result_path.read_text(encoding="utf-8")
        assert written_content == config_content

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # First write
        config_v1 = "---\nmode: primary\n---\n\nVersion 1"
        write_agent_config(project_dir, "alice", config_v1)

        # Second write (re-spawn scenario)
        config_v2 = "---\nmode: primary\n---\n\nVersion 2"
        result_path = write_agent_config(project_dir, "alice", config_v2)

        written_content = result_path.read_text(encoding="utf-8")
        assert written_content == config_v2
        assert "Version 1" not in written_content

    def test_uses_utf8_encoding(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Config with unicode characters
        config_content = "---\nmode: primary\n---\n\n你好世界 🚀"

        result_path = write_agent_config(project_dir, "alice", config_content)

        written_content = result_path.read_text(encoding="utf-8")
        assert "你好世界" in written_content
        assert "🚀" in written_content


class TestEnsureOpencodeJson:
    """Tests for ensure_opencode_json() - creates/merges .opencode/config.json with MCP config."""

    def test_creates_new_file_when_missing(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="uv run opencode-teams",
        )

        expected = project_dir / ".opencode" / "config.json"
        assert result_path == expected
        assert result_path.exists()

    def test_new_file_has_schema_key(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="uv run opencode-teams",
        )

        content = json.loads(result_path.read_text(encoding="utf-8"))
        assert "$schema" in content

    def test_new_file_has_mcp_section(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="uv run opencode-teams",
        )

        content = json.loads(result_path.read_text(encoding="utf-8"))
        assert "mcp" in content
        assert "opencode-teams" in content["mcp"]

    def test_mcp_entry_has_correct_structure(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="uv run opencode-teams",
        )

        content = json.loads(result_path.read_text(encoding="utf-8"))
        mcp_entry = content["mcp"]["opencode-teams"]

        # OpenCode expects McpLocalConfig objects
        assert mcp_entry == {
            "type": "local",
            "command": ["uv", "run", "opencode-teams"],
        }

    def test_mcp_entry_with_complex_command(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="python -m opencode_teams.server",
        )

        content = json.loads(result_path.read_text(encoding="utf-8"))
        mcp_entry = content["mcp"]["opencode-teams"]

        assert mcp_entry == {
            "type": "local",
            "command": ["python", "-m", "opencode_teams.server"],
        }

    def test_mcp_entry_includes_environment(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="uv run opencode-teams",
            mcp_server_env={"LOG_LEVEL": "debug"},
        )

        content = json.loads(result_path.read_text(encoding="utf-8"))
        mcp_entry = content["mcp"]["opencode-teams"]

        assert mcp_entry["environment"] == {"LOG_LEVEL": "debug"}

    def test_preserves_existing_config(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create existing .opencode/config.json with other config
        opencode_dir = project_dir / ".opencode"
        opencode_dir.mkdir()
        opencode_json = opencode_dir / "config.json"
        existing = {
            "$schema": "custom-schema",
            "mcp": {
                "other-server": ["other", "command"],
            },
            "customKey": "customValue",
        }
        opencode_json.write_text(json.dumps(existing, indent=2), encoding="utf-8")

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="uv run opencode-teams",
        )

        content = json.loads(result_path.read_text(encoding="utf-8"))

        # Should preserve existing keys
        assert content["$schema"] == "custom-schema"
        assert content["customKey"] == "customValue"

        # Should preserve existing MCP entries
        assert "other-server" in content["mcp"]
        assert content["mcp"]["other-server"] == ["other", "command"]

    def test_updates_existing_opencode_teams_entry(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create existing .opencode/config.json with old opencode-teams entry
        opencode_dir = project_dir / ".opencode"
        opencode_dir.mkdir()
        opencode_json = opencode_dir / "config.json"
        existing = {
            "$schema": "schema",
            "mcp": {
                "opencode-teams": ["old", "command"],
            },
        }
        opencode_json.write_text(json.dumps(existing, indent=2), encoding="utf-8")

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="uv run opencode-teams",
        )

        content = json.loads(result_path.read_text(encoding="utf-8"))

        # Should update the entry to new McpLocalConfig
        assert content["mcp"]["opencode-teams"] == {
            "type": "local",
            "command": ["uv", "run", "opencode-teams"],
        }

    def test_creates_mcp_section_if_missing(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create existing .opencode/config.json without mcp section
        opencode_dir = project_dir / ".opencode"
        opencode_dir.mkdir()
        opencode_json = opencode_dir / "config.json"
        existing = {
            "$schema": "schema",
            "someOtherKey": "value",
        }
        opencode_json.write_text(json.dumps(existing, indent=2), encoding="utf-8")

        result_path = ensure_opencode_json(
            project_dir,
            mcp_server_command="uv run opencode-teams",
        )

        content = json.loads(result_path.read_text(encoding="utf-8"))

        # Should add mcp section
        assert "mcp" in content
        assert "opencode-teams" in content["mcp"]

        # Should preserve existing keys
        assert content["someOtherKey"] == "value"


class TestCleanupAgentConfig:
    """Tests for cleanup_agent_config() - removes .opencode/agents/<name>.md"""

    def test_removes_existing_config_file(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".opencode" / "agents"
        agents_dir.mkdir(parents=True)
        config_file = agents_dir / "alice.md"
        config_file.write_text("# Agent config")

        cleanup_agent_config(tmp_path, "alice")

        assert not config_file.exists()

    def test_noop_when_file_missing(self, tmp_path: Path) -> None:
        # Should not raise even if file doesn't exist
        cleanup_agent_config(tmp_path, "nonexistent")

    def test_noop_when_agents_dir_missing(self, tmp_path: Path) -> None:
        # Should not raise even if .opencode/agents/ doesn't exist
        cleanup_agent_config(tmp_path, "ghost")
