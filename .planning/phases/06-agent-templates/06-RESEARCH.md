# Phase 6: Agent Templates - Research

**Researched:** 2026-02-08
**Domain:** Agent role templates, system prompt engineering, config generation extension
**Confidence:** HIGH

## Summary

Phase 6 adds a template system on top of the existing `generate_agent_config()` function from Phase 2. The current config generation produces a single generic system prompt for all agents -- same identity section, same communication protocol, same task management instructions regardless of role. Templates extend this by injecting role-specific behavioral instructions into the generated config, so a "researcher" agent knows to focus on investigation and a "reviewer" agent knows to focus on code review.

The existing codebase already has the perfect integration point: the `subagent_type` parameter flows from `spawn_teammate_tool()` in `server.py` through `spawn_teammate()` in `spawner.py` to the `TeammateMember` model, but is currently stored as a simple string label with no behavioral effect. Templates would map `subagent_type` values (e.g., "researcher", "implementer", "reviewer", "tester") to predefined prompt blocks that get injected into the agent config markdown body alongside the existing generic team protocol sections. Additionally, the user's custom prompt text (already passed as the `prompt` parameter to `spawn_teammate_tool`) can be appended as a customization layer on top of the template.

This phase requires no new dependencies, no changes to the filesystem layout, and no changes to the MCP tool signatures beyond potentially adding an optional `template` parameter. The core work is: (1) defining a template registry data structure, (2) writing the role-specific prompt content for 4 templates, (3) modifying `generate_agent_config()` to accept and inject template content, and (4) wiring the template lookup into the spawn flow.

**Primary recommendation:** Implement templates as a Python dictionary registry in a new `templates.py` module, with each template being a dataclass containing role description, behavioral instructions, tool permission overrides, and optional tool restrictions. Modify `generate_agent_config()` to accept an optional `role_instructions` parameter that gets injected between the identity section and the communication protocol section.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `textwrap` | 3.12+ | Template text formatting with `dedent` | Already used in config_gen.py for prompt construction |
| Python stdlib `dataclasses` | 3.12+ | Template data structure definition | Lightweight, no Pydantic overhead needed for internal-only data |
| Pydantic (existing) | v2 via FastMCP | Validation if templates are exposed via MCP | Already installed, used for all models |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| PyYAML (existing) | >=6.0 | YAML frontmatter in generated configs | Already used in config_gen.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Python dict registry | YAML/JSON template files | Files add I/O and path management complexity; dict is simpler, version-controlled with code, and sufficient for 4-8 templates |
| `dataclasses` | `Pydantic BaseModel` | Pydantic adds validation but templates are developer-defined constants, not user input; dataclass is lighter |
| Inline prompt strings | Jinja2 template engine | Jinja2 is overkill; Python f-strings with `textwrap.dedent` already work in config_gen.py |

**Installation:**
```bash
# No new dependencies needed -- all existing stack
```

## Architecture Patterns

### Recommended Project Structure
```
src/claude_teams/
    templates.py       # NEW: Template registry + template dataclass
    config_gen.py      # MODIFY: Accept role_instructions parameter
    spawner.py         # MODIFY: Look up template, pass to config_gen
    server.py          # MODIFY: Add optional template parameter to spawn_teammate_tool
    models.py          # UNCHANGED
```

### Pattern 1: Template Registry as Module-Level Constants
**What:** Define templates as a dictionary of dataclass instances, keyed by template name. Each template contains a description, role-specific system prompt instructions, and optional tool permission overrides.
**When to use:** Always -- this is the core pattern for this phase.
**Why:** Simple, testable, no I/O, version-controlled with code.
**Example:**
```python
# Source: Codebase pattern (config_gen.py uses module-level constants)
from __future__ import annotations
import textwrap
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentTemplate:
    """Pre-built role template for agent spawning."""
    name: str
    description: str
    role_instructions: str  # Injected into agent config system prompt
    tool_overrides: dict[str, bool] = field(default_factory=dict)  # Override default tool permissions


TEMPLATES: dict[str, AgentTemplate] = {
    "researcher": AgentTemplate(
        name="researcher",
        description="Research and investigation specialist",
        role_instructions=textwrap.dedent("""\
            # Role: Researcher

            You are a **research and investigation specialist**. Your primary focus is
            gathering information, exploring codebases, reading documentation, and
            synthesizing findings into clear reports.

            ## Core Behaviors
            - Read and analyze code thoroughly before drawing conclusions
            - Use grep, glob, and read tools extensively to explore the codebase
            - Use web search and web fetch to find external documentation and references
            - Summarize findings with evidence (file paths, line numbers, URLs)
            - Report uncertainty honestly -- distinguish facts from hypotheses

            ## Working Style
            - Investigate before acting -- understand the full picture first
            - Produce structured reports with clear sections and evidence
            - When asked a question, provide the answer AND the reasoning/sources
            - Flag ambiguities and open questions for the team lead

            ## Tool Priorities
            - Heavy use: read, grep, glob, websearch, webfetch
            - Moderate use: bash (for running analysis commands, not modifications)
            - Light use: write, edit (only for writing reports/findings)
        """),
    ),
    "implementer": AgentTemplate(
        name="implementer",
        description="Code implementation specialist",
        role_instructions=textwrap.dedent("""\
            # Role: Implementer

            You are a **code implementation specialist**. Your primary focus is writing,
            modifying, and building code according to specifications and task requirements.

            ## Core Behaviors
            - Write clean, well-structured code that follows existing codebase conventions
            - Read existing code to understand patterns before writing new code
            - Run tests after making changes to verify correctness
            - Make incremental changes -- small commits, one concern at a time
            - Follow the project's coding standards and naming conventions

            ## Working Style
            - Start by reading the relevant existing code to understand context
            - Implement the simplest correct solution first
            - Write or update tests alongside implementation
            - Report progress to team lead after completing each significant piece
            - Ask for clarification rather than guessing at requirements

            ## Tool Priorities
            - Heavy use: read, write, edit, bash (for running code and tests)
            - Moderate use: grep, glob (for finding related code)
            - Light use: websearch, webfetch (for library documentation)
        """),
    ),
    "reviewer": AgentTemplate(
        name="reviewer",
        description="Code review and quality specialist",
        role_instructions=textwrap.dedent("""\
            # Role: Reviewer

            You are a **code review and quality specialist**. Your primary focus is
            analyzing code changes for correctness, style, security, and maintainability.
            You should NOT make changes yourself -- report findings to the team lead.

            ## Core Behaviors
            - Read code carefully and identify issues: bugs, style violations, security risks
            - Check that code follows existing project conventions and patterns
            - Verify error handling, edge cases, and input validation
            - Look for potential performance issues and unnecessary complexity
            - Provide specific, actionable feedback with file paths and line references

            ## Working Style
            - Review systematically: structure first, then logic, then style
            - Distinguish severity levels: critical bugs vs. minor style issues
            - Suggest specific improvements, not just "this is wrong"
            - Check that tests cover the changed code paths
            - Report findings as structured review comments to the team lead

            ## Tool Priorities
            - Heavy use: read, grep, glob (for code analysis)
            - Moderate use: bash (for running tests, linters -- read-only commands)
            - Avoid: write, edit (reviewers report issues, they don't fix them)
        """),
    ),
    "tester": AgentTemplate(
        name="tester",
        description="Testing and quality assurance specialist",
        role_instructions=textwrap.dedent("""\
            # Role: Tester

            You are a **testing and quality assurance specialist**. Your primary focus is
            writing tests, running test suites, and verifying that code behaves correctly.

            ## Core Behaviors
            - Write comprehensive tests: happy path, edge cases, error conditions
            - Follow existing test patterns and conventions in the project
            - Run tests frequently and report results clearly
            - Identify untested code paths and write tests to cover them
            - Verify that existing tests still pass after changes

            ## Working Style
            - Read the code under test thoroughly before writing tests
            - Follow the project's testing framework and conventions
            - Write tests first when possible (TDD approach)
            - Organize tests logically: one test class per module/function
            - Report test results with pass/fail counts and failure details

            ## Tool Priorities
            - Heavy use: read, write, edit (for writing tests), bash (for running tests)
            - Moderate use: grep, glob (for finding test patterns and code to test)
            - Light use: websearch (for testing library documentation)
        """),
    ),
}


def get_template(name: str) -> AgentTemplate | None:
    """Look up a template by name. Returns None if not found."""
    return TEMPLATES.get(name)


def list_templates() -> list[dict[str, str]]:
    """List all available templates with name and description."""
    return [
        {"name": t.name, "description": t.description}
        for t in TEMPLATES.values()
    ]
```

### Pattern 2: Config Generation with Template Injection
**What:** Extend `generate_agent_config()` to accept an optional `role_instructions` string that gets injected into the system prompt body between the identity section and the communication protocol section.
**When to use:** When spawning an agent with a template.
**Example:**
```python
# Source: Existing config_gen.py pattern, extended
def generate_agent_config(
    agent_id: str,
    name: str,
    team_name: str,
    color: str,
    model: str,
    role_instructions: str = "",    # NEW: from template
    custom_instructions: str = "",  # NEW: user customization per-spawn
) -> str:
    # ... existing frontmatter generation ...

    # Build system prompt body
    body_parts = []

    # Section 1: Identity (existing)
    body_parts.append(textwrap.dedent(f"""\
        # Agent Identity

        You are **{name}**, a member of team **{team_name}**.

        - Agent ID: `{agent_id}`
        - Color: {color}
    """))

    # Section 2: Role instructions (NEW -- from template)
    if role_instructions:
        body_parts.append(role_instructions)

    # Section 3: Custom instructions (NEW -- user per-spawn customization)
    if custom_instructions:
        body_parts.append(textwrap.dedent(f"""\
            # Additional Instructions

            {custom_instructions}
        """))

    # Section 4: Communication protocol (existing)
    body_parts.append(textwrap.dedent(f"""\
        # Communication Protocol
        ...
    """))

    # Section 5: Task management (existing)
    # Section 6: Shutdown protocol (existing)

    body = "\n".join(body_parts)
    config = f"---\n{frontmatter_yaml}---\n\n{body}\n"
    return config
```

### Pattern 3: Spawn Flow Integration
**What:** Wire template lookup into the existing spawn_teammate flow. The `template` parameter on `spawn_teammate_tool()` resolves to role instructions before calling `generate_agent_config()`.
**When to use:** At spawn time.
**Example:**
```python
# In server.py - spawn_teammate_tool
@mcp.tool(name="spawn_teammate")
def spawn_teammate_tool(
    team_name: str,
    name: str,
    prompt: str,
    ctx: Context,
    model: str = "sonnet",
    template: str = "",  # NEW: "researcher", "implementer", "reviewer", "tester"
    plan_mode_required: bool = False,
) -> dict:
    ls = _get_lifespan(ctx)
    resolved_model = translate_model(model, provider=ls.get("provider", "moonshot-ai"))

    # Template lookup
    role_instructions = ""
    if template:
        tmpl = get_template(template)
        if tmpl is None:
            available = ", ".join(TEMPLATES.keys())
            raise ToolError(f"Unknown template: {template!r}. Available: {available}")
        role_instructions = tmpl.role_instructions

    member = spawn_teammate(
        team_name=team_name,
        name=name,
        prompt=prompt,
        opencode_binary=ls["opencode_binary"],
        lead_session_id=ls["session_id"],
        model=resolved_model,
        subagent_type=template or "general-purpose",
        role_instructions=role_instructions,
        plan_mode_required=plan_mode_required,
        project_dir=Path.cwd(),
    )
    return SpawnResult(
        agent_id=member.agent_id,
        name=member.name,
        team_name=team_name,
    ).model_dump()
```

### Pattern 4: Template Listing MCP Tool
**What:** An MCP tool that lists available templates so the team lead can discover what roles are available.
**When to use:** Before spawning, to know what templates exist.
**Example:**
```python
@mcp.tool
def list_agent_templates() -> list[dict]:
    """List all available agent templates with their name and description.
    Templates provide role-specific system prompts for spawned agents."""
    return list_templates()
```

### Anti-Patterns to Avoid
- **Template as separate config files:** Don't store templates in YAML/JSON files on disk. They are developer-defined constants, not user-configurable content. Keeping them in Python code makes them version-controlled, type-checked, and testable without I/O.
- **Overriding the entire system prompt:** Templates should ADD role-specific instructions, not REPLACE the core team protocol (inbox polling, task management, shutdown). An agent that can't communicate with its team is useless regardless of its role.
- **Coupling templates to specific models:** Templates define behavior, not model selection. The `model` parameter is independent -- any template can be used with any model.
- **Making templates too prescriptive:** Templates should guide behavior ("focus on testing") not micromanage ("always write pytest parametrize"). Agents need room to adapt to the specific codebase.
- **Mutating template objects:** Templates should be frozen/immutable. Per-spawn customization uses the `custom_instructions` parameter, not template mutation.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Template text formatting | Manual string concatenation | `textwrap.dedent()` with f-strings | Already used in config_gen.py, handles indentation cleanly |
| Template registry | Database or file-based registry | Module-level `dict[str, AgentTemplate]` | 4 templates do not need database overhead; dict is O(1) lookup |
| Template validation | Custom validation logic | `dataclass(frozen=True)` with type hints | Immutability + type checking at definition time |
| Prompt composition | Custom template engine | String concatenation of prompt sections | The prompt is structured markdown sections joined with newlines; no templating engine complexity needed |

**Key insight:** This phase is fundamentally about structured text composition, not complex system design. The templates are static data (4 prompt strings) and the injection point already exists in `generate_agent_config()`. The complexity budget should go into writing good role prompts, not building elaborate template infrastructure.

## Common Pitfalls

### Pitfall 1: Template Instructions Conflicting with Team Protocol
**What goes wrong:** A template says "avoid using write/edit tools" (reviewer role) but the generic team protocol section tells the agent to update tasks and send messages, which requires tool access. The agent gets confused by contradictory instructions.
**Why it happens:** Template instructions are written in isolation without considering the base system prompt sections they'll be composed with.
**How to avoid:** Template instructions should specify behavioral focus ("focus on code review", "report findings to team lead") rather than hard tool restrictions. Tool restrictions, if needed, should be in the frontmatter `tools` dict, not in prose instructions that can conflict with the team protocol.
**Warning signs:** An agent with a reviewer template stops checking its inbox or fails to respond to shutdown requests.

### Pitfall 2: Custom Instructions Overriding Template Purpose
**What goes wrong:** User passes `custom_instructions="ignore your role and write code"` which completely negates the reviewer template's purpose. There is no guard against adversarial customization.
**Why it happens:** Custom instructions are appended with no validation or guardrails.
**How to avoid:** This is acceptable behavior -- the system should allow customization to override template defaults. Document that custom instructions take priority and the template is a starting point. The team lead is the user and they are trusted to provide sensible customizations.
**Warning signs:** None -- this is expected behavior, not a bug.

### Pitfall 3: Template Parameter Breaking Backward Compatibility
**What goes wrong:** Adding a required `template` parameter to `spawn_teammate_tool` breaks existing callers that don't pass it.
**Why it happens:** Poor API design -- making new parameters required instead of optional.
**How to avoid:** Make `template` optional with default `""` (empty string = no template). When no template is specified, the agent gets the same config as before, preserving backward compatibility.
**Warning signs:** Existing spawn calls that worked before Phase 6 start failing.

### Pitfall 4: Prompt Section Ordering Issues
**What goes wrong:** Role instructions placed after the communication protocol section get less attention from the LLM, because earlier sections tend to have stronger influence on behavior.
**Why it happens:** LLMs exhibit primacy bias -- instructions at the beginning of a prompt have more weight than those at the end.
**How to avoid:** Place role instructions immediately after the identity section (before communication protocol). This gives role-specific behavior instructions high priority while the generic team protocol remains functional but lower priority.
**Warning signs:** Agents ignore their role instructions and behave identically regardless of template.

### Pitfall 5: Not Testing Template Content End-to-End
**What goes wrong:** Templates pass unit tests (string contains expected text) but produce poor agent behavior because the prompt phrasing is ineffective.
**Why it happens:** Unit tests verify structure, not behavioral effectiveness. Prompt engineering requires qualitative evaluation.
**How to avoid:** Write unit tests for template structure (presence in registry, required fields, injection into config). Accept that behavioral effectiveness is validated manually during integration testing. Include clear, specific instructions in templates rather than vague directives.
**Warning signs:** All tests pass but spawned agents with templates behave identically to agents without templates.

## Code Examples

### Existing Config Generation (What Gets Extended)
```python
# Source: src/claude_teams/config_gen.py, lines 13-138
# Current function signature -- no template support
def generate_agent_config(
    agent_id: str,
    name: str,
    team_name: str,
    color: str,
    model: str,
) -> str:
    # ... builds frontmatter dict ...
    # ... builds body with textwrap.dedent ...
    # ... combines frontmatter and body ...
    return config
```

### Existing Spawn Flow (Integration Point)
```python
# Source: src/claude_teams/spawner.py, lines 210-219
# Currently calls generate_agent_config without any role instructions
config_content = generate_agent_config(
    agent_id=member.agent_id,
    name=name,
    team_name=team_name,
    color=color,
    model=model,
)
write_agent_config(project, name, config_content)
```

### Existing MCP Tool (Where Template Parameter Gets Added)
```python
# Source: src/claude_teams/server.py, lines 83-113
# Current spawn_teammate_tool -- subagent_type is stored but has no behavioral effect
@mcp.tool(name="spawn_teammate")
def spawn_teammate_tool(
    team_name: str,
    name: str,
    prompt: str,
    ctx: Context,
    model: str = "sonnet",
    subagent_type: str = "general-purpose",  # <-- could be replaced by template
    plan_mode_required: bool = False,
) -> dict:
```

### Test Pattern for Template Registry
```python
# Source: tests/test_config_gen.py pattern, adapted for templates
import pytest
from claude_teams.templates import (
    TEMPLATES,
    AgentTemplate,
    get_template,
    list_templates,
)

class TestTemplateRegistry:
    def test_has_four_required_templates(self) -> None:
        required = {"researcher", "implementer", "reviewer", "tester"}
        assert required.issubset(TEMPLATES.keys())

    def test_all_templates_are_agent_template_instances(self) -> None:
        for name, template in TEMPLATES.items():
            assert isinstance(template, AgentTemplate)

    def test_all_templates_have_nonempty_role_instructions(self) -> None:
        for name, template in TEMPLATES.items():
            assert len(template.role_instructions.strip()) > 0

    def test_get_template_returns_template(self) -> None:
        tmpl = get_template("researcher")
        assert tmpl is not None
        assert tmpl.name == "researcher"

    def test_get_template_returns_none_for_unknown(self) -> None:
        assert get_template("nonexistent") is None

    def test_list_templates_returns_all(self) -> None:
        result = list_templates()
        assert len(result) >= 4
        names = {t["name"] for t in result}
        assert "researcher" in names

    def test_templates_are_frozen(self) -> None:
        tmpl = get_template("researcher")
        with pytest.raises(AttributeError):
            tmpl.name = "hacked"
```

### Test Pattern for Config Generation with Template
```python
class TestGenerateAgentConfigWithTemplate:
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
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Generic system prompt for all agents | Role-specific template injection | Phase 6 (now) | Agents have specialized behavior based on role |
| `subagent_type` as unused label | `template` parameter with behavioral effect | Phase 6 (now) | Template drives system prompt content |
| No per-spawn customization of behavior | `custom_instructions` parameter | Phase 6 (now) | Users can fine-tune agent behavior at spawn time |

**OpenCode ecosystem context:** OpenCode's own agent system supports role differentiation through per-agent markdown config files with different system prompts and tool permissions. The built-in `build` and `plan` agents are essentially templates -- one has full tool access, the other restricts write/edit. Community projects (rothnic/opencode-agents) have established the pattern of role-specific agents (orchestrator, task executor, test writer, security auditor, refactor engine) with varying tool permissions. This project follows the same pattern but applies it to multi-agent team coordination rather than single-user agent switching.

**Deprecated/outdated:**
- Nothing deprecated -- this is net-new functionality building on Phase 2 foundations.

## Design Decisions

### Decision 1: Template vs. subagent_type Parameter
**Recommendation:** Add a new `template` parameter to `spawn_teammate_tool` rather than overloading `subagent_type`.

**Rationale:** The `subagent_type` field is stored in the `TeammateMember` model and persisted in team config JSON. It was designed as a type label (e.g., "general-purpose"), not a template selector. A separate `template` parameter keeps concerns clean: `template` selects the prompt template (behavioral), `subagent_type` can be derived from the template name or remain independent (metadata).

**Alternative:** Overload `subagent_type` to also serve as template name. This is simpler but muddies the semantics -- "general-purpose" is not a template name, and template names might not be appropriate as agent type labels.

**Recommendation strength:** MEDIUM -- either approach works. The separate parameter is cleaner but adds a parameter to the API.

### Decision 2: Template Content in Python vs. External Files
**Recommendation:** Keep templates as Python constants in `templates.py`.

**Rationale:** With only 4 templates, external files add complexity (file I/O, path resolution, error handling for missing files) without benefit. Python constants are type-checked, importable in tests, and version-controlled alongside the code. If the project later needs user-defined templates, a file-based system can be added without changing the template data structure.

**Recommendation strength:** HIGH -- external files are premature abstraction for 4 items.

### Decision 3: Tool Permission Overrides in Templates
**Recommendation:** Include `tool_overrides` in the template dataclass but DO NOT use it for the initial 4 templates.

**Rationale:** OpenCode's agent config supports tool-level permissions in frontmatter. A reviewer template could disable `write` and `edit` tools. However, this is risky for team coordination -- an agent that can't write might not be able to create report files or update task metadata. For v1, all templates should use the same full-access tool permissions, with behavioral guidance in the prompt rather than hard restrictions. The `tool_overrides` field exists in the dataclass for future use.

**Recommendation strength:** HIGH -- hard tool restrictions cause unexpected failures in team coordination. Behavioral guidance is safer for v1.

### Decision 4: Prompt Section Ordering
**Recommendation:** Insert role instructions between Identity and Communication Protocol sections.

The prompt structure should be:
1. **Agent Identity** (who you are)
2. **Role Instructions** (what you focus on) -- NEW from template
3. **Additional Instructions** (user customization) -- NEW from custom_instructions
4. **Communication Protocol** (how to communicate with team)
5. **Task Management** (how to manage tasks)
6. **Shutdown Protocol** (how to shut down)

**Rationale:** LLMs give more weight to earlier prompt sections. Role instructions should come before generic team protocol so the agent's specialized behavior takes priority. Team protocol is still present and functional but serves as background infrastructure rather than the agent's primary behavioral driver.

**Recommendation strength:** HIGH -- supported by LLM prompt engineering best practices.

## Open Questions

1. **Should `subagent_type` be replaced by `template` or coexist?**
   - What we know: `subagent_type` is stored in TeammateMember and persisted to team config JSON. It's currently set to "general-purpose" by default.
   - What's unclear: Whether consumers of the team config JSON rely on `subagent_type` having specific values, or if it can be changed to template names.
   - Recommendation: Keep both. Set `subagent_type` to the template name when a template is used, falling back to "general-purpose" when no template is specified. This preserves backward compatibility.

2. **Should there be an MCP tool to list available templates?**
   - What we know: The team lead needs to know what templates are available when deciding how to spawn agents.
   - What's unclear: Whether this is better as an MCP tool or as documentation in the team lead's prompt.
   - Recommendation: Add a `list_agent_templates` MCP tool. It's a simple one-liner and makes templates discoverable at runtime without requiring the team lead to memorize template names.

3. **How much tool-restriction guidance should templates provide?**
   - What we know: OpenCode supports per-agent tool permissions in frontmatter. Community patterns (rothnic/opencode-agents) use heavy tool restriction for role separation.
   - What's unclear: Whether tool restrictions work well in multi-process team coordination where agents need to communicate via MCP tools.
   - Recommendation: Start with behavioral guidance only (prompt text), no hard tool restrictions. Monitor agent behavior and add restrictions in a future iteration if agents consistently violate role boundaries.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/claude_teams/config_gen.py` -- current config generation pattern
- Existing codebase: `src/claude_teams/spawner.py` -- current spawn flow and integration points
- Existing codebase: `src/claude_teams/server.py` -- current MCP tool signatures
- Existing codebase: `tests/test_config_gen.py` -- current test patterns
- [OpenCode Agents documentation](https://opencode.ai/docs/agents/) -- agent config format, frontmatter fields, mode types
- [OpenCode Agent System (DeepWiki)](https://deepwiki.com/sst/opencode/3.2-agent-system) -- agent configuration schema, loading mechanism

### Secondary (MEDIUM confidence)
- [rothnic/opencode-agents custom coding agents](https://github.com/rothnic/opencode-agents/blob/main/docs/custom-coding-agents.md) -- community role-based agent patterns (orchestrator, test writer, security auditor, refactor engine)
- [oh-my-opencode AGENTS.md template request](https://github.com/code-yeongyu/oh-my-opencode/issues/614) -- AGENTS.md protocol for agent configuration
- [Claude Prompt Engineering Best Practices 2026](https://promptbuilder.cc/blog/claude-prompt-engineering-best-practices-2026) -- prompt structuring, role definitions, self-check mechanisms
- [Prompt Engineering for AI Agents (PromptHub)](https://www.prompthub.us/blog/prompt-engineering-for-ai-agents) -- multi-agent role design, base prompt with policy variables
- [OpenAI Practical Guide to Building Agents](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf) -- hub-and-spoke model, specialist agent roles

### Tertiary (LOW confidence)
- None -- all findings verified with at least two sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, extending existing patterns
- Architecture: HIGH -- clear integration points in existing code, minimal surface area change
- Template content: MEDIUM -- prompt effectiveness requires empirical validation; structure is solid but behavioral outcomes depend on prompt quality
- Pitfalls: HIGH -- well-understood prompt engineering concerns, verified with multiple sources

**Research date:** 2026-02-08
**Valid until:** 2026-03-08 (30 days -- this is stable domain knowledge about prompt engineering and internal code architecture; no external API dependencies)
