---
phase: 06-agent-templates
plan: 01
subsystem: config
tags: [dataclass, templates, system-prompt, config-gen, textwrap]

# Dependency graph
requires:
  - phase: 02-agent-config-generation
    provides: "generate_agent_config() function and config_gen.py module"
provides:
  - "AgentTemplate frozen dataclass with name, description, role_instructions, tool_overrides"
  - "TEMPLATES registry with 4 built-in templates: researcher, implementer, reviewer, tester"
  - "get_template() and list_templates() helper functions"
  - "generate_agent_config() role_instructions and custom_instructions parameters"
affects: [06-agent-templates, spawner, server]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Frozen dataclass constants for immutable template registry", "Body-parts list pattern for conditional prompt section injection"]

key-files:
  created:
    - "src/claude_teams/templates.py"
    - "tests/test_templates.py"
  modified:
    - "src/claude_teams/config_gen.py"
    - "tests/test_config_gen.py"

key-decisions:
  - "Templates use frozen dataclass, not Pydantic, since they are developer-defined constants"
  - "tool_overrides field exists but is empty for all v1 templates (behavioral guidance only)"
  - "Body refactored to list-of-parts joined by double newlines for conditional section injection"

patterns-established:
  - "Template registry as module-level dict of frozen dataclass instances"
  - "Conditional prompt injection via body_parts list pattern in config_gen"

# Metrics
duration: 4min
completed: 2026-02-08
---

# Phase 6 Plan 1: Template Data Model Summary

**Frozen AgentTemplate dataclass with 4 role templates (researcher, implementer, reviewer, tester) and config_gen extension for role/custom instruction injection**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-08T16:53:03Z
- **Completed:** 2026-02-08T16:56:50Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created templates.py with AgentTemplate frozen dataclass and 4 built-in role templates
- Extended generate_agent_config() with role_instructions and custom_instructions parameters
- Role instructions injected between Identity and Communication Protocol sections (primacy bias)
- Full backward compatibility verified: identical output when no template params provided

## Task Commits

Each task was committed atomically:

1. **Task 1: Create templates.py with AgentTemplate dataclass and 4 built-in templates** - `d0f4093` (feat)
2. **Task 2: Extend generate_agent_config with role_instructions and custom_instructions** - `ee05c50` (feat)

## Files Created/Modified
- `src/claude_teams/templates.py` - AgentTemplate dataclass, TEMPLATES registry, get_template(), list_templates()
- `tests/test_templates.py` - 10 tests for template registry (frozen, content, helpers)
- `src/claude_teams/config_gen.py` - Added role_instructions and custom_instructions params, refactored body to parts list
- `tests/test_config_gen.py` - 9 new tests in TestGenerateAgentConfigWithTemplate (injection, ordering, backward compat)

## Decisions Made
- Templates use frozen dataclass (not Pydantic) since they are internal developer-defined constants, not user input
- tool_overrides field included in dataclass but left empty for all v1 templates -- behavioral guidance in prompt text, not hard tool restrictions
- Body construction refactored from single textwrap.dedent f-string to list of parts joined by "\n\n" for clean conditional section injection
- Custom instructions wrapped with "# Additional Instructions" heading; role instructions injected as-is (they already have their own heading)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Template data model and config gen extension complete
- Plan 02 can now wire templates into spawn flow (spawner.py) and add MCP tools (server.py)
- get_template() returns role_instructions string ready to pass to generate_agent_config()
- list_templates() returns dicts ready for MCP tool response

## Self-Check: PASSED

- All 4 files verified present on disk
- Commit `d0f4093` verified in git log (Task 1)
- Commit `ee05c50` verified in git log (Task 2)
- 10/10 template tests pass, 41/41 config gen tests pass (including 9 new)
- Full suite: 294 passed, 2 pre-existing failures (Windows tmux + messaging race)

---
*Phase: 06-agent-templates*
*Completed: 2026-02-08*
