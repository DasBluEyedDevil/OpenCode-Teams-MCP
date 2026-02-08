# Phase 2: Agent Config Generation - Research

**Researched:** 2026-02-07
**Domain:** OpenCode agent markdown file generation, YAML frontmatter, MCP tool configuration, permission system
**Confidence:** HIGH

## Summary

Phase 2 generates `.opencode/agents/<name>.md` config files that give spawned OpenCode agents their identity, team awareness, communication instructions, and MCP tool access. These are markdown files with YAML frontmatter that OpenCode loads when invoked with `opencode run --agent <name>`. The file name (without `.md`) becomes the agent identifier.

The core work is string generation: building a YAML frontmatter block (description, model, mode, tools, permission) and a markdown body containing the system prompt with team context, inbox polling instructions, and task management protocol. No new external dependencies are required -- the YAML frontmatter is simple enough to generate via Python string formatting or `yaml.dump()` (PyYAML 6.0.3 is already available in the environment). The system prompt content is templated text with interpolated values (agent_id, team_name, color, tool names, polling frequency).

A critical architectural decision: MCP servers are configured in `opencode.json` at the project level, not in individual agent markdown files. The agent config controls which MCP tools are *enabled* for that agent via the `tools` section (e.g., `claude-teams_*: true`), and what *permissions* those tools have via the `permission` section. The MCP server definition itself (command, type, environment) lives in `opencode.json`. This means Phase 2 must generate BOTH the agent markdown file AND ensure the `opencode.json` has the `claude-teams` MCP server registered.

**Primary recommendation:** Create a `config_gen.py` module with a `generate_agent_config()` function that returns the full markdown string, and a `write_agent_config()` function that writes it to `.opencode/agents/<name>.md`. Use a separate `ensure_opencode_json()` function to create/update the project-level `opencode.json` with the MCP server definition. Call these from `spawn_teammate()` before executing the spawn command.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `textwrap` | 3.12+ | `textwrap.dedent` for clean multi-line system prompts | Avoids indentation issues in generated markdown |
| Python stdlib `json` | 3.12+ | Read/write `opencode.json` config file | Already used throughout codebase for config files |
| Python stdlib `pathlib` | 3.12+ | File path construction for `.opencode/agents/` | Already used throughout codebase |
| PyYAML | 6.0.3 (available) | `yaml.dump()` for YAML frontmatter generation | Safer than manual string formatting for nested structures |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pydantic (already installed) | v2 via FastMCP | Data models for agent config structure | For `AgentConfig` dataclass with validation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PyYAML for frontmatter | Manual f-string formatting | f-strings are simpler for flat YAML but fragile for nested `tools`/`permission` dicts; PyYAML handles quoting and escaping correctly |
| PyYAML for frontmatter | `json.dumps` with `---` wrappers | JSON is valid YAML but less readable; YAML frontmatter convention expects YAML syntax |
| Single `config_gen.py` module | Inline in `spawner.py` | `spawner.py` already has 335 lines; separate module is cleaner and more testable |

**Installation:**
```bash
# PyYAML is already available but not declared as a dependency.
# Option A: Add to pyproject.toml (recommended for reliability)
# Option B: Use manual string formatting to avoid dependency risk
# Recommendation: Add PyYAML to pyproject.toml since it's a stable, well-maintained library
pip install pyyaml  # Already present, but declare in pyproject.toml
```

**Decision needed:** Whether to add PyYAML as an explicit dependency or generate YAML manually. The frontmatter structure has nested dicts (`tools`, `permission`) that benefit from `yaml.dump()`. Recommendation: add PyYAML explicitly. If the planner disagrees, manual formatting is also viable for this use case since the structure is predictable.

## Architecture Patterns

### Recommended Project Structure
```
src/claude_teams/
  config_gen.py       # NEW: Agent config file generation
  spawner.py          # MODIFY: call config_gen before spawn
  server.py           # MINOR: pass project_dir to spawn flow
  models.py           # MINOR: add AgentConfig model if needed
.opencode/
  agents/             # GENERATED: agent markdown files go here
opencode.json         # GENERATED: MCP server registration
```

### Pattern 1: Two-Layer Config Generation
**What:** Agent config consists of two parts: (1) the agent markdown file at `.opencode/agents/<name>.md` and (2) the MCP server entry in `opencode.json`. Both must exist before spawning.
**When to use:** Every time a teammate is spawned.
**Example:**
```python
# Source: OpenCode docs (opencode.ai/docs/agents/, opencode.ai/docs/mcp-servers/)

def generate_agent_config(
    agent_id: str,
    name: str,
    team_name: str,
    color: str,
    model: str,
    mcp_server_command: list[str],
) -> str:
    """Generate the complete .opencode/agents/<name>.md content.

    Returns the full markdown string with YAML frontmatter and system prompt.
    """
    frontmatter = {
        "description": f"Team agent: {name} in team {team_name}",
        "model": model,
        "mode": "primary",
        "tools": {
            "read": True,
            "write": True,
            "edit": True,
            "bash": True,
            "glob": True,
            "grep": True,
            "list": True,
            "webfetch": True,
            "websearch": True,
            "todoread": True,
            "todowrite": True,
            "claude-teams_*": True,  # Enable all tools from our MCP server
        },
        "permission": "allow",  # RELY-02: all tools set to "allow"
    }

    system_prompt = f"""# Agent Identity

You are **{name}**, a team member of **{team_name}**.
- Agent ID: `{agent_id}`
- Color: {color}

# Communication Protocol

## Inbox Polling
You MUST check your inbox regularly using the `claude-teams_read_inbox` tool:
- Call `read_inbox(team_name="{team_name}", agent_name="{name}")` every 3-5 tool calls
- Always check inbox BEFORE starting new work
- Process all unread messages before continuing

## Sending Messages
Use `claude-teams_send_message` to communicate:
- Direct message: type="message", recipient="<name>", content="...", summary="..."
- To team lead: recipient="team-lead"

# Task Management

## Claiming Tasks
1. Check available tasks: `claude-teams_task_list(team_name="{team_name}")`
2. Claim a task: `claude-teams_task_update(team_name="{team_name}", task_id="<id>", owner="{name}", status="in_progress")`
3. Never claim tasks already owned by another agent

## Completing Tasks
1. Update status: `claude-teams_task_update(team_name="{team_name}", task_id="<id>", status="completed")`
2. Send completion message to team-lead

## Shutdown Protocol
When you receive a shutdown_request:
1. Finish current atomic operation
2. Report status via send_message
3. Respond with shutdown_response (approve=true)
"""

    yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    return f"---\n{yaml_str}---\n\n{system_prompt}"
```

### Pattern 2: MCP Server Registration in opencode.json
**What:** The `opencode.json` must contain the `claude-teams` MCP server definition so agents can access coordination tools.
**When to use:** Once per project, before any agent is spawned. Can be idempotent (check before writing).
**Example:**
```python
# Source: OpenCode MCP docs (opencode.ai/docs/mcp-servers/)

def ensure_opencode_json(
    project_dir: Path,
    mcp_server_command: list[str],
    mcp_server_env: dict[str, str] | None = None,
) -> Path:
    """Ensure opencode.json exists with claude-teams MCP server registered.

    Creates the file if it doesn't exist. Merges MCP config if it does.
    Returns the path to opencode.json.
    """
    config_path = project_dir / "opencode.json"

    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        config = {"$schema": "https://opencode.ai/config.json"}

    mcp = config.setdefault("mcp", {})
    mcp["claude-teams"] = {
        "type": "local",
        "command": mcp_server_command,
        "enabled": True,
    }
    if mcp_server_env:
        mcp["claude-teams"]["environment"] = mcp_server_env

    config_path.write_text(json.dumps(config, indent=2))
    return config_path
```

### Pattern 3: Agent File Write with Directory Creation
**What:** Write the generated markdown to `.opencode/agents/<name>.md`, creating directories as needed.
**When to use:** During spawn_teammate, before executing the opencode run command.
**Example:**
```python
# Source: OpenCode agent loading docs (opencode.ai/docs/agents/)

def write_agent_config(
    project_dir: Path,
    name: str,
    config_content: str,
) -> Path:
    """Write agent config to .opencode/agents/<name>.md.

    Creates .opencode/agents/ directory if it doesn't exist.
    Overwrites existing config file (re-spawn scenario).
    Returns the path to the created file.
    """
    agents_dir = project_dir / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    config_path = agents_dir / f"{name}.md"
    config_path.write_text(config_content, encoding="utf-8")
    return config_path
```

### Anti-Patterns to Avoid

- **Putting MCP server config in agent markdown:** MCP servers are defined in `opencode.json`, not in agent `.md` files. The agent file only controls which MCP *tools* are enabled/disabled and their permissions.
- **Using `mode: "subagent"` for spawned agents:** Subagents cannot be used with `opencode run --agent <name>`. Use `mode: "primary"` or omit mode (defaults to `"all"`, which includes primary). Since our agents run standalone via CLI, `"primary"` is the correct mode.
- **Using boolean `true` for permissions:** The `permission` field uses string values `"allow"`, `"ask"`, `"deny"` -- not booleans. The `tools` field uses booleans `true`/`false`. Confusing these causes silent failures.
- **Hardcoding tool names without the MCP prefix:** MCP tools in OpenCode are namespaced as `serverName_toolName`. Our server is named `claude-teams`, so tools appear as `claude-teams_read_inbox`, `claude-teams_send_message`, etc. Using `read_inbox` without the prefix will not match.
- **Generating YAML with raw f-strings for nested dicts:** Manual YAML generation with f-strings is error-prone for nested structures (missing quotes, incorrect indentation). Use `yaml.dump()` or at minimum a helper function.
- **Not setting `permission: "allow"` uniformly:** Per RELY-02, all tool permissions must be `"allow"` (string) to prevent the agent from hanging on permission prompts in non-interactive mode. The shorthand `"permission": "allow"` applies to all tools at once.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML generation | Manual f-string formatting for nested dicts | `yaml.dump()` from PyYAML | Handles quoting, escaping, indentation; avoids subtle YAML syntax bugs |
| JSON config merging | Manual dict update with edge case handling | `dict.setdefault()` + `json.dumps()` | Standard pattern, handles missing keys correctly |
| File path construction | String concatenation with `/` | `pathlib.Path` operator `/` | Cross-platform, handles separators correctly |
| Agent name sanitization | Custom regex | Reuse existing `_VALID_NAME_RE` from `teams.py` | Already validated and tested |
| System prompt templating | Jinja2 or complex template engine | Python f-strings with `textwrap.dedent` | System prompts are simple interpolation, not complex templates |

**Key insight:** The config generation is fundamentally string building -- YAML frontmatter + markdown body. The complexity is in getting the content *right* (correct tool names, correct permission values, complete instructions), not in the generation mechanism itself.

## Common Pitfalls

### Pitfall 1: Permission Value Type Mismatch
**What goes wrong:** Setting permissions to boolean `true` instead of string `"allow"`. OpenCode treats these differently: `tools` uses booleans (enable/disable), `permission` uses strings ("allow"/"ask"/"deny").
**Why it happens:** The two config sections look similar but have different value types. Easy to mix up.
**How to avoid:** Use the shorthand `"permission": "allow"` which sets all permissions to allow in one declaration. Test by checking the generated YAML contains the string `allow` not `true` in the permission section.
**Warning signs:** Agent hangs waiting for user approval on tool calls when running non-interactively.

### Pitfall 2: MCP Tool Name Prefix Wrong
**What goes wrong:** System prompt tells agent to call `read_inbox()` but the actual tool name in OpenCode is `claude-teams_read_inbox`. Agent cannot find the tool.
**Why it happens:** MCP tools are namespaced with server name prefix and underscore separator. The server name is `claude-teams` (as configured in `opencode.json` mcp section).
**How to avoid:** Always use the fully qualified tool name `claude-teams_read_inbox` in system prompt instructions. The server name in `opencode.json` must match the prefix used in the agent config.
**Warning signs:** Agent reports "tool not found" or ignores inbox polling instructions.

### Pitfall 3: Agent Mode Must Be "primary" for CLI
**What goes wrong:** Generated agent has `mode: "subagent"`. When `opencode run --agent <name>` is executed, OpenCode falls back to the default "build" agent with a warning. The custom system prompt is ignored.
**Why it happens:** "subagent" mode means the agent can only be invoked by another primary agent via the task tool. It cannot be used directly with `opencode run --agent`.
**How to avoid:** Set `mode: "primary"` in the YAML frontmatter. This allows the agent to be used with `opencode run --agent <name>`.
**Warning signs:** Agent starts but behaves as a generic "build" agent without team awareness.

### Pitfall 4: opencode.json Not Present When Agent Spawns
**What goes wrong:** Agent markdown file exists at `.opencode/agents/<name>.md` but `opencode.json` does not have the `claude-teams` MCP server registered. Agent starts but has no access to coordination tools.
**Why it happens:** The agent config enables MCP tools (`claude-teams_*: true`) but the MCP server itself is not defined anywhere.
**How to avoid:** Call `ensure_opencode_json()` before writing agent config. Make it idempotent so it can be called multiple times safely.
**Warning signs:** Agent starts but cannot call any `claude-teams_*` tools.

### Pitfall 5: YAML Frontmatter Delimiter Issues
**What goes wrong:** Generated file has wrong frontmatter delimiters (e.g., missing closing `---`, extra whitespace, or BOM character). OpenCode fails to parse the agent config.
**Why it happens:** Manual string construction with f-strings or incorrect `yaml.dump()` usage.
**How to avoid:** Use `yaml.dump()` for the frontmatter content, wrap with `---\n` prefix and `---\n\n` suffix. Write with `encoding="utf-8"` and no BOM.
**Warning signs:** Agent file exists but OpenCode reports "agent not found" or loads default agent instead.

### Pitfall 6: Existing opencode.json Overwritten
**What goes wrong:** User has an existing `opencode.json` with custom configuration. Our code overwrites it entirely, losing their settings.
**Why it happens:** Using `write_text()` instead of read-modify-write pattern.
**How to avoid:** Always read existing `opencode.json` first, merge the `mcp` section, write back. Use `dict.setdefault("mcp", {})` to preserve other top-level keys.
**Warning signs:** User loses custom model settings, theme, or other MCP servers after spawning a teammate.

### Pitfall 7: Agent Config Not Cleaned Up
**What goes wrong:** After an agent is killed or removed, its `.opencode/agents/<name>.md` file remains. If the same name is used for a different team or with different settings, stale config causes confusion.
**Why it happens:** Cleanup logic only removes team member from config.json and resets tasks, not the agent file.
**How to avoid:** Add cleanup of `.opencode/agents/<name>.md` in the removal/kill flow. This is a Phase 2 concern since we create the files here.
**Warning signs:** Re-spawning an agent with the same name uses stale system prompt.

## Code Examples

Verified patterns from official sources:

### Complete Agent Markdown File (Target Output)
```markdown
---
description: Team agent: researcher in team alpha-squad
model: moonshot-ai/kimi-k2.5
mode: primary
tools:
  read: true
  write: true
  edit: true
  bash: true
  glob: true
  grep: true
  list: true
  webfetch: true
  websearch: true
  todoread: true
  todowrite: true
  claude-teams_*: true
permission: allow
---

# Agent Identity

You are **researcher**, a team member of **alpha-squad**.
- Agent ID: `researcher@alpha-squad`
- Color: blue

# Communication Protocol

## Inbox Polling
You MUST check your inbox regularly using the `claude-teams_read_inbox` tool:
- Call `read_inbox(team_name="alpha-squad", agent_name="researcher")` every 3-5 tool calls
- Always check inbox BEFORE starting new work
- Process all unread messages before continuing

## Sending Messages
Use `claude-teams_send_message` to communicate:
- Direct message: type="message", recipient="<name>", content="...", summary="..."
- To team lead: recipient="team-lead"

# Task Management

## Claiming Tasks
1. Check available tasks: `claude-teams_task_list(team_name="alpha-squad")`
2. Claim a task: `claude-teams_task_update(team_name="alpha-squad", task_id="<id>", owner="researcher", status="in_progress")`
3. Never claim tasks already owned by another agent

## Completing Tasks
1. Update status: `claude-teams_task_update(team_name="alpha-squad", task_id="<id>", status="completed")`
2. Send completion message to team-lead

## Shutdown Protocol
When you receive a shutdown_request message:
1. Finish current atomic operation
2. Report status via send_message
3. Respond with shutdown_response (approve=true)
```

### opencode.json MCP Server Entry (Target Output)
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "claude-teams": {
      "type": "local",
      "command": ["claude-teams"],
      "enabled": true
    }
  }
}
```

### YAML Frontmatter Generation with PyYAML
```python
# Source: PyYAML docs, OpenCode agent format (opencode.ai/docs/agents/)
import yaml

frontmatter = {
    "description": "Team agent: researcher in team alpha-squad",
    "model": "moonshot-ai/kimi-k2.5",
    "mode": "primary",
    "tools": {
        "read": True,
        "write": True,
        "edit": True,
        "bash": True,
        "glob": True,
        "grep": True,
        "list": True,
        "webfetch": True,
        "websearch": True,
        "todoread": True,
        "todowrite": True,
        "claude-teams_*": True,
    },
    "permission": "allow",
}

yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
# Result:
# description: Team agent: researcher in team alpha-squad
# model: moonshot-ai/kimi-k2.5
# mode: primary
# tools:
#   read: true
#   write: true
#   ...
# permission: allow

full_content = f"---\n{yaml_str}---\n\n{system_prompt}"
```

### Manual YAML Generation (Alternative - No PyYAML)
```python
# If PyYAML is not desired as a dependency
def _format_yaml_frontmatter(config: dict) -> str:
    """Generate simple YAML frontmatter from a flat/shallow dict."""
    lines = []
    for key, value in config.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for k, v in value.items():
                if isinstance(v, bool):
                    lines.append(f"  {k}: {'true' if v else 'false'}")
                else:
                    lines.append(f"  {k}: {v}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, str):
            # Quote strings that contain special YAML characters
            if any(c in value for c in ":{}\n#"):
                lines.append(f'{key}: "{value}"')
            else:
                lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"
```

### Pydantic Model for Agent Config (Validation Layer)
```python
from pydantic import BaseModel, Field

class AgentConfig(BaseModel):
    """Configuration for a generated OpenCode agent."""
    name: str
    agent_id: str
    team_name: str
    color: str
    model: str
    description: str = ""

    # These are computed, not user-provided
    tools: dict[str, bool] = Field(default_factory=dict)
    permission: str = "allow"
    mode: str = "primary"

    def to_frontmatter_dict(self) -> dict:
        """Return the dict for YAML frontmatter generation."""
        return {
            "description": self.description or f"Team agent: {self.name} in team {self.team_name}",
            "model": self.model,
            "mode": self.mode,
            "tools": self.tools,
            "permission": self.permission,
        }
```

### Integration Point: spawn_teammate Modification
```python
# In spawner.py -- add config generation before spawn command execution
def spawn_teammate(
    team_name: str,
    name: str,
    prompt: str,
    claude_binary: str,  # actually opencode binary
    lead_session_id: str,
    *,
    model: str = "sonnet",
    subagent_type: str = "general-purpose",
    cwd: str | None = None,
    plan_mode_required: bool = False,
    base_dir: Path | None = None,
    project_dir: Path | None = None,  # NEW: for .opencode/agents/ and opencode.json
) -> TeammateMember:
    # ... existing validation ...
    # ... existing member creation ...
    # ... existing team registration and inbox ...

    # NEW: Generate agent config file
    project = project_dir or Path.cwd()
    config_content = generate_agent_config(
        agent_id=member.agent_id,
        name=name,
        team_name=team_name,
        color=color,
        model=model,
    )
    write_agent_config(project, name, config_content)
    ensure_opencode_json(project, mcp_server_command=["claude-teams"])

    # NEW: Build opencode run command instead of claude command
    cmd = build_opencode_run_command(member, claude_binary)
    # ... tmux spawn ...
```

### Test Pattern for Config Generation
```python
class TestGenerateAgentConfig:
    def test_has_yaml_frontmatter(self):
        content = generate_agent_config(
            agent_id="researcher@test-team",
            name="researcher",
            team_name="test-team",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        assert content.startswith("---\n")
        assert "\n---\n" in content  # closing delimiter

    def test_frontmatter_has_required_fields(self):
        content = generate_agent_config(...)
        # Parse YAML frontmatter
        yaml_section = content.split("---\n")[1]
        parsed = yaml.safe_load(yaml_section)
        assert parsed["mode"] == "primary"
        assert parsed["model"] == "moonshot-ai/kimi-k2.5"
        assert parsed["permission"] == "allow"
        assert parsed["tools"]["claude-teams_*"] is True

    def test_system_prompt_has_identity(self):
        content = generate_agent_config(
            agent_id="researcher@test-team",
            name="researcher",
            team_name="test-team",
            color="blue",
            model="moonshot-ai/kimi-k2.5",
        )
        assert "researcher" in content
        assert "test-team" in content
        assert "researcher@test-team" in content
        assert "blue" in content

    def test_system_prompt_has_inbox_instructions(self):
        content = generate_agent_config(...)
        assert "claude-teams_read_inbox" in content
        assert "read_inbox" in content
        assert "every 3-5 tool calls" in content  # or similar frequency

    def test_system_prompt_has_task_instructions(self):
        content = generate_agent_config(...)
        assert "claude-teams_task_list" in content
        assert "claude-teams_task_update" in content
        assert "in_progress" in content
        assert "completed" in content

    def test_permission_is_string_allow_not_boolean(self):
        content = generate_agent_config(...)
        yaml_section = content.split("---\n")[1]
        parsed = yaml.safe_load(yaml_section)
        assert parsed["permission"] == "allow"
        assert isinstance(parsed["permission"], str)

    def test_all_tools_enabled(self):
        content = generate_agent_config(...)
        yaml_section = content.split("---\n")[1]
        parsed = yaml.safe_load(yaml_section)
        tools = parsed["tools"]
        # All built-in tools enabled
        for tool in ["read", "write", "edit", "bash", "glob", "grep"]:
            assert tools[tool] is True
        # MCP tools enabled
        assert tools["claude-teams_*"] is True


class TestWriteAgentConfig:
    def test_creates_directory_structure(self, tmp_path):
        write_agent_config(tmp_path, "researcher", "content")
        assert (tmp_path / ".opencode" / "agents" / "researcher.md").exists()

    def test_file_content_matches(self, tmp_path):
        write_agent_config(tmp_path, "researcher", "test content")
        assert (tmp_path / ".opencode" / "agents" / "researcher.md").read_text() == "test content"

    def test_overwrites_existing(self, tmp_path):
        write_agent_config(tmp_path, "researcher", "v1")
        write_agent_config(tmp_path, "researcher", "v2")
        assert (tmp_path / ".opencode" / "agents" / "researcher.md").read_text() == "v2"


class TestEnsureOpencodeJson:
    def test_creates_new_file(self, tmp_path):
        ensure_opencode_json(tmp_path, ["claude-teams"])
        config = json.loads((tmp_path / "opencode.json").read_text())
        assert "claude-teams" in config["mcp"]
        assert config["mcp"]["claude-teams"]["type"] == "local"
        assert config["mcp"]["claude-teams"]["command"] == ["claude-teams"]

    def test_preserves_existing_config(self, tmp_path):
        existing = {"model": "moonshot-ai/kimi-k2.5", "theme": "dark"}
        (tmp_path / "opencode.json").write_text(json.dumps(existing))
        ensure_opencode_json(tmp_path, ["claude-teams"])
        config = json.loads((tmp_path / "opencode.json").read_text())
        assert config["model"] == "moonshot-ai/kimi-k2.5"  # preserved
        assert config["theme"] == "dark"  # preserved
        assert "claude-teams" in config["mcp"]  # added

    def test_updates_existing_mcp_entry(self, tmp_path):
        existing = {"mcp": {"other-server": {"type": "remote", "url": "..."}}}
        (tmp_path / "opencode.json").write_text(json.dumps(existing))
        ensure_opencode_json(tmp_path, ["claude-teams"])
        config = json.loads((tmp_path / "opencode.json").read_text())
        assert "other-server" in config["mcp"]  # preserved
        assert "claude-teams" in config["mcp"]  # added
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Claude Code CLI flags (`--agent-id`, `--team-name`) | Agent identity via markdown system prompt | Phase 2 (now) | Context injection shifts from CLI args to config files |
| No agent config files | `.opencode/agents/<name>.md` with YAML frontmatter | Phase 2 (now) | Each agent gets a persistent config file with full system prompt |
| Implicit MCP access via Claude Code env vars | Explicit MCP tool enablement in agent `tools` section | Phase 2 (now) | Must explicitly enable `claude-teams_*` tools per agent |
| `CLAUDECODE=1` env var for tool access | `permission: "allow"` in YAML frontmatter | Phase 2 (now) | Permissions are per-agent, not global env vars |
| No opencode.json needed | `opencode.json` with MCP server registration | Phase 2 (now) | Project-level config file required for MCP server discovery |

**Deprecated/outdated:**
- `build_spawn_command()` will need replacement in Phase 3, but Phase 2 prepares the config files it will reference
- Claude Code's `--agent-id`, `--team-name`, `--agent-color` flags are replaced by system prompt content
- `CLAUDECODE=1` and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` env vars are no longer relevant

## Open Questions

1. **MCP Server Command for claude-teams**
   - What we know: The MCP server is a Python package (`claude-teams`) invoked via `claude-teams` script (entry point in pyproject.toml). It can also be run via `python -m claude_teams.server`.
   - What's unclear: Whether the spawned agent's OpenCode process can find and connect to the MCP server. The server might need to run as a persistent process that all agents share (for state sharing), or each agent might spawn its own MCP server instance (which would isolate state).
   - Recommendation: Use `["claude-teams"]` as the command (entry point). Per MCP-03 requirement, state must be shared across agents via the filesystem backend at `~/.claude/`. Since the MCP server uses filesystem-based persistence (JSON files under `~/.claude/teams/`), multiple MCP server instances should share state correctly as long as file locking works. This is validated in Phase 4.

2. **Cleanup of Agent Config Files on Kill/Remove**
   - What we know: `force_kill_teammate` and `process_shutdown_approved` remove the member from team config and reset tasks. They do not currently clean up config files.
   - What's unclear: Whether we should clean up `.opencode/agents/<name>.md` when an agent is removed, or leave it for potential re-use.
   - Recommendation: Clean up the file on removal. Stale configs with wrong team context are worse than regenerating a fresh config on re-spawn. Add cleanup to both `force_kill_teammate` and `process_shutdown_approved` flows.

3. **PyYAML as Explicit Dependency**
   - What we know: PyYAML 6.0.3 is available in the current environment but not declared in `pyproject.toml`.
   - What's unclear: Whether it will be available in all deployment environments.
   - Recommendation: Either add `pyyaml>=6.0` to `pyproject.toml` dependencies, or implement a simple manual YAML formatter for the known frontmatter structure. PyYAML is the safer choice since it handles edge cases (special characters in team names, quoting rules).

4. **System Prompt Quality for Kimi K2.5**
   - What we know: The system prompt must instruct the agent to poll inbox, manage tasks, and follow protocols. This is pure text that Kimi K2.5 must follow.
   - What's unclear: How well Kimi K2.5 follows complex multi-step instructions compared to Claude. This is flagged in STATE.md as a concern for Phase 4 validation.
   - Recommendation: Keep instructions concise and explicit. Use numbered steps, bold formatting, and specific tool names. Avoid abstract instructions. This will be validated empirically in Phase 4.

5. **Agent Config for Different Roles (Phase 6 Preview)**
   - What we know: Phase 6 adds agent templates (researcher, implementer, reviewer, tester) with role-specific system prompts.
   - What's unclear: Whether Phase 2 should design for extensibility or keep it simple.
   - Recommendation: Phase 2 generates a single config format. The system prompt has a clear structure (identity + communication + tasks) that Phase 6 can extend by appending role-specific sections. Design the function signature to accept an optional `extra_instructions: str` parameter for future use, but don't build the template system now.

## Sources

### Primary (HIGH confidence)
- [OpenCode Agents docs](https://opencode.ai/docs/agents/) -- Agent markdown file format, YAML frontmatter fields, mode options, tool configuration
- [OpenCode Config docs](https://opencode.ai/docs/config/) -- Config merging, agent section in opencode.json, precedence order
- [OpenCode MCP Servers docs](https://opencode.ai/docs/mcp-servers/) -- MCP server registration format, local vs remote, command array
- [OpenCode Permissions docs](https://opencode.ai/docs/permissions/) -- Permission values (allow/ask/deny), per-agent overrides, wildcard patterns
- [OpenCode Tools docs](https://opencode.ai/docs/tools/) -- Built-in tool names (read, write, edit, bash, glob, grep, list, etc.), MCP tool namespacing
- [OpenCode CLI docs](https://opencode.ai/docs/cli/) -- `opencode run --agent <name>` flag

### Secondary (MEDIUM confidence)
- [DeepWiki: Agent System](https://deepwiki.com/sst/opencode/3.2-agent-system) -- Agent loading internals, glob pattern `{agent,agents}/**/*.md`, mode behavior
- [DeepWiki: MCP](https://deepwiki.com/sst/opencode/5.6-model-context-protocol-(mcp)) -- MCP tool namespacing format `serverName_toolName`
- [DeepWiki: Claude Code Compatibility](https://deepwiki.com/fractalmind-ai/oh-my-opencode/8.1-claude-code-compatibility) -- Claude Code to OpenCode concept mapping
- [GitHub Issue #2029](https://github.com/sst/opencode/issues/2029) -- Mode behavior: empty defaults to "all", "primary" for CLI usage
- [Claude Code to OpenCode migration gist](https://gist.github.com/RichardHightower/827c4b655f894a1dd2d14b15be6a33c0) -- Example agent frontmatter with tools and permissions
- [OpenCode Tutorial: MCP Servers](https://opencode-tutorial.com/en/docs/mcp-servers) -- MCP tool prefix separator is underscore

### Tertiary (LOW confidence)
- MCP tool separator (underscore vs slash) -- Multiple sources disagree. Official OpenCode docs use `serverName_*` wildcard pattern with underscore. DeepWiki shows `serverName/toolName` with slash. The underscore pattern is more commonly cited and matches the official tools docs example `mymcp_*`. **Using underscore as separator.**

## Metadata

**Confidence breakdown:**
- Agent markdown format: HIGH -- verified across official docs, DeepWiki internals, community examples
- YAML frontmatter fields: HIGH -- multiple sources confirm description, mode, model, tools, permission
- MCP server registration: HIGH -- official docs with clear JSON schema
- Permission system: HIGH -- official docs with examples, RELY-02 maps directly to `permission: "allow"`
- MCP tool naming: MEDIUM -- underscore separator confirmed in official tools docs and tutorial, but DeepWiki shows slash; using underscore
- Agent mode for CLI: HIGH -- confirmed "primary" or "all" works with `opencode run --agent`, "subagent" does not
- System prompt effectiveness with Kimi K2.5: LOW -- empirical validation needed (Phase 4 concern)

**Research date:** 2026-02-07
**Valid until:** 2026-02-21 (14 days -- OpenCode agent system is stable, unlikely to change format)
