from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_teams import teams, messaging
from claude_teams.models import COLOR_PALETTE, TeammateMember
from claude_teams.spawner import (
    assign_color,
    build_spawn_command,
    discover_claude_binary,
    discover_opencode_binary,
    get_credential_env_var,
    get_provider_config,
    kill_tmux_pane,
    spawn_teammate,
    translate_model,
    validate_opencode_version,
    MINIMUM_OPENCODE_VERSION,
    MODEL_ALIASES,
    PROVIDER_CONFIGS,
    PROVIDER_MODEL_MAP,
)


TEAM = "test-team"
SESSION_ID = "test-session-id"


@pytest.fixture
def team_dir(tmp_claude_dir: Path) -> Path:
    teams.create_team(TEAM, session_id=SESSION_ID, base_dir=tmp_claude_dir)
    return tmp_claude_dir


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


class TestDiscoverClaudeBinary:
    @patch("claude_teams.spawner.shutil.which")
    def test_found(self, mock_which: MagicMock) -> None:
        mock_which.return_value = "/usr/local/bin/claude"
        assert discover_claude_binary() == "/usr/local/bin/claude"
        mock_which.assert_called_once_with("claude")

    @patch("claude_teams.spawner.shutil.which")
    def test_not_found(self, mock_which: MagicMock) -> None:
        mock_which.return_value = None
        with pytest.raises(FileNotFoundError):
            discover_claude_binary()


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


class TestBuildSpawnCommand:
    def test_format(self) -> None:
        member = _make_member("researcher")
        cmd = build_spawn_command(member, "/usr/local/bin/claude", "lead-sess-1")
        assert "CLAUDECODE=1" in cmd
        assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1" in cmd
        assert "/usr/local/bin/claude" in cmd
        assert "--agent-id" in cmd
        assert "--agent-name" in cmd
        assert "--team-name" in cmd
        assert "--agent-color" in cmd
        assert "--parent-session-id" in cmd
        assert "--agent-type" in cmd
        assert "--model" in cmd
        assert f"cd /tmp" in cmd
        assert "--plan-mode-required" not in cmd

    def test_with_plan_mode(self) -> None:
        member = _make_member("researcher")
        member.plan_mode_required = True
        cmd = build_spawn_command(member, "/usr/local/bin/claude", "lead-sess-1")
        assert "--plan-mode-required" in cmd


class TestSpawnTeammateNameValidation:
    def test_should_reject_empty_name(self, team_dir: Path) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            spawn_teammate(TEAM, "", "prompt", "/bin/echo", SESSION_ID, base_dir=team_dir)

    def test_should_reject_name_with_special_chars(self, team_dir: Path) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            spawn_teammate(TEAM, "agent!@#", "prompt", "/bin/echo", SESSION_ID, base_dir=team_dir)

    def test_should_reject_name_exceeding_64_chars(self, team_dir: Path) -> None:
        with pytest.raises(ValueError, match="too long"):
            spawn_teammate(TEAM, "a" * 65, "prompt", "/bin/echo", SESSION_ID, base_dir=team_dir)

    def test_should_reject_reserved_name_team_lead(self, team_dir: Path) -> None:
        with pytest.raises(ValueError, match="reserved"):
            spawn_teammate(TEAM, "team-lead", "prompt", "/bin/echo", SESSION_ID, base_dir=team_dir)


class TestSpawnTeammate:
    @patch("claude_teams.spawner.subprocess")
    def test_registers_member_before_spawn(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/claude",
            SESSION_ID,
            base_dir=team_dir,
        )
        config = teams.read_config(TEAM, base_dir=team_dir)
        names = [m.name for m in config.members]
        assert "researcher" in names

    @patch("claude_teams.spawner.subprocess")
    def test_writes_prompt_to_inbox(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/claude",
            SESSION_ID,
            base_dir=team_dir,
        )
        msgs = messaging.read_inbox(TEAM, "researcher", base_dir=team_dir)
        assert len(msgs) == 1
        assert msgs[0].from_ == "team-lead"
        assert msgs[0].text == "Do research"

    @patch("claude_teams.spawner.subprocess")
    def test_updates_pane_id(
        self, mock_subprocess: MagicMock, team_dir: Path
    ) -> None:
        mock_subprocess.run.return_value.stdout = "%42\n"
        member = spawn_teammate(
            TEAM,
            "researcher",
            "Do research",
            "/usr/local/bin/claude",
            SESSION_ID,
            base_dir=team_dir,
        )
        assert member.tmux_pane_id == "%42"
        config = teams.read_config(TEAM, base_dir=team_dir)
        found = [m for m in config.members if m.name == "researcher"]
        assert found[0].tmux_pane_id == "%42"


class TestKillTmuxPane:
    @patch("claude_teams.spawner.subprocess")
    def test_calls_subprocess(self, mock_subprocess: MagicMock) -> None:
        kill_tmux_pane("%99")
        mock_subprocess.run.assert_called_once_with(
            ["tmux", "kill-pane", "-t", "%99"], check=False
        )


# OpenCode tests


class TestDiscoverOpencodeBinary:
    @patch("claude_teams.spawner.subprocess.run")
    @patch("claude_teams.spawner.shutil.which")
    def test_found_and_valid_version(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value.stdout = "1.1.52\n"
        mock_run.return_value.stderr = ""
        assert discover_opencode_binary() == "/usr/local/bin/opencode"
        mock_which.assert_called_once_with("opencode")

    @patch("claude_teams.spawner.shutil.which")
    def test_not_found(self, mock_which: MagicMock) -> None:
        mock_which.return_value = None
        with pytest.raises(FileNotFoundError, match="opencode"):
            discover_opencode_binary()

    @patch("claude_teams.spawner.subprocess.run")
    @patch("claude_teams.spawner.shutil.which")
    def test_version_too_old(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value.stdout = "1.1.40\n"
        mock_run.return_value.stderr = ""
        with pytest.raises(RuntimeError, match="too old"):
            discover_opencode_binary()

    @patch("claude_teams.spawner.subprocess.run")
    @patch("claude_teams.spawner.shutil.which")
    def test_version_with_v_prefix(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value.stdout = "v1.1.53\n"
        mock_run.return_value.stderr = ""
        assert discover_opencode_binary() == "/usr/local/bin/opencode"

    @patch("claude_teams.spawner.subprocess.run")
    @patch("claude_teams.spawner.shutil.which")
    def test_version_with_verbose_output(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value.stdout = "opencode version v1.1.52\n"
        mock_run.return_value.stderr = ""
        assert discover_opencode_binary() == "/usr/local/bin/opencode"


class TestValidateOpencodeVersion:
    @patch("claude_teams.spawner.subprocess.run")
    def test_valid_version(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "1.1.52\n"
        mock_run.return_value.stderr = ""
        assert validate_opencode_version("/usr/local/bin/opencode") == "1.1.52"

    @patch("claude_teams.spawner.subprocess.run")
    def test_newer_version(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "2.0.0\n"
        mock_run.return_value.stderr = ""
        assert validate_opencode_version("/usr/local/bin/opencode") == "2.0.0"

    @patch("claude_teams.spawner.subprocess.run")
    def test_old_version_raises(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "1.1.49\n"
        mock_run.return_value.stderr = ""
        with pytest.raises(RuntimeError, match="too old"):
            validate_opencode_version("/usr/local/bin/opencode")

    @patch("claude_teams.spawner.subprocess.run")
    def test_unparseable_output_raises(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "unknown\n"
        mock_run.return_value.stderr = ""
        with pytest.raises(RuntimeError, match="Could not parse"):
            validate_opencode_version("/usr/local/bin/opencode")

    @patch("claude_teams.spawner.subprocess.run")
    def test_timeout_raises(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="opencode", timeout=10
        )
        with pytest.raises(RuntimeError, match="Timed out"):
            validate_opencode_version("/usr/local/bin/opencode")

    @patch("claude_teams.spawner.subprocess.run")
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
