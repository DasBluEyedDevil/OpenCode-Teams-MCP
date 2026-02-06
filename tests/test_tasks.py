from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_teams.tasks import (
    create_task,
    get_task,
    list_tasks,
    next_task_id,
    reset_owner_tasks,
    update_task,
)


@pytest.fixture
def team_tasks_dir(tmp_claude_dir):
    d = tmp_claude_dir / "tasks" / "test-team"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".lock").touch()
    return d


def test_create_task_assigns_id_1_first(tmp_claude_dir, team_tasks_dir):
    task = create_task("test-team", "First", "desc", base_dir=tmp_claude_dir)
    assert task.id == "1"


def test_create_task_auto_increments(tmp_claude_dir, team_tasks_dir):
    create_task("test-team", "First", "desc", base_dir=tmp_claude_dir)
    task2 = create_task("test-team", "Second", "desc2", base_dir=tmp_claude_dir)
    assert task2.id == "2"


def test_create_task_excludes_none_owner(tmp_claude_dir, team_tasks_dir):
    task = create_task("test-team", "Sub", "desc", base_dir=tmp_claude_dir)
    raw = json.loads((team_tasks_dir / f"{task.id}.json").read_text())
    assert "owner" not in raw


def test_create_task_with_metadata(tmp_claude_dir, team_tasks_dir):
    task = create_task(
        "test-team", "Sub", "desc", metadata={"key": "val"}, base_dir=tmp_claude_dir
    )
    raw = json.loads((team_tasks_dir / f"{task.id}.json").read_text())
    assert raw["metadata"] == {"key": "val"}


def test_get_task_round_trip(tmp_claude_dir, team_tasks_dir):
    created = create_task(
        "test-team", "Sub", "desc", active_form="do the thing", base_dir=tmp_claude_dir
    )
    fetched = get_task("test-team", created.id, base_dir=tmp_claude_dir)
    assert fetched.id == created.id
    assert fetched.subject == "Sub"
    assert fetched.description == "desc"
    assert fetched.active_form == "do the thing"
    assert fetched.status == "pending"


def test_update_task_changes_status(tmp_claude_dir, team_tasks_dir):
    task = create_task("test-team", "Sub", "desc", base_dir=tmp_claude_dir)
    updated = update_task(
        "test-team", task.id, status="in_progress", base_dir=tmp_claude_dir
    )
    assert updated.status == "in_progress"
    on_disk = get_task("test-team", task.id, base_dir=tmp_claude_dir)
    assert on_disk.status == "in_progress"


def test_update_task_sets_owner(tmp_claude_dir, team_tasks_dir):
    task = create_task("test-team", "Sub", "desc", base_dir=tmp_claude_dir)
    updated = update_task(
        "test-team", task.id, owner="worker-1", base_dir=tmp_claude_dir
    )
    assert updated.owner == "worker-1"
    raw = json.loads((team_tasks_dir / f"{task.id}.json").read_text())
    assert raw["owner"] == "worker-1"


def test_update_task_delete_removes_file(tmp_claude_dir, team_tasks_dir):
    task = create_task("test-team", "Sub", "desc", base_dir=tmp_claude_dir)
    fpath = team_tasks_dir / f"{task.id}.json"
    assert fpath.exists()
    result = update_task(
        "test-team", task.id, status="deleted", base_dir=tmp_claude_dir
    )
    assert not fpath.exists()
    assert result.status == "deleted"


def test_update_task_add_blocks(tmp_claude_dir, team_tasks_dir):
    task = create_task("test-team", "Sub", "desc", base_dir=tmp_claude_dir)
    updated = update_task(
        "test-team", task.id, add_blocks=["2", "3"], base_dir=tmp_claude_dir
    )
    assert updated.blocks == ["2", "3"]
    updated2 = update_task(
        "test-team", task.id, add_blocks=["3", "4"], base_dir=tmp_claude_dir
    )
    assert updated2.blocks == ["2", "3", "4"]


def test_update_task_add_blocked_by(tmp_claude_dir, team_tasks_dir):
    task = create_task("test-team", "Sub", "desc", base_dir=tmp_claude_dir)
    updated = update_task(
        "test-team", task.id, add_blocked_by=["5", "6"], base_dir=tmp_claude_dir
    )
    assert updated.blocked_by == ["5", "6"]
    updated2 = update_task(
        "test-team", task.id, add_blocked_by=["6", "7"], base_dir=tmp_claude_dir
    )
    assert updated2.blocked_by == ["5", "6", "7"]


def test_update_task_metadata_merge(tmp_claude_dir, team_tasks_dir):
    task = create_task(
        "test-team", "Sub", "desc", metadata={"a": 1}, base_dir=tmp_claude_dir
    )
    updated = update_task(
        "test-team", task.id, metadata={"b": 2}, base_dir=tmp_claude_dir
    )
    assert updated.metadata == {"a": 1, "b": 2}

    updated2 = update_task(
        "test-team", task.id, metadata={"a": None}, base_dir=tmp_claude_dir
    )
    assert "a" not in updated2.metadata
    assert updated2.metadata == {"b": 2}


def test_list_tasks_returns_sorted(tmp_claude_dir, team_tasks_dir):
    create_task("test-team", "A", "d1", base_dir=tmp_claude_dir)
    create_task("test-team", "B", "d2", base_dir=tmp_claude_dir)
    create_task("test-team", "C", "d3", base_dir=tmp_claude_dir)
    tasks = list_tasks("test-team", base_dir=tmp_claude_dir)
    assert [t.id for t in tasks] == ["1", "2", "3"]


def test_list_tasks_empty(tmp_claude_dir, team_tasks_dir):
    tasks = list_tasks("test-team", base_dir=tmp_claude_dir)
    assert tasks == []


def test_reset_owner_tasks_reverts_status(tmp_claude_dir, team_tasks_dir):
    task = create_task("test-team", "Sub", "desc", base_dir=tmp_claude_dir)
    update_task(
        "test-team",
        task.id,
        owner="w",
        status="in_progress",
        base_dir=tmp_claude_dir,
    )
    reset_owner_tasks("test-team", "w", base_dir=tmp_claude_dir)
    after = get_task("test-team", task.id, base_dir=tmp_claude_dir)
    assert after.status == "pending"
    assert after.owner is None


def test_reset_owner_tasks_only_affects_matching_owner(tmp_claude_dir, team_tasks_dir):
    t1 = create_task("test-team", "A", "d1", base_dir=tmp_claude_dir)
    t2 = create_task("test-team", "B", "d2", base_dir=tmp_claude_dir)
    update_task(
        "test-team",
        t1.id,
        owner="w1",
        status="in_progress",
        base_dir=tmp_claude_dir,
    )
    update_task(
        "test-team",
        t2.id,
        owner="w2",
        status="in_progress",
        base_dir=tmp_claude_dir,
    )
    reset_owner_tasks("test-team", "w1", base_dir=tmp_claude_dir)
    after1 = get_task("test-team", t1.id, base_dir=tmp_claude_dir)
    after2 = get_task("test-team", t2.id, base_dir=tmp_claude_dir)
    assert after1.status == "pending"
    assert after1.owner is None
    assert after2.status == "in_progress"
    assert after2.owner == "w2"
