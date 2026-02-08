# Phase 4: MCP Communication Validation - Research

**Researched:** 2026-02-07
**Domain:** MCP tool invocation verification, multi-agent filesystem state sharing, integration testing patterns
**Confidence:** HIGH

## Summary

Phase 4 validates that the MCP server tools actually work when called by spawned agents. This is fundamentally an integration testing phase -- the implementation was done in Phases 1-3, and Phase 4 confirms the end-to-end behavior works correctly. There are two distinct concerns: (1) a single agent can invoke `read_inbox`, `send_message`, and `task_*` MCP tools and get correct responses, and (2) two separate agent processes share state through the filesystem backend so that messages sent by agent A are visible to agent B.

The architecture is clear: each OpenCode agent instance spawns its own `claude-teams` MCP server subprocess via STDIO transport (as configured in `opencode.json` with `"type": "local"`). These are independent processes. State sharing works because the MCP server persists everything as JSON files under `~/.claude/teams/` with `fcntl.flock` file locking for concurrent access safety. Two MCP server processes writing to the same inbox file will serialize correctly through the lock. This is not a shared-memory model -- it is a shared-filesystem model, which is exactly what the existing persistence layer was designed for.

The existing test suite already validates most of the single-agent behavior through the `Client(mcp)` in-memory test pattern in `test_server.py`. What Phase 4 needs to add is: (a) an explicit integration test that simulates two agents operating on the same team state, and (b) confirmation that the filesystem-based state sharing works across separate "agent contexts" (not just within a single `Client` session). The tests should use real filesystem operations (not mocks) with `tmp_path` isolation to validate the file locking and JSON persistence.

**Primary recommendation:** Write integration tests that validate single-agent tool access and multi-agent state sharing through the filesystem backend. No new production code is expected -- Phase 4 is verification, not implementation. If tests reveal bugs, fix them. The empirical concerns from STATE.md (MCP state sharing, Kimi K2.5 instruction-following) should be addressed: state sharing is validated by tests, and Kimi K2.5 instruction-following is deferred to manual testing (it requires an actual LLM and API key).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.0+ | Test framework | Already used throughout codebase |
| pytest-asyncio | 0.23+ | Async test support | Already used, `asyncio_mode = "auto"` configured |
| fastmcp.Client | 3.0.0b1 | In-memory MCP client for testing | Already used in `test_server.py` for tool invocation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python stdlib `threading` | 3.12+ | Multi-process simulation in tests | Validate concurrent file access from multiple "agents" |
| Python stdlib `json` | 3.12+ | Read/verify filesystem state directly | Assert that files on disk match expected state |
| Python stdlib `pathlib` | 3.12+ | Temp directory management | Test isolation via `tmp_path` fixture |
| unittest.mock | 3.12+ | Mock external dependencies (binary discovery) | Prevent actual OpenCode binary requirement in tests |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-memory `Client(mcp)` testing | Actual subprocess STDIO testing | Subprocess testing is slower, requires installed binary; in-memory tests validate the same tool logic |
| Simulated multi-agent via separate function calls | Two actual `Client` instances on same server | Two clients sharing same FastMCP server would share lifespan context, which matches production behavior |
| Python threading for concurrency tests | multiprocessing module | Threading is simpler and sufficient since we are testing file locking (which works across threads and processes) |

**Installation:**
```bash
# No new dependencies -- all already in project
```

## Architecture Patterns

### Recommended Project Structure
```
tests/
  test_server.py            # EXTEND: add Phase 4 validation test classes
  test_mcp_integration.py   # NEW (optional): dedicated multi-agent integration tests
  conftest.py               # EXTEND: add multi-agent fixtures if needed
```

### Pattern 1: Single-Agent MCP Tool Verification
**What:** Validate that each MCP tool (`read_inbox`, `send_message`, `task_create`, `task_update`, `task_list`, `task_get`) returns correct responses when called by a spawned agent's perspective.
**When to use:** Verify MCP-02 requirement (teammates can access all MCP tools).
**Example:**
```python
# Source: Existing test_server.py pattern, extended for agent perspective
class TestSingleAgentMCPAccess:
    """Verify MCP-02: spawned agent can call all coordination tools."""

    async def test_agent_can_read_own_inbox(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t"})
        teams.add_member("t", _make_teammate("alice", "t"))
        # Team lead sends a message to alice
        await client.call_tool("send_message", {
            "team_name": "t",
            "type": "message",
            "recipient": "alice",
            "content": "start working",
            "summary": "assignment",
        })
        # Alice reads her inbox (agent perspective)
        inbox = _data(await client.call_tool("read_inbox", {
            "team_name": "t",
            "agent_name": "alice",
        }))
        assert len(inbox) == 1
        assert inbox[0]["text"] == "start working"

    async def test_agent_can_send_message_to_teammate(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t"})
        teams.add_member("t", _make_teammate("alice", "t"))
        teams.add_member("t", _make_teammate("bob", "t"))
        # Alice sends message to Bob (agent perspective)
        await client.call_tool("send_message", {
            "team_name": "t",
            "type": "message",
            "sender": "alice",
            "recipient": "bob",
            "content": "need help with tests",
            "summary": "help request",
        })
        # Bob reads his inbox
        inbox = _data(await client.call_tool("read_inbox", {
            "team_name": "t",
            "agent_name": "bob",
        }))
        assert len(inbox) == 1
        assert inbox[0]["from"] == "alice"

    async def test_agent_can_create_and_update_tasks(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t"})
        created = _data(await client.call_tool("task_create", {
            "team_name": "t",
            "subject": "Fix bug",
            "description": "Fix the auth bug",
        }))
        assert created["id"] == "1"
        # Agent claims the task
        updated = _data(await client.call_tool("task_update", {
            "team_name": "t",
            "task_id": created["id"],
            "owner": "alice",
            "status": "in_progress",
        }))
        assert updated["owner"] == "alice"
        assert updated["status"] == "in_progress"
```

### Pattern 2: Multi-Agent State Sharing via Filesystem
**What:** Validate that operations from one agent's context are visible to another agent's context through the shared filesystem.
**When to use:** Verify MCP-03 requirement (shared state across all spawned agents).
**Example:**
```python
# Source: Architecture requirement MCP-03
class TestMultiAgentStateSharing:
    """Verify MCP-03: state shared across agents via filesystem backend."""

    async def test_message_from_agent_a_visible_to_agent_b(self, client: Client):
        """Two agents in same team can exchange messages through MCP server."""
        await client.call_tool("team_create", {"team_name": "shared"})
        teams.add_member("shared", _make_teammate("alice", "shared"))
        teams.add_member("shared", _make_teammate("bob", "shared"))

        # Agent A (alice) sends message to agent B (bob)
        await client.call_tool("send_message", {
            "team_name": "shared",
            "type": "message",
            "sender": "alice",
            "recipient": "bob",
            "content": "I found the bug",
            "summary": "bug report",
        })

        # Agent B (bob) reads inbox and sees alice's message
        inbox = _data(await client.call_tool("read_inbox", {
            "team_name": "shared",
            "agent_name": "bob",
        }))
        assert len(inbox) == 1
        assert inbox[0]["from"] == "alice"
        assert inbox[0]["text"] == "I found the bug"

    async def test_task_created_by_lead_visible_to_agent(self, client: Client):
        """Task created by team lead is visible when agent lists tasks."""
        await client.call_tool("team_create", {"team_name": "shared"})
        await client.call_tool("task_create", {
            "team_name": "shared",
            "subject": "Implement feature",
            "description": "Build the login page",
        })
        # Agent reads task list
        task_list = _data(await client.call_tool("task_list", {
            "team_name": "shared",
        }))
        assert len(task_list) == 1
        assert task_list[0]["subject"] == "Implement feature"

    async def test_task_claimed_by_agent_a_visible_to_agent_b(self, client: Client):
        """When alice claims a task, bob sees it as claimed."""
        await client.call_tool("team_create", {"team_name": "shared"})
        created = _data(await client.call_tool("task_create", {
            "team_name": "shared",
            "subject": "Code review",
            "description": "Review PR #42",
        }))
        # Alice claims the task
        await client.call_tool("task_update", {
            "team_name": "shared",
            "task_id": created["id"],
            "owner": "alice",
            "status": "in_progress",
        })
        # Bob checks task list -- sees alice owns it
        task_list = _data(await client.call_tool("task_list", {
            "team_name": "shared",
        }))
        assert task_list[0]["owner"] == "alice"
        assert task_list[0]["status"] == "in_progress"
```

### Pattern 3: Cross-Process Filesystem Verification
**What:** Directly verify that filesystem state written by MCP tools matches expected format, confirming the persistence layer works for cross-process sharing.
**When to use:** To confirm MCP-03 at the filesystem level, not just through the MCP tool API.
**Example:**
```python
class TestFilesystemStateSharing:
    """Verify filesystem state is correct for cross-process sharing."""

    def test_inbox_file_is_valid_json_after_send(self, tmp_claude_dir):
        """Inbox JSON files written by send_message are valid JSON readable by any process."""
        teams_module.create_team("t", session_id="s", base_dir=tmp_claude_dir)
        messaging.send_plain_message("t", "alice", "bob", "hello", summary="hi",
                                      base_dir=tmp_claude_dir)
        # Directly read the file (as another process would)
        inbox_file = tmp_claude_dir / "teams" / "t" / "inboxes" / "bob.json"
        assert inbox_file.exists()
        raw = json.loads(inbox_file.read_text())
        assert len(raw) == 1
        assert raw[0]["text"] == "hello"
        assert raw[0]["from"] == "alice"

    def test_task_file_is_valid_json_after_create(self, tmp_claude_dir):
        """Task JSON files are valid and readable by any process."""
        teams_module.create_team("t", session_id="s", base_dir=tmp_claude_dir)
        task = tasks.create_task("t", "Fix bug", "desc", base_dir=tmp_claude_dir)
        task_file = tmp_claude_dir / "tasks" / "t" / f"{task.id}.json"
        assert task_file.exists()
        raw = json.loads(task_file.read_text())
        assert raw["subject"] == "Fix bug"
```

### Anti-Patterns to Avoid

- **Testing with actual OpenCode binary and Kimi K2.5 API calls:** Phase 4 is integration testing of the MCP server layer, not end-to-end LLM testing. Use in-memory `Client(mcp)` and direct domain function calls, not actual `opencode run` invocations.
- **Assuming MCP server instances share in-memory state:** Each OpenCode agent spawns its own MCP server subprocess. There is NO shared memory. All state sharing happens through the filesystem. Tests must verify filesystem persistence, not in-memory state.
- **Mocking the filesystem for state sharing tests:** The whole point of MCP-03 is that the filesystem IS the shared state backend. Use real temp directories, not mocks.
- **Testing only the happy path:** Test edge cases: empty inbox, concurrent message sends, task status transitions by different agents, read-after-write consistency.
- **Creating new production modules:** Phase 4 should produce tests, not new source code. If bugs are found, fix them in existing modules.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP tool testing | Custom HTTP client or subprocess spawning | `fastmcp.Client(mcp)` in-memory | Already proven in test_server.py, zero setup |
| Multi-agent simulation | Actual subprocess spawning of OpenCode | Sequential MCP tool calls with different agent names | Simulates the exact same API without requiring installed binary |
| Filesystem verification | Custom file watchers | Direct `Path.read_text()` + `json.loads()` | Simple, deterministic, no race conditions in tests |
| Team/inbox setup | Manual JSON file creation | Existing `teams.create_team()` + `teams.add_member()` + `messaging.*` | Already tested, correct format guaranteed |
| Test data creation | Inline TeammateMember construction | Existing `_make_teammate()` helper in test_server.py | Consistent, DRY |

**Key insight:** Phase 4's value is in PROVING the system works end-to-end, not building new functionality. The tests are the deliverable.

## Common Pitfalls

### Pitfall 1: send_message Default Sender is "team-lead"
**What goes wrong:** When testing agent-to-agent messaging, the `sender` parameter in `send_message` defaults to `"team-lead"`. If you forget to set `sender="alice"` when simulating alice sending a message, the message appears to come from team-lead.
**Why it happens:** The `send_message` MCP tool was designed primarily for team-lead usage. Agent-to-agent messaging uses the same tool but requires explicit `sender` parameter.
**How to avoid:** Always set the `sender` parameter explicitly in multi-agent tests. Verify `from` field in received messages matches expected sender.
**Warning signs:** All messages in agent inboxes show `from: team-lead` regardless of actual sender.

### Pitfall 2: send_message "message" Type Requires Recipient to Be Team Member
**What goes wrong:** Sending a message with `type="message"` and `recipient="alice"` fails if alice is not registered as a team member via `teams.add_member()`.
**Why it happens:** The `send_message` tool validates that the recipient exists in the team config before sending.
**How to avoid:** Always register agents as team members before testing message exchange. Use the helper: `teams.add_member("team", _make_teammate("alice", "team"))`.
**Warning signs:** `ToolError: Recipient 'alice' is not a member of team`.

### Pitfall 3: Lifespan Context Per-Session in FastMCP
**What goes wrong:** FastMCP's lifespan context runs per client session, not per application startup. If tests expect a single shared lifespan across multiple `Client(mcp)` instances, state like `active_team` will reset for each new client connection.
**Why it happens:** FastMCP lifespan is session-scoped per MCP specification, not application-scoped. Each `async with Client(mcp) as c:` creates a new session with fresh lifespan context.
**How to avoid:** For multi-agent tests that need shared team state, use a single `Client` connection and simulate both agents' operations through it. The filesystem is the actual shared state, not the lifespan dict. Alternatively, use direct domain function calls (`messaging.*`, `tasks.*`, `teams.*`) alongside a single Client for MCP tool validation.
**Warning signs:** `active_team` is None in second client even though team was created in first client.

### Pitfall 4: read_inbox mark_as_read Side Effect
**What goes wrong:** Calling `read_inbox` marks messages as read by default. If a test reads the inbox to verify a message was delivered, subsequent reads with `unread_only=True` return empty.
**Why it happens:** `mark_as_read=True` is the default parameter.
**How to avoid:** Use `mark_as_read=False` in verification reads, or structure tests to account for the read-once behavior. In production, this is correct behavior -- an agent should only see unread messages once.
**Warning signs:** Tests pass individually but fail when run together because messages were already marked read.

### Pitfall 5: Monkeypatch Scope for Directory Constants
**What goes wrong:** Tests that modify `TEAMS_DIR` or `TASKS_DIR` via `monkeypatch` can leak state between test classes if the fixture scope is wrong.
**Why it happens:** The constants in `messaging.py`, `tasks.py`, and `teams.py` are module-level globals. Monkeypatching in one test fixture must cover ALL modules that use these constants.
**How to avoid:** Follow the existing pattern from `test_server.py:31-35`: monkeypatch all three modules (`teams.TEAMS_DIR`, `tasks.TASKS_DIR`, `messaging.TEAMS_DIR`) together in the fixture.
**Warning signs:** Tests pass individually but fail when run together; state from one test leaks into another.

### Pitfall 6: Windows/WSL fcntl Dependency
**What goes wrong:** Tests that exercise file locking (concurrent message sends, task updates) will fail on Windows because `fcntl` is POSIX-only.
**Why it happens:** The codebase uses `fcntl.flock` for file locking, which is not available on Windows.
**How to avoid:** Run tests in WSL on Windows. This is already a known constraint documented in STATE.md. Tests should not try to work around this -- it is a platform requirement.
**Warning signs:** `ImportError: No module named 'fcntl'` on native Windows Python.

## Code Examples

Verified patterns from official sources and existing codebase:

### Complete Test Fixture for Multi-Agent Testing
```python
# Source: Existing test_server.py fixture pattern
@pytest.fixture
async def client(tmp_path: Path, monkeypatch):
    """MCP client with filesystem isolation for multi-agent tests."""
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
```

### End-to-End Multi-Agent Message Exchange Test
```python
# Source: MCP-02 and MCP-03 requirements
class TestMultiAgentMessageExchange:
    """Verify success criterion 2: Two agents can exchange messages."""

    async def test_bidirectional_message_exchange(self, client: Client):
        """Agent A sends to agent B, agent B sends to agent A."""
        await client.call_tool("team_create", {"team_name": "duo"})
        teams.add_member("duo", _make_teammate("alice", "duo"))
        teams.add_member("duo", _make_teammate("bob", "duo"))

        # Alice -> Bob
        await client.call_tool("send_message", {
            "team_name": "duo",
            "type": "message",
            "sender": "alice",
            "recipient": "bob",
            "content": "Can you review my PR?",
            "summary": "review request",
        })

        # Bob reads inbox
        bob_inbox = _data(await client.call_tool("read_inbox", {
            "team_name": "duo", "agent_name": "bob",
        }))
        assert len(bob_inbox) == 1
        assert bob_inbox[0]["from"] == "alice"

        # Bob -> Alice
        await client.call_tool("send_message", {
            "team_name": "duo",
            "type": "message",
            "sender": "bob",
            "recipient": "alice",
            "content": "LGTM, approved!",
            "summary": "review approved",
        })

        # Alice reads inbox
        alice_inbox = _data(await client.call_tool("read_inbox", {
            "team_name": "duo", "agent_name": "alice",
        }))
        assert len(alice_inbox) == 1
        assert alice_inbox[0]["from"] == "bob"
        assert alice_inbox[0]["text"] == "LGTM, approved!"
```

### Full Tool Access Verification
```python
# Source: MCP-02 requirement - all tools accessible
class TestAllToolsAccessible:
    """Verify success criterion 1: agent can call all MCP tools."""

    async def test_read_inbox_returns_correct_format(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t"})
        result = _data(await client.call_tool("read_inbox", {
            "team_name": "t", "agent_name": "agent1",
        }))
        assert isinstance(result, list)

    async def test_send_message_returns_success(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t"})
        teams.add_member("t", _make_teammate("agent1", "t"))
        result = _data(await client.call_tool("send_message", {
            "team_name": "t", "type": "message",
            "recipient": "agent1", "content": "hi", "summary": "greet",
        }))
        assert result["success"] is True

    async def test_task_create_list_get_update_cycle(self, client: Client):
        await client.call_tool("team_create", {"team_name": "t"})

        # Create
        created = _data(await client.call_tool("task_create", {
            "team_name": "t", "subject": "Task 1", "description": "Do it",
        }))
        assert "id" in created

        # List
        listed = _data(await client.call_tool("task_list", {"team_name": "t"}))
        assert len(listed) == 1

        # Get
        got = _data(await client.call_tool("task_get", {
            "team_name": "t", "task_id": created["id"],
        }))
        assert got["subject"] == "Task 1"

        # Update
        updated = _data(await client.call_tool("task_update", {
            "team_name": "t", "task_id": created["id"],
            "status": "in_progress", "owner": "agent1",
        }))
        assert updated["status"] == "in_progress"
```

### Filesystem State Verification
```python
# Source: MCP-03 requirement - filesystem backend verification
class TestFilesystemBackend:
    """Verify success criterion 3: state shared via filesystem at ~/.claude/."""

    async def test_inbox_persisted_to_disk(self, client: Client, tmp_path: Path):
        await client.call_tool("team_create", {"team_name": "fs-test"})
        teams.add_member("fs-test", _make_teammate("worker", "fs-test"))
        await client.call_tool("send_message", {
            "team_name": "fs-test", "type": "message",
            "recipient": "worker", "content": "disk check", "summary": "verify",
        })
        # Verify file exists on disk
        inbox_file = tmp_path / "teams" / "fs-test" / "inboxes" / "worker.json"
        assert inbox_file.exists()
        raw = json.loads(inbox_file.read_text())
        assert any(m["text"] == "disk check" for m in raw)

    async def test_task_persisted_to_disk(self, client: Client, tmp_path: Path):
        await client.call_tool("team_create", {"team_name": "fs-test"})
        created = _data(await client.call_tool("task_create", {
            "team_name": "fs-test", "subject": "Persisted", "description": "On disk",
        }))
        task_file = tmp_path / "tasks" / "fs-test" / f"{created['id']}.json"
        assert task_file.exists()
        raw = json.loads(task_file.read_text())
        assert raw["subject"] == "Persisted"

    async def test_team_config_persisted_to_disk(self, client: Client, tmp_path: Path):
        await client.call_tool("team_create", {"team_name": "fs-test"})
        config_file = tmp_path / "teams" / "fs-test" / "config.json"
        assert config_file.exists()
        raw = json.loads(config_file.read_text())
        assert raw["name"] == "fs-test"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Shared in-memory state (single process) | Shared filesystem state (multi-process) | Phase 2-3 (architecture) | Each agent subprocess has own MCP server; filesystem is the coordination layer |
| Claude Code built-in team awareness | OpenCode agent config + MCP tools for team awareness | Phase 2 (config gen) | Agent identity via system prompt, coordination via MCP tool calls |
| No explicit MCP tool access verification | Integration tests for all tool operations | Phase 4 (now) | Validates that the tool interface works end-to-end |

**Deprecated/outdated:**
- In-process shared state assumption -- each OpenCode agent gets its own MCP server subprocess
- Claude Code's built-in `--agent-id` and `--team-name` flags for team context

## Requirements Mapping

| Requirement | How Validated | Test Strategy |
|-------------|---------------|---------------|
| **MCP-02**: Teammates access read_inbox, send_message, task_* tools | Call each tool via `Client(mcp)` and verify correct responses | TestAllToolsAccessible class with per-tool tests |
| **MCP-03**: MCP server state shared across agents via filesystem | Verify that state written by one agent's tool call is readable by another agent's tool call; verify files on disk | TestMultiAgentStateSharing + TestFilesystemBackend classes |

| Success Criterion | How Validated | Test Strategy |
|-------------------|---------------|---------------|
| 1. Agent can call read_inbox, send_message, task_* tools | MCP tool calls return correct results | TestAllToolsAccessible: each tool returns expected format |
| 2. Two agents exchange messages through MCP server | Agent A sends, agent B reads, message matches | TestMultiAgentMessageExchange: bidirectional test |
| 3. State shared via filesystem backend | Operations visible across agent contexts; files on disk match | TestFilesystemBackend: verify JSON files exist with correct content |

## Open Questions

1. **Kimi K2.5 Instruction-Following for Team Coordination**
   - What we know: The agent system prompt instructs polling inbox every 3-5 tool calls, using `claude-teams_read_inbox`, sending messages, managing tasks. These are clear, structured instructions.
   - What's unclear: Whether Kimi K2.5 reliably follows these multi-step protocols. This was flagged in STATE.md as needing empirical testing.
   - Recommendation: This CANNOT be validated in automated tests -- it requires an actual Kimi K2.5 API key and live LLM interaction. Phase 4 tests validate the MCP tool layer (which is language-model-agnostic). Kimi K2.5 instruction-following should be tested manually or deferred to a separate validation phase. Document this as out-of-scope for Phase 4 automated tests.

2. **FastMCP Lifespan Per-Session Behavior**
   - What we know: FastMCP lifespan context runs per client session, not per application. Each `async with Client(mcp)` creates a fresh lifespan with new `active_team`, `session_id`, etc.
   - What's unclear: Whether this accurately simulates production behavior where each agent has its own STDIO connection (and thus its own session/lifespan).
   - Recommendation: This is actually CORRECT behavior. In production, each OpenCode agent has its own MCP server subprocess, so each has its own lifespan context. The filesystem is the ONLY shared state. Tests using a single `Client` with multiple agent names passed as parameters correctly simulate this because the filesystem operations are the same regardless of which lifespan context they run in.

3. **Concurrent File Access Under Load**
   - What we know: `fcntl.flock` provides advisory locking. The existing codebase uses it for inbox appends and task updates. One threading test exists in `test_messaging.py`.
   - What's unclear: Whether concurrent writes from two agent MCP server processes could race under real-world load.
   - Recommendation: The existing file locking is correct for advisory locking between cooperating processes. Add a concurrent write test in Phase 4 that simulates two agents appending messages to the same inbox simultaneously. If it passes (it should, given the existing lock), the concern is resolved.

4. **send_message sender Parameter Behavior**
   - What we know: The `send_message` tool has `sender: str = "team-lead"` as default. When a spawned agent calls this tool, it needs to provide its own name as `sender`. The system prompt tells agents to use `claude-teams_send_message` but does not explicitly show setting the `sender` parameter.
   - What's unclear: Whether the generated agent config prompt should be updated to include `sender="{name}"` in the example, or whether OpenCode/the MCP protocol automatically injects caller identity.
   - Recommendation: MCP does NOT inject caller identity. The `sender` parameter must be explicitly set by the calling agent. The system prompt in `config_gen.py` should be verified and potentially updated to include `sender="{name}"` in the send_message example. This is a documentation/prompt quality issue, not a code bug. If Phase 4 tests reveal that the current prompt leads to incorrect sender attribution, it should be fixed.

## Sources

### Primary (HIGH confidence)
- Existing codebase `server.py` -- MCP tool definitions, parameter validation, lifespan context
- Existing codebase `messaging.py` -- Filesystem persistence with fcntl.flock locking
- Existing codebase `tasks.py` -- Filesystem persistence with fcntl.flock locking
- Existing codebase `teams.py` -- Atomic writes via tempfile + os.replace
- Existing `test_server.py` -- Client(mcp) testing pattern, _data() helper, _make_teammate() factory
- Existing `test_messaging.py` -- File locking test pattern, threading test
- [DeepWiki: OpenCode MCP and External Tools](https://deepwiki.com/opencode-ai/opencode/6.3-mcp-and-external-tools) -- Each OpenCode instance spawns own subprocess for local MCP servers

### Secondary (MEDIUM confidence)
- [FastMCP Testing Guide](https://gofastmcp.com/patterns/testing) -- Client(transport=mcp) pattern for in-memory testing
- [FastMCP Client Docs](https://gofastmcp.com/clients/client) -- In-memory transport for testing
- [FastMCP Issue #1115](https://github.com/jlowin/fastmcp/issues/1115) -- Lifespan is per-session, not per-application (closed as expected behavior)
- [MCP Architecture](https://modelcontextprotocol.io/docs/learn/architecture) -- STDIO transport, one client per connection
- [MCP STDIO Transport](https://mcp-framework.com/docs/Transports/stdio-transport/) -- Subprocess per client, natural process isolation

### Tertiary (LOW confidence)
- Kimi K2.5 instruction-following quality -- no empirical data, only inference from STATE.md concerns
- Optimal concurrent access patterns under production load -- tested with single thread in existing tests, not stress-tested

## Metadata

**Confidence breakdown:**
- Single-agent tool access (MCP-02): HIGH -- existing tests already cover most of this, Phase 4 adds explicit agent-perspective validation
- Multi-agent state sharing (MCP-03): HIGH -- filesystem backend with fcntl locking is well-understood; architecture confirmed (each agent = own MCP subprocess + shared filesystem)
- Test patterns: HIGH -- existing test_server.py provides proven patterns
- send_message sender parameter: MEDIUM -- default is "team-lead", agent system prompt may not explicitly set sender; needs verification
- Kimi K2.5 instruction-following: LOW -- requires empirical testing with actual LLM, out of scope for automated Phase 4 tests

**Research date:** 2026-02-07
**Valid until:** 2026-02-21 (14 days -- testing patterns stable, no external API dependencies)
