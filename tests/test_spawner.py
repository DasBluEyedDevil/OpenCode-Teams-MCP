from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from opencode_teams import teams, messaging
from opencode_teams.models import AgentHealthStatus, COLOR_PALETTE, TeammateMember
from opencode_teams.spawner import (
    assign_color,
    build_opencode_run_command,
    capture_pane_content_hash,
    check_pane_alive,
    check_process_alive,
    check_single_agent_health,
    discover_desktop_binary,
    discover_opencode_binary,
    get_credential_env_var,
    get_provider_config,
    kill_desktop_process,
    kill_tmux_pane,
    launch_desktop_app,
    load_health_state,
    save_health_state,
    spawn_teammate,
    translate_model,
    validate_opencode_version,
    DEFAULT_GRACE_PERIOD_SECONDS,
    DEFAULT_HUNG_TIMEOUT_SECONDS,
    DESKTOP_BINARY_ENV_VAR,
    DESKTOP_BINARY_NAMES,
    DESKTOP_PATHS,
    MINIMUM_OPENCODE_VERSION,
    MODEL_ALIASES,
    PROVIDER_CONFIGS,
    PROVIDER_MODEL_MAP,
    SPAWN_TIMEOUT_SECONDS,
)


TEAM = "test-team"
SESSION_ID = "test-session-id"


@pytest.fixture
def team_dir(tmp_base_dir: Path) -> Path:
    teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)
    return tmp_base_dir


def _make_member(
    name: str,
    team: str = TEAM,
    color: str = "blue",
    model: str = "sonnet",
    agent_type: str = "general-purpose",
    cwd: str = "/tmp",
) -> TeammateMember:
    return TeammateMember(
        agent_id=f"{name}@{team}",
        name=name,
        agent_type=agent_type,
        model=model,
        prompt=f"You are {name}",
        color=color,
        joined_at=0,
        tmux_pane_id="",
        cwd=cwd,
    )


class TestAssignColor:
    def test_first_teammate_is_blue(self, team_dir: Path) -> None:
        color = assign_color(TEAM, base_dir=team_dir)
        assert color == "blue"

    def test_cycles(self, team_dir: Path) -> None:
        for i in range(len(COLOR_PALETTE)):
            member = _make_member(f"agent-{i}", color=COLOR_PALETTE[i])
            teams.add_member(TEAM, member, base_dir=team_dir)

        color = assign_color(TEAM, base_dir=team_dir)
        assert color == COLOR_PALETTE[0]


def _make_opencode_member(
    name: str = "researcher",
    team: str = TEAM,
    color: str = "blue",
    model: str = "moonshot-ai/kimi-k2.5",
    agent_type: str = "general-purpose",
    cwd: str = "/tmp",
    prompt: str = "Do research",
    plan_mode_required: bool = False,
) -> TeammateMember:
    return TeammateMember(
        agent_id=f"{name}@{team}",
        name=name,
        agent_type=agent_type,
        model=model,
        prompt=prompt,
        color=color,
        joined_at=0,
        tmux_pane_id="",
        cwd=cwd,
        plan_mode_required=plan_mode_required,
    )


class TestBuildOpencodeRunCommand:
    def test_basic_command_format(self) -> None:
        member = _make_opencode_member()
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        assert "opencode" in cmd
        assert "run" in cmd
        assert "--agent" in cmd
        assert "researcher" in cmd
        assert "--model" in cmd
        assert "moonshot-ai/kimi-k2.5" in cmd
        assert "--format json" in cmd
        assert "timeout 300" in cmd
        assert "cd" in cmd
        assert "/tmp" in cmd

    def test_prompt_is_shell_quoted(self) -> None:
        member = _make_opencode_member(prompt="Fix 'main.py' bugs")
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        # shlex.quote wraps strings with single quotes; the inner quotes
        # are escaped. The key test: no unquoted single quotes break the shell.
        assert "Fix" in cmd
        assert "main.py" in cmd
        assert "bugs" in cmd

    def test_special_chars_in_prompt(self) -> None:
        member = _make_opencode_member(prompt='Use "$HOME" and `backticks`')
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        # shlex.quote should safely wrap the prompt
        assert "$HOME" in cmd
        assert "backticks" in cmd

    def test_custom_timeout(self) -> None:
        member = _make_opencode_member()
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode", timeout_seconds=600)
        assert "timeout 600" in cmd
        assert "timeout 300" not in cmd

    def test_no_claude_flags(self) -> None:
        member = _make_opencode_member()
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        assert "--agent-id" not in cmd
        assert "--team-name" not in cmd
        assert "--parent-session-id" not in cmd
        assert "--agent-color" not in cmd
        assert "--agent-type" not in cmd
        assert "CLAUDECODE" not in cmd
        assert "CLAUDE_CODE_EXPERIMENTAL" not in cmd

    def test_no_plan_mode_flag(self) -> None:
        member = _make_opencode_member(plan_mode_required=True)
        cmd = build_opencode_run_command(member, "/usr/local/bin/opencode")
        assert "--plan-mode-required" not in cmd

    def test_default_timeout_constant(self) -> None:
        assert SPAWN_TIMEOUT_SECONDS == 300


class TestSpawnTeammateNameValidation:
    def test_should_reject_empty_name(self, team_dir: Path) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            spawn_teammate(TEAM, "", "prompt", "/bin/echo", base_dir=team_dir)

    def test_should_reject_name_with_special_chars(self, team_dir: Path) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            spawn_teammate(TEAM, "agent!@#", "prompt", "/bin/echo", base_dir=team_dir)

    def test_should_reject_name_exceeding_64_chars(self, team_dir: Path) -> None:
        with pytest.raises(ValueError, match="too long"):
            spawn_teammate(TEAM, "a" * 65, "prompt", "/bin/echo", base_dir=team_dir)

    def test_should_reject_reserved_name_team_lead(self, team_dir: Path) -> None:
        with pytest.raises(ValueError, match="reserved"):
            spawn_teammate(TEAM, "team-lead", "prompt", "/bin/echo", base_dir=team_dir)


class TestSpawnTeammate:
    @patch("opencode_teams.spawner.subprocess")
    def test_registers_member_before_spawn(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/claude",
            base_dir=team_dir,
        )
        config = teams.read_config(TEAM, base_dir=team_dir)
        names = [m.name for m in config.members]
        assert "researcher" in names

    @patch("opencode_teams.spawner.subprocess")
    def test_writes_prompt_to_inbox(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/claude",
            base_dir=team_dir,
        )
        msgs = messaging.read_inbox(TEAM, "researcher", base_dir=team_dir)
        assert len(msgs) == 1
        assert msgs[0].from_ == "team-lead"
        assert msgs[0].text == "Do research"

    @patch("opencode_teams.spawner.subprocess")
    def test_updates_pane_id(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        member = spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/opencode",
            base_dir=team_dir,
        )
        assert member.tmux_pane_id == "%42"
        config = teams.read_config(TEAM, base_dir=team_dir)
        found = [m for m in config.members if m.name == "researcher"]
        assert found[0].tmux_pane_id == "%42"

    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_uses_opencode_command(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        """Verify spawn_teammate calls tmux with opencode run command, not Claude flags."""
        mock_subprocess.run.return_value.stdout = "%42\n"
        spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/opencode",
            base_dir=team_dir,
        )
        # Get the tmux command string (last positional arg to subprocess.run)
        call_args = mock_subprocess.run.call_args[0][0]
        tmux_cmd = call_args[-1]  # The shell command passed to tmux split-window
        assert "opencode" in tmux_cmd
        assert "run" in tmux_cmd
        assert "CLAUDECODE" not in tmux_cmd


class TestSpawnWithTemplate:
    """Tests for template wiring in spawn flow (role_instructions, custom_instructions)."""

    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_passes_role_instructions_to_config_gen(
        self, mock_subprocess: MagicMock, tmp_base_dir: Path, tmp_path: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/opencode",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
            model="moonshot-ai/kimi-k2.5",
            role_instructions="# Role: Tester\n\nTest stuff.",
        )

        config_file = project_dir / ".opencode" / "agents" / "researcher.md"
        assert config_file.exists()
        content = config_file.read_text()
        assert "# Role: Tester" in content

    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_passes_custom_instructions_to_config_gen(
        self, mock_subprocess: MagicMock, tmp_base_dir: Path, tmp_path: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        spawn_teammate(
            TEAM,
            "worker",
            "Do work",
            "/usr/local/bin/opencode",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
            model="moonshot-ai/kimi-k2.5",
            custom_instructions="Focus on edge cases.",
        )

        config_file = project_dir / ".opencode" / "agents" / "worker.md"
        assert config_file.exists()
        content = config_file.read_text()
        assert "Focus on edge cases." in content

    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_without_template_produces_clean_config(
        self, mock_subprocess: MagicMock, tmp_base_dir: Path, tmp_path: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        spawn_teammate(
            TEAM,
            "generic",
            "Do generic work",
            "/usr/local/bin/opencode",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
            model="moonshot-ai/kimi-k2.5",
        )

        config_file = project_dir / ".opencode" / "agents" / "generic.md"
        assert config_file.exists()
        content = config_file.read_text()
        assert "# Role:" not in content
        assert "# Additional Instructions" not in content

    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_with_both_role_and_custom_instructions(
        self, mock_subprocess: MagicMock, tmp_base_dir: Path, tmp_path: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        spawn_teammate(
            TEAM,
            "hybrid",
            "Do hybrid work",
            "/usr/local/bin/opencode",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
            model="moonshot-ai/kimi-k2.5",
            role_instructions="# Role: Tester\n\nTest everything.",
            custom_instructions="Focus on performance tests.",
        )

        config_file = project_dir / ".opencode" / "agents" / "hybrid.md"
        assert config_file.exists()
        content = config_file.read_text()
        assert "# Role: Tester" in content
        assert "Focus on performance tests." in content
        # Role instructions should appear before custom instructions
        role_pos = content.index("# Role: Tester")
        custom_pos = content.index("# Additional Instructions")
        comm_pos = content.index("# Communication Protocol")
        assert role_pos < custom_pos < comm_pos


class TestKillTmuxPane:
    @patch("opencode_teams.spawner.subprocess")
    def test_calls_subprocess(self, mock_subprocess: MagicMock) -> None:
        kill_tmux_pane("%99")
        mock_subprocess.run.assert_called_once_with(
            ["tmux", "kill-pane", "-t", "%99"], check=False
        )


# OpenCode tests


class TestDiscoverOpencodeBinary:
    @patch("opencode_teams.spawner.subprocess.run")
    @patch("opencode_teams.spawner.shutil.which")
    def test_found_and_valid_version(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value.stdout = "1.1.52\n"
        mock_run.return_value.stderr = ""
        assert discover_opencode_binary() == "/usr/local/bin/opencode"
        mock_which.assert_called_once_with("opencode")

    @patch("opencode_teams.spawner.shutil.which")
    def test_not_found(self, mock_which: MagicMock) -> None:
        mock_which.return_value = None
        with pytest.raises(FileNotFoundError, match="opencode"):
            discover_opencode_binary()

    @patch("opencode_teams.spawner.subprocess.run")
    @patch("opencode_teams.spawner.shutil.which")
    def test_version_too_old(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value.stdout = "1.1.40\n"
        mock_run.return_value.stderr = ""
        with pytest.raises(RuntimeError, match="too old"):
            discover_opencode_binary()

    @patch("opencode_teams.spawner.subprocess.run")
    @patch("opencode_teams.spawner.shutil.which")
    def test_version_with_v_prefix(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value.stdout = "v1.1.53\n"
        mock_run.return_value.stderr = ""
        assert discover_opencode_binary() == "/usr/local/bin/opencode"

    @patch("opencode_teams.spawner.subprocess.run")
    @patch("opencode_teams.spawner.shutil.which")
    def test_version_with_verbose_output(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value.stdout = "opencode version v1.1.52\n"
        mock_run.return_value.stderr = ""
        assert discover_opencode_binary() == "/usr/local/bin/opencode"


class TestValidateOpencodeVersion:
    @patch("opencode_teams.spawner.subprocess.run")
    def test_valid_version(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "1.1.52\n"
        mock_run.return_value.stderr = ""
        assert validate_opencode_version("/usr/local/bin/opencode") == "1.1.52"

    @patch("opencode_teams.spawner.subprocess.run")
    def test_newer_version(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "2.0.0\n"
        mock_run.return_value.stderr = ""
        assert validate_opencode_version("/usr/local/bin/opencode") == "2.0.0"

    @patch("opencode_teams.spawner.subprocess.run")
    def test_old_version_raises(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "1.1.49\n"
        mock_run.return_value.stderr = ""
        with pytest.raises(RuntimeError, match="too old"):
            validate_opencode_version("/usr/local/bin/opencode")

    @patch("opencode_teams.spawner.subprocess.run")
    def test_unparseable_output_raises(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "unknown\n"
        mock_run.return_value.stderr = ""
        with pytest.raises(RuntimeError, match="Could not parse"):
            validate_opencode_version("/usr/local/bin/opencode")

    @patch("opencode_teams.spawner.subprocess.run")
    def test_timeout_raises(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="opencode", timeout=10
        )
        with pytest.raises(RuntimeError, match="Timed out"):
            validate_opencode_version("/usr/local/bin/opencode")

    @patch("opencode_teams.spawner.subprocess.run")
    def test_binary_not_found_raises(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError
        with pytest.raises(RuntimeError):
            validate_opencode_version("/usr/local/bin/opencode")


class TestTranslateModel:
    def test_sonnet_moonshot(self) -> None:
        assert translate_model("sonnet", "moonshot-ai") == "moonshot-ai/kimi-k2.5"

    def test_opus_moonshot(self) -> None:
        assert translate_model("opus", "moonshot-ai") == "moonshot-ai/kimi-k2.5"

    def test_haiku_openrouter(self) -> None:
        assert (
            translate_model("haiku", "openrouter")
            == "openrouter/moonshotai/kimi-k2.5"
        )

    def test_sonnet_novita(self) -> None:
        assert translate_model("sonnet", "novita") == "novita/moonshotai/kimi-k2.5"

    def test_passthrough_provider_model(self) -> None:
        assert (
            translate_model("moonshot-ai/kimi-k2.5") == "moonshot-ai/kimi-k2.5"
        )

    def test_passthrough_arbitrary(self) -> None:
        assert translate_model("custom/my-model") == "custom/my-model"

    def test_unknown_alias_as_model_name(self) -> None:
        assert translate_model("kimi-k2.5", "moonshot-ai") == "moonshot-ai/kimi-k2.5"

    def test_default_provider(self) -> None:
        assert translate_model("sonnet") == "moonshot-ai/kimi-k2.5"


class TestGetProviderConfig:
    def test_moonshot_ai(self) -> None:
        result = get_provider_config("moonshot-ai")
        assert "moonshot-ai" in result
        assert result["moonshot-ai"]["apiKey"] == "{env:MOONSHOT_API_KEY}"

    def test_openrouter(self) -> None:
        result = get_provider_config("openrouter")
        assert result["openrouter"]["apiKey"] == "{env:OPENROUTER_API_KEY}"

    def test_novita_has_base_url(self) -> None:
        result = get_provider_config("novita")
        assert (
            result["novita"]["options"]["baseURL"]
            == "https://api.novita.ai/openai"
        )

    def test_novita_has_npm_package(self) -> None:
        result = get_provider_config("novita")
        assert "npm" in result["novita"]

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider_config("unknown-provider")

    def test_no_hardcoded_keys(self) -> None:
        for provider in PROVIDER_CONFIGS.keys():
            result = get_provider_config(provider)
            result_str = str(result)
            assert "sk-" not in result_str
            assert "{env:" in result_str


class TestGetCredentialEnvVar:
    def test_moonshot(self) -> None:
        assert get_credential_env_var("moonshot-ai") == "MOONSHOT_API_KEY"

    def test_openrouter(self) -> None:
        assert get_credential_env_var("openrouter") == "OPENROUTER_API_KEY"

    def test_novita(self) -> None:
        assert get_credential_env_var("novita") == "NOVITA_API_KEY"

    def test_unknown_fallback(self) -> None:
        assert get_credential_env_var("my-custom") == "MY_CUSTOM_API_KEY"


class TestConfigGenIntegration:
    """Integration tests for config generation wiring in spawn flow."""

    @patch("opencode_teams.spawner.validate_opencode_version")
    @patch("opencode_teams.spawner.shutil.which")
    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_generates_agent_config(
        self, mock_subprocess: MagicMock, mock_which: MagicMock,
        mock_validate: MagicMock, tmp_base_dir: Path, tmp_path: Path
    ) -> None:
        """Verify spawn_teammate generates .opencode/agents/<name>.md"""
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_validate.return_value = "1.1.52"
        mock_subprocess.run.return_value.stdout = "%42\n"

        # Create team using tmp_base_dir for team data
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)

        # Use tmp_path as project_dir for config files
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/opencode",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
            model="moonshot-ai/kimi-k2.5",
        )

        # Verify agent config file exists
        config_file = project_dir / ".opencode" / "agents" / "researcher.md"
        assert config_file.exists()

        # Verify content has expected YAML frontmatter
        content = config_file.read_text()
        assert "mode: primary" in content
        assert "permission: allow" in content
        assert "researcher" in content
        assert TEAM in content

    @patch("opencode_teams.spawner.validate_opencode_version")
    @patch("opencode_teams.spawner.shutil.which")
    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_creates_opencode_config_json(
        self, mock_subprocess: MagicMock, mock_which: MagicMock,
        mock_validate: MagicMock, tmp_base_dir: Path, tmp_path: Path
    ) -> None:
        """Verify spawn_teammate creates .opencode/config.json with MCP server entry"""
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_validate.return_value = "1.1.52"
        mock_subprocess.run.return_value.stdout = "%43\n"

        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)

        project_dir = tmp_path / "project2"
        project_dir.mkdir()

        spawn_teammate(
            TEAM,
            "worker",
            "Do work",
            "/usr/local/bin/opencode",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
        )

        # Verify .opencode/config.json exists
        opencode_json = project_dir / ".opencode" / "config.json"
        assert opencode_json.exists()

        # Verify content has opencode-teams MCP entry as McpLocalConfig
        import json
        content = json.loads(opencode_json.read_text())
        assert "mcp" in content
        assert "opencode-teams" in content["mcp"]
        # OpenCode expects MCP entries as McpLocalConfig objects
        mcp_entry = content["mcp"]["opencode-teams"]
        assert mcp_entry["type"] == "local"
        assert mcp_entry["command"] == ["uv", "run", "opencode-teams"]

    def test_cleanup_agent_config_removes_file(self, tmp_path: Path) -> None:
        """Verify cleanup_agent_config removes the config file"""
        from opencode_teams.spawner import cleanup_agent_config

        # Create fake agent config file
        agents_dir = tmp_path / ".opencode" / "agents"
        agents_dir.mkdir(parents=True)
        config_file = agents_dir / "test-agent.md"
        config_file.write_text("# Test config")

        assert config_file.exists()

        # Call cleanup
        cleanup_agent_config(tmp_path, "test-agent")

        # Verify file is gone
        assert not config_file.exists()

    def test_cleanup_agent_config_noop_if_missing(self, tmp_path: Path) -> None:
        """Verify cleanup_agent_config doesn't error if file doesn't exist"""
        from opencode_teams.spawner import cleanup_agent_config

        # Call cleanup on nonexistent file - should not raise
        cleanup_agent_config(tmp_path, "nonexistent")

        # No assertion needed - test passes if no exception raised


# Agent health detection tests


class TestCheckPaneAlive:
    @patch("opencode_teams.spawner.subprocess.run")
    def test_returns_true_for_alive_pane(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "0\n"
        mock_run.return_value.returncode = 0
        assert check_pane_alive("%42") is True

    @patch("opencode_teams.spawner.subprocess.run")
    def test_returns_false_for_dead_pane(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "1\n"
        mock_run.return_value.returncode = 0
        assert check_pane_alive("%42") is False

    @patch("opencode_teams.spawner.subprocess.run")
    def test_returns_false_for_missing_pane(self, mock_run: MagicMock) -> None:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        assert check_pane_alive("%42") is False

    def test_returns_false_for_empty_pane_id(self) -> None:
        # No subprocess call should be made
        assert check_pane_alive("") is False

    @patch("opencode_teams.spawner.subprocess.run")
    def test_returns_false_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tmux", timeout=5)
        assert check_pane_alive("%42") is False

    @patch("opencode_teams.spawner.subprocess.run")
    def test_returns_false_when_tmux_not_installed(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError
        assert check_pane_alive("%42") is False


class TestCapturePaneContentHash:
    @patch("opencode_teams.spawner.subprocess.run")
    def test_returns_hash_for_live_pane(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "some output\n"
        mock_run.return_value.returncode = 0
        result = capture_pane_content_hash("%42")
        assert result is not None
        assert len(result) == 64  # SHA-256 hex digest length
        assert all(c in "0123456789abcdef" for c in result)

    @patch("opencode_teams.spawner.subprocess.run")
    def test_returns_none_for_failed_capture(self, mock_run: MagicMock) -> None:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        assert capture_pane_content_hash("%42") is None

    def test_returns_none_for_empty_pane_id(self) -> None:
        assert capture_pane_content_hash("") is None

    @patch("opencode_teams.spawner.subprocess.run")
    def test_returns_none_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tmux", timeout=5)
        assert capture_pane_content_hash("%42") is None

    @patch("opencode_teams.spawner.subprocess.run")
    def test_same_content_produces_same_hash(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "deterministic content"
        mock_run.return_value.returncode = 0
        hash1 = capture_pane_content_hash("%42")
        hash2 = capture_pane_content_hash("%42")
        assert hash1 == hash2

    @patch("opencode_teams.spawner.subprocess.run")
    def test_different_content_produces_different_hash(self, mock_run: MagicMock) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "content A"
        hash_a = capture_pane_content_hash("%42")
        mock_run.return_value.stdout = "content B"
        hash_b = capture_pane_content_hash("%42")
        assert hash_a != hash_b


class TestCheckSingleAgentHealth:
    @patch("opencode_teams.spawner.capture_pane_content_hash")
    @patch("opencode_teams.spawner.check_pane_alive")
    def test_dead_when_pane_missing(
        self, mock_alive: MagicMock, mock_hash: MagicMock
    ) -> None:
        mock_alive.return_value = False
        member = _make_opencode_member(name="worker", prompt="Do work")
        member.joined_at = int(time.time() * 1000) - 120_000
        member.tmux_pane_id = "%42"
        result = check_single_agent_health(member, None, None)
        assert result.status == "dead"
        assert result.agent_name == "worker"
        assert result.pane_id == "%42"

    @patch("opencode_teams.spawner.capture_pane_content_hash")
    @patch("opencode_teams.spawner.check_pane_alive")
    def test_alive_when_pane_exists_and_content_changes(
        self, mock_alive: MagicMock, mock_hash: MagicMock
    ) -> None:
        mock_alive.return_value = True
        mock_hash.return_value = "newhash"
        member = _make_opencode_member(name="worker", prompt="Do work")
        member.joined_at = int(time.time() * 1000) - 120_000
        member.tmux_pane_id = "%42"
        result = check_single_agent_health(member, "oldhash", time.time() - 10)
        assert result.status == "alive"
        assert result.last_content_hash == "newhash"

    @patch("opencode_teams.spawner.capture_pane_content_hash")
    @patch("opencode_teams.spawner.check_pane_alive")
    def test_hung_when_content_unchanged_beyond_timeout(
        self, mock_alive: MagicMock, mock_hash: MagicMock
    ) -> None:
        mock_alive.return_value = True
        mock_hash.return_value = "samehash"
        member = _make_opencode_member(name="worker", prompt="Do work")
        member.joined_at = int(time.time() * 1000) - 120_000
        member.tmux_pane_id = "%42"
        result = check_single_agent_health(
            member, "samehash", time.time() - 130
        )
        assert result.status == "hung"

    @patch("opencode_teams.spawner.capture_pane_content_hash")
    @patch("opencode_teams.spawner.check_pane_alive")
    def test_alive_during_grace_period(
        self, mock_alive: MagicMock, mock_hash: MagicMock
    ) -> None:
        mock_alive.return_value = True
        mock_hash.return_value = "samehash"
        # 5 seconds ago -- well within default 60s grace period
        member = _make_opencode_member(name="worker", prompt="Do work")
        member.joined_at = int(time.time() * 1000) - 5_000
        member.tmux_pane_id = "%42"
        result = check_single_agent_health(
            member, "samehash", time.time() - 130
        )
        assert result.status == "alive"
        assert "grace" in result.detail.lower()

    @patch("opencode_teams.spawner.capture_pane_content_hash")
    @patch("opencode_teams.spawner.check_pane_alive")
    def test_unknown_when_capture_fails(
        self, mock_alive: MagicMock, mock_hash: MagicMock
    ) -> None:
        mock_alive.return_value = True
        mock_hash.return_value = None
        member = _make_opencode_member(name="worker", prompt="Do work")
        member.joined_at = int(time.time() * 1000) - 120_000
        member.tmux_pane_id = "%42"
        result = check_single_agent_health(member, None, None)
        assert result.status == "unknown"

    @patch("opencode_teams.spawner.capture_pane_content_hash")
    @patch("opencode_teams.spawner.check_pane_alive")
    def test_alive_when_content_unchanged_within_timeout(
        self, mock_alive: MagicMock, mock_hash: MagicMock
    ) -> None:
        mock_alive.return_value = True
        mock_hash.return_value = "samehash"
        member = _make_opencode_member(name="worker", prompt="Do work")
        member.joined_at = int(time.time() * 1000) - 120_000
        member.tmux_pane_id = "%42"
        # Only 30s elapsed -- below 120s threshold
        result = check_single_agent_health(
            member, "samehash", time.time() - 30
        )
        assert result.status == "alive"


class TestHealthStatePersistence:
    def test_load_empty_state_when_no_file(self, team_dir: Path) -> None:
        result = load_health_state(TEAM, base_dir=team_dir)
        assert result == {}

    def test_save_and_load_round_trip(self, team_dir: Path) -> None:
        state = {
            "worker": {
                "hash": "abc123",
                "last_change_time": 1700000000.0,
            }
        }
        save_health_state(TEAM, state, base_dir=team_dir)
        loaded = load_health_state(TEAM, base_dir=team_dir)
        assert loaded["worker"]["hash"] == "abc123"
        assert loaded["worker"]["last_change_time"] == 1700000000.0

    def test_save_overwrites_previous(self, team_dir: Path) -> None:
        state1 = {"worker": {"hash": "old", "last_change_time": 1.0}}
        save_health_state(TEAM, state1, base_dir=team_dir)

        state2 = {"worker": {"hash": "new", "last_change_time": 2.0}}
        save_health_state(TEAM, state2, base_dir=team_dir)

        loaded = load_health_state(TEAM, base_dir=team_dir)
        assert loaded["worker"]["hash"] == "new"
        assert loaded["worker"]["last_change_time"] == 2.0


# Desktop app lifecycle tests


class TestDesktopDiscovery:
    def test_env_var_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_binary = tmp_path / "opencode-desktop"
        fake_binary.write_text("fake")
        monkeypatch.setenv(DESKTOP_BINARY_ENV_VAR, str(fake_binary))
        result = discover_desktop_binary()
        assert result == str(fake_binary)

    def test_env_var_override_missing_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DESKTOP_BINARY_ENV_VAR, "/nonexistent/path/opencode-desktop")
        with pytest.raises(FileNotFoundError, match="does not exist"):
            discover_desktop_binary()

    def test_known_path_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_binary = tmp_path / "opencode-desktop"
        fake_binary.write_text("fake")
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            "opencode_teams.spawner.DESKTOP_PATHS",
            {"linux": [str(fake_binary)]},
        )
        monkeypatch.delenv(DESKTOP_BINARY_ENV_VAR, raising=False)
        result = discover_desktop_binary()
        assert result == str(fake_binary)

    def test_path_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("opencode_teams.spawner.DESKTOP_PATHS", {"linux": []})
        monkeypatch.setattr(
            "opencode_teams.spawner.shutil.which",
            lambda name: "/usr/local/bin/opencode-desktop" if name == "opencode-desktop" else None,
        )
        monkeypatch.delenv(DESKTOP_BINARY_ENV_VAR, raising=False)
        result = discover_desktop_binary()
        assert result == "/usr/local/bin/opencode-desktop"

    def test_not_found_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("opencode_teams.spawner.DESKTOP_PATHS", {"linux": []})
        monkeypatch.setattr("opencode_teams.spawner.shutil.which", lambda name: None)
        monkeypatch.delenv(DESKTOP_BINARY_ENV_VAR, raising=False)
        with pytest.raises(FileNotFoundError, match="Could not find OpenCode Desktop"):
            discover_desktop_binary()


class TestDesktopLaunch:
    def test_launch_returns_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_popen = MagicMock()
        mock_popen.pid = 12345
        mock_popen_cls = MagicMock(return_value=mock_popen)
        monkeypatch.setattr("opencode_teams.spawner.subprocess.Popen", mock_popen_cls)
        monkeypatch.setattr(sys, "platform", "linux")

        result = launch_desktop_app("/usr/bin/opencode-desktop", "/tmp/project")
        assert result == 12345
        mock_popen_cls.assert_called_once_with(
            ["/usr/bin/opencode-desktop"],
            cwd="/tmp/project",
            start_new_session=True,
        )

    def test_launch_windows_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_popen = MagicMock()
        mock_popen.pid = 99999
        mock_popen_cls = MagicMock(return_value=mock_popen)
        monkeypatch.setattr("opencode_teams.spawner.subprocess.Popen", mock_popen_cls)
        monkeypatch.setattr(sys, "platform", "win32")

        result = launch_desktop_app("/usr/bin/opencode-desktop", "/tmp/project")
        assert result == 99999
        call_kwargs = mock_popen_cls.call_args[1]
        expected_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        assert call_kwargs["creationflags"] == expected_flags
        assert "start_new_session" not in call_kwargs


class TestProcessLifecycle:
    def test_check_alive_with_running_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("opencode_teams.spawner.os.kill", lambda pid, sig: None)
        assert check_process_alive(1234) is True

    def test_check_alive_with_dead_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_os_error(pid: int, sig: int) -> None:
            raise OSError("No such process")
        monkeypatch.setattr("opencode_teams.spawner.os.kill", raise_os_error)
        assert check_process_alive(1234) is False

    def test_check_alive_with_zero_pid(self) -> None:
        assert check_process_alive(0) is False

    def test_check_alive_with_negative_pid(self) -> None:
        assert check_process_alive(-1) is False

    def test_kill_desktop_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_kill = MagicMock()
        monkeypatch.setattr("opencode_teams.spawner.os.kill", mock_kill)
        kill_desktop_process(5678)
        mock_kill.assert_called_once_with(5678, signal.SIGTERM)

    def test_kill_desktop_process_already_dead(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_os_error(pid: int, sig: int) -> None:
            raise OSError("No such process")
        monkeypatch.setattr("opencode_teams.spawner.os.kill", raise_os_error)
        # Should not raise
        kill_desktop_process(5678)

    def test_kill_desktop_process_zero_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_kill = MagicMock()
        monkeypatch.setattr("opencode_teams.spawner.os.kill", mock_kill)
        kill_desktop_process(0)
        mock_kill.assert_not_called()


class TestSpawnDesktopBackend:
    @patch("opencode_teams.spawner.launch_desktop_app", return_value=9999)
    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_desktop_calls_launch_desktop_app(
        self, mock_subprocess: MagicMock, mock_launch: MagicMock,
        tmp_base_dir: Path, tmp_path: Path,
    ) -> None:
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        member = spawn_teammate(
            TEAM, "desktop-agent", "Do work",
            "/usr/local/bin/opencode",
            backend_type="desktop",
            desktop_binary="/fake/opencode-desktop",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
        )
        mock_launch.assert_called_once()
        assert mock_launch.call_args[0][0] == "/fake/opencode-desktop"
        assert member.process_id == 9999
        assert member.backend_type == "desktop"

    def test_spawn_desktop_requires_desktop_binary(
        self, tmp_base_dir: Path, tmp_path: Path,
    ) -> None:
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        with pytest.raises(ValueError, match="desktop_binary is required"):
            spawn_teammate(
                TEAM, "desktop-agent", "Do work",
                "/usr/local/bin/opencode",
                backend_type="desktop",
                base_dir=tmp_base_dir,
                project_dir=project_dir,
            )

    @patch("opencode_teams.spawner.launch_desktop_app", return_value=8888)
    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_desktop_stores_pid_in_config(
        self, mock_subprocess: MagicMock, mock_launch: MagicMock,
        tmp_base_dir: Path, tmp_path: Path,
    ) -> None:
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        spawn_teammate(
            TEAM, "desktop-agent", "Do work",
            "/usr/local/bin/opencode",
            backend_type="desktop",
            desktop_binary="/fake/opencode-desktop",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
        )
        config = teams.read_config(TEAM, base_dir=tmp_base_dir)
        found = [m for m in config.members if isinstance(m, TeammateMember) and m.name == "desktop-agent"]
        assert len(found) == 1
        assert found[0].process_id == 8888
        assert found[0].backend_type == "desktop"

    @patch("opencode_teams.spawner.subprocess")
    def test_spawn_tmux_still_works(
        self, mock_subprocess: MagicMock,
        tmp_base_dir: Path, tmp_path: Path,
    ) -> None:
        teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_base_dir)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        mock_subprocess.run.return_value.stdout = "%42\n"
        member = spawn_teammate(
            TEAM, "tmux-agent", "Do work",
            "/usr/local/bin/opencode",
            backend_type="tmux",
            base_dir=tmp_base_dir,
            project_dir=project_dir,
        )
        mock_subprocess.run.assert_called_once()
        call_args = mock_subprocess.run.call_args[0][0]
        assert "tmux" in call_args[0]
        assert member.tmux_pane_id == "%42"
        assert member.backend_type == "tmux"


class TestDesktopHealthCheck:
    def test_desktop_alive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        member = TeammateMember(
            agent_id="agent@team", name="agent", agent_type="general-purpose",
            model="kimi-k2.5", prompt="work", color="blue", joined_at=0,
            tmux_pane_id="", cwd="/tmp", backend_type="desktop", process_id=1234,
        )
        monkeypatch.setattr("opencode_teams.spawner.check_process_alive", lambda pid: True)
        result = check_single_agent_health(member, None, None)
        assert result.status == "alive"
        assert "running" in result.detail

    def test_desktop_dead(self, monkeypatch: pytest.MonkeyPatch) -> None:
        member = TeammateMember(
            agent_id="agent@team", name="agent", agent_type="general-purpose",
            model="kimi-k2.5", prompt="work", color="blue", joined_at=0,
            tmux_pane_id="", cwd="/tmp", backend_type="desktop", process_id=1234,
        )
        monkeypatch.setattr("opencode_teams.spawner.check_process_alive", lambda pid: False)
        result = check_single_agent_health(member, None, None)
        assert result.status == "dead"
        assert "no longer running" in result.detail

    def test_desktop_never_reports_hung(self, monkeypatch: pytest.MonkeyPatch) -> None:
        member = TeammateMember(
            agent_id="agent@team", name="agent", agent_type="general-purpose",
            model="kimi-k2.5", prompt="work", color="blue", joined_at=0,
            tmux_pane_id="", cwd="/tmp", backend_type="desktop", process_id=1234,
        )
        monkeypatch.setattr("opencode_teams.spawner.check_process_alive", lambda pid: True)
        # Simulate conditions that would trigger "hung" for tmux backend
        result = check_single_agent_health(
            member, "samehash", time.time() - 300, hung_timeout=120,
        )
        assert result.status == "alive"
        assert result.status != "hung"
