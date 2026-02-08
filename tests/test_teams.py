from __future__ import annotations

import json
import time
import unittest.mock
from pathlib import Path

import pytest

from opencode_teams.models import LeadMember, TeamConfig, TeammateMember
from opencode_teams.teams import (
    add_member,
    create_team,
    delete_team,
    get_project_dir,
    read_config,
    remove_member,
    write_config,
)


def _make_teammate(name: str, team_name: str) -> TeammateMember:
    return TeammateMember(
        agent_id=f"{name}@{team_name}",
        name=name,
        agent_type="teammate",
        model="moonshot-ai/kimi-k2.5",
        prompt="Do stuff",
        color="blue",
        plan_mode_required=False,
        joined_at=int(time.time() * 1000),
        tmux_pane_id="%1",
        cwd="/tmp",
    )


class TestCreateTeam:
    def test_create_team_produces_correct_directory_structure(self, tmp_base_dir: Path) -> None:
        result = create_team("alpha", "sess-1", base_dir=tmp_base_dir)

        assert (tmp_base_dir / "teams" / "alpha").is_dir()
        assert (tmp_base_dir / "tasks" / "alpha").is_dir()
        assert (tmp_base_dir / "tasks" / "alpha" / ".lock").exists()
        assert not (tmp_base_dir / "teams" / "alpha" / "inboxes").exists()

    def test_create_team_config_has_correct_schema(self, tmp_base_dir: Path) -> None:
        create_team("beta", "sess-42", description="test team", base_dir=tmp_base_dir)

        raw = json.loads((tmp_base_dir / "teams" / "beta" / "config.json").read_text())

        assert raw["name"] == "beta"
        assert raw["description"] == "test team"
        assert raw["leadSessionId"] == "sess-42"
        assert raw["leadAgentId"] == "team-lead@beta"
        assert "createdAt" in raw
        assert isinstance(raw["createdAt"], int)
        assert isinstance(raw["members"], list)
        assert len(raw["members"]) == 1

    def test_create_team_lead_member_shape(self, tmp_base_dir: Path) -> None:
        create_team("gamma", "sess-7", base_dir=tmp_base_dir)

        raw = json.loads((tmp_base_dir / "teams" / "gamma" / "config.json").read_text())
        lead = raw["members"][0]

        assert lead["agentId"] == "team-lead@gamma"
        assert lead["name"] == "team-lead"
        assert lead["agentType"] == "team-lead"
        assert lead["tmuxPaneId"] == ""
        assert lead["subscriptions"] == []

    def test_create_team_rejects_invalid_names(self, tmp_base_dir: Path) -> None:
        for bad_name in ["has space", "has.dot", "has/slash", "has\\back"]:
            with pytest.raises(ValueError):
                create_team(bad_name, "sess-x", base_dir=tmp_base_dir)

    def test_should_reject_name_exceeding_max_length(self, tmp_base_dir: Path) -> None:
        with pytest.raises(ValueError, match="too long"):
            create_team("a" * 65, "sess-x", base_dir=tmp_base_dir)

    def test_should_accept_name_at_max_length(self, tmp_base_dir: Path) -> None:
        result = create_team("a" * 64, "sess-x", base_dir=tmp_base_dir)
        assert result.team_name == "a" * 64


class TestDeleteTeam:
    def test_delete_team_removes_directories(self, tmp_base_dir: Path) -> None:
        create_team("doomed", "sess-1", base_dir=tmp_base_dir)
        result = delete_team("doomed", base_dir=tmp_base_dir)

        assert result.success is True
        assert result.team_name == "doomed"
        assert not (tmp_base_dir / "teams" / "doomed").exists()
        assert not (tmp_base_dir / "tasks" / "doomed").exists()

    def test_delete_team_fails_with_active_members(self, tmp_base_dir: Path) -> None:
        create_team("busy", "sess-1", base_dir=tmp_base_dir)
        mate = _make_teammate("worker", "busy")
        add_member("busy", mate, base_dir=tmp_base_dir)

        with pytest.raises(RuntimeError):
            delete_team("busy", base_dir=tmp_base_dir)


class TestMembers:
    def test_add_member_appends_to_config(self, tmp_base_dir: Path) -> None:
        create_team("squad", "sess-1", base_dir=tmp_base_dir)
        mate = _make_teammate("coder", "squad")
        add_member("squad", mate, base_dir=tmp_base_dir)

        cfg = read_config("squad", base_dir=tmp_base_dir)
        assert len(cfg.members) == 2
        assert cfg.members[1].name == "coder"

    def test_remove_member_filters_from_config(self, tmp_base_dir: Path) -> None:
        create_team("squad2", "sess-1", base_dir=tmp_base_dir)
        mate = _make_teammate("temp", "squad2")
        add_member("squad2", mate, base_dir=tmp_base_dir)
        remove_member("squad2", "temp", base_dir=tmp_base_dir)

        cfg = read_config("squad2", base_dir=tmp_base_dir)
        assert len(cfg.members) == 1
        assert cfg.members[0].name == "team-lead"


class TestDuplicateMember:
    def test_should_reject_duplicate_member_name(self, tmp_base_dir: Path) -> None:
        create_team("dup", "sess-1", base_dir=tmp_base_dir)
        mate = _make_teammate("worker", "dup")
        add_member("dup", mate, base_dir=tmp_base_dir)
        mate2 = _make_teammate("worker", "dup")
        with pytest.raises(ValueError, match="already exists"):
            add_member("dup", mate2, base_dir=tmp_base_dir)

    def test_should_allow_member_after_removal(self, tmp_base_dir: Path) -> None:
        create_team("reuse", "sess-1", base_dir=tmp_base_dir)
        mate = _make_teammate("worker", "reuse")
        add_member("reuse", mate, base_dir=tmp_base_dir)
        remove_member("reuse", "worker", base_dir=tmp_base_dir)
        mate2 = _make_teammate("worker", "reuse")
        add_member("reuse", mate2, base_dir=tmp_base_dir)
        cfg = read_config("reuse", base_dir=tmp_base_dir)
        assert any(m.name == "worker" for m in cfg.members)


class TestWriteConfig:
    def test_should_cleanup_temp_file_when_replace_fails(self, tmp_base_dir: Path) -> None:
        create_team("atomic", "sess-1", base_dir=tmp_base_dir)
        config = read_config("atomic", base_dir=tmp_base_dir)
        config.description = "updated"

        config_dir = tmp_base_dir / "teams" / "atomic"

        with unittest.mock.patch("os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                write_config("atomic", config, base_dir=tmp_base_dir)

        tmp_files = list(config_dir.glob("*.tmp"))
        assert tmp_files == [], f"Leaked temp files: {tmp_files}"


class TestTeamExists:
    def test_should_return_true_for_existing_team(self, tmp_base_dir: Path) -> None:
        from opencode_teams.teams import team_exists
        create_team("exists", "sess-1", base_dir=tmp_base_dir)
        assert team_exists("exists", base_dir=tmp_base_dir) is True

    def test_should_return_false_for_nonexistent_team(self, tmp_base_dir: Path) -> None:
        from opencode_teams.teams import team_exists
        assert team_exists("ghost", base_dir=tmp_base_dir) is False


class TestRemoveMemberGuard:
    def test_should_reject_removing_team_lead(self, tmp_base_dir: Path) -> None:
        create_team("guarded", "sess-1", base_dir=tmp_base_dir)
        with pytest.raises(ValueError, match="Cannot remove team-lead"):
            remove_member("guarded", "team-lead", base_dir=tmp_base_dir)

    def test_should_allow_removing_non_lead_member(self, tmp_base_dir: Path) -> None:
        create_team("ok-rm", "sess-1", base_dir=tmp_base_dir)
        mate = _make_teammate("temp", "ok-rm")
        add_member("ok-rm", mate, base_dir=tmp_base_dir)
        remove_member("ok-rm", "temp", base_dir=tmp_base_dir)
        cfg = read_config("ok-rm", base_dir=tmp_base_dir)
        assert len(cfg.members) == 1


class TestReadConfig:
    def test_read_config_round_trip(self, tmp_base_dir: Path) -> None:
        result = create_team("roundtrip", "sess-99", description="rt test", base_dir=tmp_base_dir)
        cfg = read_config("roundtrip", base_dir=tmp_base_dir)

        assert cfg.name == "roundtrip"
        assert cfg.description == "rt test"
        assert cfg.lead_session_id == "sess-99"
        assert cfg.lead_agent_id == "team-lead@roundtrip"
        assert len(cfg.members) == 1
        lead = cfg.members[0]
        assert isinstance(lead, LeadMember)
        assert lead.agent_id == "team-lead@roundtrip"


class TestProjectDir:
    def test_create_team_stores_project_dir(self, tmp_base_dir: Path, tmp_path: Path) -> None:
        project = tmp_path / "myproject"
        project.mkdir()
        create_team("pd-test", "sess-1", base_dir=tmp_base_dir, project_dir=project)
        cfg = read_config("pd-test", base_dir=tmp_base_dir)
        assert cfg.project_dir == str(project)

    def test_create_team_project_dir_defaults_to_none(self, tmp_base_dir: Path) -> None:
        create_team("pd-none", "sess-1", base_dir=tmp_base_dir)
        cfg = read_config("pd-none", base_dir=tmp_base_dir)
        assert cfg.project_dir is None

    def test_project_dir_serialized_as_camel_case(self, tmp_base_dir: Path, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        create_team("pd-alias", "sess-1", base_dir=tmp_base_dir, project_dir=project)

        import json
        raw = json.loads((tmp_base_dir / "teams" / "pd-alias" / "config.json").read_text())
        assert "projectDir" in raw
        assert raw["projectDir"] == str(project)

    def test_backward_compat_missing_project_dir(self, tmp_base_dir: Path) -> None:
        """Configs created before project_dir was added should still load."""
        create_team("old-team", "sess-1", base_dir=tmp_base_dir)
        # Manually strip projectDir from the JSON to simulate old config
        import json
        config_path = tmp_base_dir / "teams" / "old-team" / "config.json"
        raw = json.loads(config_path.read_text())
        raw.pop("projectDir", None)
        config_path.write_text(json.dumps(raw, indent=2))

        cfg = read_config("old-team", base_dir=tmp_base_dir)
        assert cfg.project_dir is None


class TestGetProjectDir:
    def test_returns_stored_project_dir(self, tmp_base_dir: Path, tmp_path: Path) -> None:
        project = tmp_path / "stored"
        project.mkdir()
        create_team("gp-stored", "sess-1", base_dir=tmp_base_dir, project_dir=project)
        result = get_project_dir("gp-stored", base_dir=tmp_base_dir)
        assert result == project

    def test_falls_back_to_cwd_when_none(self, tmp_base_dir: Path) -> None:
        create_team("gp-cwd", "sess-1", base_dir=tmp_base_dir)
        result = get_project_dir("gp-cwd", base_dir=tmp_base_dir)
        assert result == Path.cwd()


class TestRemoveMemberCleansUpConfig:
    def test_remove_member_deletes_agent_config(self, tmp_base_dir: Path, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        create_team("cleanup-rm", "sess-1", base_dir=tmp_base_dir, project_dir=project)

        # Create a fake agent config file
        agents_dir = project / ".opencode" / "agents"
        agents_dir.mkdir(parents=True)
        config_file = agents_dir / "worker.md"
        config_file.write_text("# Agent config")

        mate = _make_teammate("worker", "cleanup-rm")
        add_member("cleanup-rm", mate, base_dir=tmp_base_dir)

        remove_member("cleanup-rm", "worker", base_dir=tmp_base_dir)

        assert not config_file.exists()

    def test_remove_member_succeeds_even_if_no_config_file(self, tmp_base_dir: Path) -> None:
        create_team("cleanup-nofile", "sess-1", base_dir=tmp_base_dir)
        mate = _make_teammate("worker", "cleanup-nofile")
        add_member("cleanup-nofile", mate, base_dir=tmp_base_dir)

        # Should not raise even though there's no .opencode/agents/ directory
        remove_member("cleanup-nofile", "worker", base_dir=tmp_base_dir)
        cfg = read_config("cleanup-nofile", base_dir=tmp_base_dir)
        assert len(cfg.members) == 1
