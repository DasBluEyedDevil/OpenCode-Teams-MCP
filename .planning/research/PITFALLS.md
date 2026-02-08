# Domain Pitfalls: OpenCode Multi-Agent Spawning

**Domain:** Programmatic OpenCode spawning for Kimi K2.5 team coordination
**Researched:** 2026-02-07
**Overall Confidence:** MEDIUM-HIGH (verified against official docs and issue trackers)

---

## Critical Pitfalls

Mistakes that cause rewrites, data loss, or architectural dead ends.

---

### Pitfall 1: `opencode run` Hangs Indefinitely on Errors

**What goes wrong:** When `opencode run` encounters an API error (rate limit 429, auth failure, quota exhaustion), it logs the error internally but **never exits**. The process hangs indefinitely, holding the tmux pane hostage. Any parent process waiting for completion (our MCP server) will also hang.

**Why it happens:** OpenCode's error handling path lacks proper `process.exit()` logic for unrecoverable errors. This is a documented, unresolved architectural issue (GitHub issues #8203, #4506, #3213).

**Consequences:**
- Spawned teammates appear alive but are doing nothing
- Our MCP server's spawn function blocks forever waiting for process termination
- Tmux panes accumulate dead-but-not-terminated processes
- No error propagation back to the team lead

**Warning signs:**
- Spawned agent pane shows no output for extended periods
- Agent never reads its inbox or picks up tasks
- tmux `capture-pane` shows an error message but the process hasn't exited

**Prevention:**
1. **Wrap all `opencode run` invocations with a timeout** -- use `timeout <seconds> opencode run ...` on the shell command level. 300-600 seconds is reasonable for initial spawn.
2. **Implement a heartbeat/liveness check** -- periodically verify the tmux pane process is still running AND producing output (not just alive-but-hung).
3. **Set all permissions to "allow"** in agent configs to prevent permission-prompt hangs (see Pitfall 3).
4. **Monitor process exit codes** -- when `opencode run` does exit, it often returns 0 even on errors (issue #2489). Check for actual output, not just exit code.

**Detection:** Poll tmux pane state; if process is alive but no new output in >60 seconds after spawn, assume hung.

**Phase:** Must be addressed in Phase 1 (spawn command construction). Timeout wrapping is the minimum viable fix.

**Confidence:** HIGH -- multiple GitHub issues confirm this is a real, unresolved problem.

**Sources:**
- [opencode run hangs forever on API errors (#8203)](https://github.com/anomalyco/opencode/issues/8203)
- [opencode run and TUI exits hang on v0.15+ (#3213)](https://github.com/anomalyco/opencode/issues/3213)
- [exit code is not non-zero (#2489)](https://github.com/sst/opencode/issues/2489)

---

### Pitfall 2: Permission Prompts Cause Silent Hangs in Non-Interactive Mode

**What goes wrong:** If any tool permission is set to `"ask"` (the default for several operations), `opencode run` will wait indefinitely for user approval that can never come in a headless tmux pane. The agent simply freezes.

**Why it happens:** OpenCode's permission system was designed for interactive TUI use. In non-interactive/`opencode run` mode, there is no UI to approve/reject permission requests. The process blocks waiting for input that never arrives.

**Consequences:**
- Agent spawns successfully but immediately freezes on first tool use
- Looks like the agent is "thinking" but is actually waiting for permission approval
- No error output, no indication of what went wrong
- Extremely hard to debug without knowing to look for this

**Warning signs:**
- Agent starts but never performs any file operations
- Agent responds with text but cannot edit files or run bash commands
- tmux pane shows no error, agent appears idle

**Prevention:**
1. **Set ALL permissions to `"allow"` in generated agent configs.** This is non-negotiable for headless spawning. Use this in the agent markdown frontmatter:
   ```yaml
   permission:
     read: allow
     edit: allow
     bash: allow
     glob: allow
     grep: allow
     list: allow
     write: allow
     webfetch: allow
     websearch: allow
     task: allow
   ```
2. **Never use `"ask"` for any permission** on spawned agents. The agent has no way to respond.
3. **Validate generated agent configs** before spawning -- check that no permission is set to `"ask"`.
4. **Set `"deny"` explicitly** for any tools you want to restrict (not `"ask"`).

**Detection:** If agent is alive but has performed zero tool calls after >30 seconds, suspect permission hang.

**Phase:** Must be addressed in Phase 1 (agent config generation). Template agent configs must have all permissions set to `"allow"`.

**Confidence:** HIGH -- confirmed via official permissions docs and issue #3332 (tools with ask permission hang when invoked).

**Sources:**
- [Tools with ask permission hang when invoked (#3332)](https://github.com/anomalyco/opencode/issues/3332)
- [Add non-interactive mode to opencode run (#10411)](https://github.com/anomalyco/opencode/issues/10411)
- [Permissions docs](https://opencode.ai/docs/permissions/)

---

### Pitfall 3: Agent Config Schema Validation Crashes OpenCode Silently

**What goes wrong:** If agent markdown frontmatter contains schema errors -- particularly using boolean `true`/`false` instead of string `"allow"`/`"deny"` for permissions -- OpenCode refuses to launch with zero useful error output. The only diagnostic is a cryptic `ConfigInvalidError` in internal logs.

**Why it happens:** OpenCode uses strict Zod schema validation for agent configs. Boolean values for permission fields fail validation, but the error reporting is poor. The process hangs during startup rather than printing a clear error.

**Consequences:**
- Spawned OpenCode process starts but never reaches the agent loop
- Tmux pane shows nothing or a single cryptic error line
- Extremely difficult to debug because the config format looks plausible
- Since we're generating configs dynamically, any template bug silently breaks ALL spawns

**Warning signs:**
- All spawned agents fail immediately after config generation change
- tmux pane shows "ConfigInvalidError" text
- OpenCode process exits quickly or hangs at startup

**Prevention:**
1. **Use string values exclusively** for all permission fields: `"allow"`, `"deny"`, `"ask"` -- never booleans.
2. **Validate generated agent configs against the JSON schema** (`https://opencode.ai/config.json`) before writing them.
3. **Include the `$schema` field** in `opencode.json` -- its absence can trigger config rewriting behavior that resolves env vars to their actual values (security issue, see Pitfall 7).
4. **Write integration tests** that spawn a real OpenCode process with generated configs and verify it starts successfully.
5. **Use a known-good template** and only substitute specific values (agent name, team name, prompt text). Minimize dynamic fields.

**Detection:** If OpenCode exits within 5 seconds of spawn or shows "ConfigInvalidError", check generated config syntax.

**Phase:** Phase 1 (agent config generation). Must have config validation before any spawning code.

**Confidence:** HIGH -- confirmed via issue #7810 with specific reproduction steps.

**Sources:**
- [OpenCode will not launch if permissions set as True/False (#7810)](https://github.com/anomalyco/opencode/issues/7810)
- [Config variable overwriting bug (#9086)](https://github.com/anomalyco/opencode/issues/9086)

---

### Pitfall 4: No Native Team Identity -- Context Injection Is Fragile

**What goes wrong:** Unlike Claude Code which has native `--agent-id`, `--team-name`, `--parent-session-id` flags, OpenCode has zero built-in team awareness. Team identity must be injected via system prompts and MCP tools. This injection is fragile: the LLM can ignore the system prompt, hallucinate team member names, or fail to use the MCP tools as instructed.

**Why it happens:** OpenCode is a single-agent tool. Multi-agent coordination is not a first-class feature. All team awareness depends on the LLM correctly interpreting and following system prompt instructions about reading inboxes, sending messages, and updating task status.

**Consequences:**
- Agents may not check their inbox regularly or at all
- Agents may send messages to non-existent team members
- Agents may not report task completion through the proper channel
- Agents may forget their team role mid-conversation (context window fills up)
- Different models (Kimi K2.5 vs Claude) may follow team instructions with varying reliability

**Warning signs:**
- Agent completes work but never updates task status
- Agent stops reading inbox after initial messages
- Agent tries to use tools that don't exist (hallucinating Claude Code team tools)
- Messages accumulate unread in agent inboxes

**Prevention:**
1. **Make the system prompt extremely explicit and structured.** Include exact tool names, exact parameter formats, and step-by-step instructions for inbox polling, message sending, and task updates.
2. **Put critical team instructions at BOTH the start and end** of the system prompt (primacy and recency effects in context windows).
3. **Include concrete examples** in the system prompt: "To check your inbox, call the `read_inbox` tool with `team_name='my-team'` and `agent_name='my-name'`."
4. **Design the MCP tool names to be self-documenting:** `team_read_inbox`, `team_send_message`, `team_update_task` rather than generic names.
5. **Test with Kimi K2.5 specifically** -- different models have different instruction-following characteristics. What works with Claude may not work with Kimi.
6. **Keep team coordination prompts short and directive** -- long prompts dilute the signal.

**Detection:** Monitor inbox read rates and task status updates. If an agent hasn't read its inbox in >2 minutes, it may have lost team context.

**Phase:** Phase 1-2. System prompt design is Phase 1. Reliability tuning is Phase 2 after initial integration testing with Kimi K2.5.

**Confidence:** MEDIUM -- this is an architectural certainty (no native team support), but the severity depends on Kimi K2.5's instruction-following ability, which we haven't tested yet.

---

### Pitfall 5: Model Configuration Is Error-Prone for Third-Party Providers

**What goes wrong:** Configuring Kimi K2.5 through OpenCode requires precise provider configuration with correct `baseURL`, model ID, and special options like `interleaved.field: "reasoning_content"`. Missing any of these causes cryptic failures: wrong model used, reasoning content errors, or silent fallback to a default model.

**Why it happens:** OpenCode's model configuration uses a `"provider/model"` format (e.g., `"kimi-for-coding/k2p5"`) with provider-specific options. Kimi K2.5 requires the `interleaved` option for reasoning content. Additionally, there are known bugs where subagent model specifications leak back to the primary agent (#8946, #6636).

**Consequences:**
- Spawned agents silently use wrong model (e.g., default Claude instead of Kimi K2.5)
- Reasoning content errors crash the agent mid-task
- Model switching bug: if one agent uses a different model, it can corrupt the model setting for the entire session
- API costs spike if wrong provider is used

**Warning signs:**
- Agent responses don't match expected Kimi K2.5 behavior
- Errors about "reasoning_content" in agent output
- Unexpected API billing from wrong provider
- Model name in agent output differs from configured model

**Prevention:**
1. **Pin the model in the agent config**, not just the global config:
   ```yaml
   model: kimi-for-coding/k2p5
   ```
2. **Include the full provider block** in the project-level `opencode.json` with Kimi-specific options:
   ```json
   {
     "provider": {
       "kimi-for-coding": {
         "options": {
           "baseURL": "https://api.novita.ai/openai"
         },
         "models": {
           "k2p5": {
             "name": "Kimi K2.5",
             "reasoning": true,
             "options": {
               "interleaved": { "field": "reasoning_content" }
             }
           }
         }
       }
     }
   }
   ```
3. **Validate the provider is reachable** before spawning agents -- make a test API call.
4. **Use `OPENCODE_CONFIG` env var** to point spawned agents to a generated config file that includes the provider block, ensuring each agent gets the right model config.

**Detection:** Check agent output for model identification strings; verify API provider billing matches expectations.

**Phase:** Phase 1 (config generation). Provider config must be included in the generated config or project-level opencode.json.

**Confidence:** MEDIUM-HIGH -- provider config format confirmed via official docs and community gists. Model switching bugs confirmed via issues #8946 and #6636.

**Sources:**
- [OpenCode + Kimi K2.5 Setup Gist](https://gist.github.com/OmerFarukOruc/26262e9c883b3c2310c507fdf12142f4)
- [Primary agent model switches to subagent model (#8946)](https://github.com/anomalyco/opencode/issues/8946)
- [Subagent model results in model change (#6636)](https://github.com/anomalyco/opencode/issues/6636)
- [Config docs](https://opencode.ai/docs/config/)

---

### Pitfall 6: Config Merging Precedence Is Unintuitive and Buggy

**What goes wrong:** OpenCode merges configs from 5+ sources (remote, global, OPENCODE_CONFIG, project, OPENCODE_CONFIG_CONTENT). The merge behavior is documented as "later sources override earlier ones for conflicting keys, non-conflicting settings are preserved." In practice, agent-level overrides don't always work: global agent configs can take precedence over project-specific ones (issue #4217), and the merge order for MCP server definitions is unpredictable.

**Why it happens:** The config system was designed for single-user, single-project use. When we dynamically generate configs for spawned agents, we're fighting the merge system: our generated project config may be overridden by the user's global config, or vice versa.

**Consequences:**
- Generated agent config (with team-specific system prompt) is silently overridden by a global agent with the same name
- MCP server config (pointing to our claude-teams server) may be missing or overridden
- Permissions set in generated config are overridden by global "always allow" settings cached in memory (#9554)
- Model settings don't stick -- agent uses global model instead of configured one

**Warning signs:**
- Agent doesn't have expected system prompt (team instructions missing)
- Agent doesn't have access to claude-teams MCP tools
- Agent uses wrong model despite config specifying correct one
- `opencode debug config` shows different values than what you wrote

**Prevention:**
1. **Use unique agent names** that won't collide with user's existing agents. Prefix with team context: `team-alpha-worker-1` not `worker`.
2. **Use `OPENCODE_CONFIG` env var** to point to a fully self-contained config file per agent, rather than relying on project-level config that merges with global.
3. **Include ALL necessary config in one file** -- provider, MCP servers, agent definition, permissions. Don't rely on inheritance from global config.
4. **Use `OPENCODE_CONFIG_DIR` env var** to point to a unique `.opencode/` directory per agent with its agent markdown file.
5. **Test with `opencode debug config`** to verify the final merged config is what you expect.
6. **Never name generated agents the same as built-in agents** (`build`, `plan`, `general`, `explore`).

**Detection:** Run `opencode debug config` with the same env vars as the spawned agent; verify MCP servers and agent definitions match expectations.

**Phase:** Phase 1 (config strategy design). This is an architectural decision that affects everything downstream.

**Confidence:** MEDIUM -- confirmed via issue #4217 and config docs. The exact merge behavior for dynamically generated configs is not well-documented and may need empirical testing.

**Sources:**
- [Local agent settings don't override global (#4217)](https://github.com/anomalyco/opencode/issues/4217)
- [Always allow TUI approvals override restrictions (#9554)](https://github.com/anomalyco/opencode/issues/9554)
- [Config docs](https://opencode.ai/docs/config/)

---

## Moderate Pitfalls

Issues that cause bugs, delays, or significant rework but don't require full architectural changes.

---

### Pitfall 7: Config File Rewriting Exposes Secrets

**What goes wrong:** If `opencode.json` is missing the `$schema` field, OpenCode may rewrite the config file on startup, resolving `{env:API_KEY}` placeholders to their actual values. This writes secrets to disk in plaintext.

**Prevention:**
1. Always include `"$schema": "https://opencode.ai/config.json"` in generated config files.
2. Use `OPENCODE_CONFIG_CONTENT` env var for inline config instead of writing config files (if this env var is supported -- needs validation).
3. Pass API keys via environment variables directly, not via config file references.
4. If writing config files, ensure they are in a temp directory with restricted permissions and cleaned up after agent termination.

**Detection:** Check if generated `opencode.json` files contain actual API key values after agent spawn.

**Phase:** Phase 1 (config generation).

**Confidence:** HIGH -- confirmed and fixed in commit 052f887, but the fix requires `$schema` field presence.

**Sources:**
- [Config variables overwritten with actual values (#9086)](https://github.com/anomalyco/opencode/issues/9086)

---

### Pitfall 8: OpenCode Cannot Run in Git Bash tmux on Windows

**What goes wrong:** OpenCode has documented incompatibility with Git Bash tmux on Windows. The existing codebase already uses tmux for spawning, but on Windows this requires WSL or a native tmux port.

**Prevention:**
1. Document Windows requirements clearly: WSL2 with tmux, or native Linux/macOS.
2. Since the existing codebase already uses `fcntl` (Unix-only), Windows support is already limited. Keep tmux as the spawning backend.
3. Consider `opencode serve` + `opencode attach` as a tmux-free alternative for future Windows support (server mode doesn't need tmux).

**Detection:** Check platform at startup; warn if Windows without WSL.

**Phase:** Phase 3 (if Windows support is desired). Not a Phase 1 concern.

**Confidence:** HIGH -- confirmed via issue #10129.

**Sources:**
- [opencode cannot run in Git Bash tmux (#10129)](https://github.com/anomalyco/opencode/issues/10129)

---

### Pitfall 9: MCP Server Discovery Requires Explicit Configuration Per Agent

**What goes wrong:** Each spawned OpenCode instance needs the claude-teams MCP server configured in its config. Unlike Claude Code where the MCP server is available to the parent and inherited, OpenCode requires explicit MCP server declarations. If the MCP config is missing, the agent has no access to team coordination tools.

**Prevention:**
1. **Include the MCP server block in every generated config:**
   ```json
   {
     "mcp": {
       "claude-teams": {
         "type": "local",
         "command": ["uvx", "--from", "git+https://github.com/cs50victor/claude-code-teams-mcp", "claude-teams"],
         "enabled": true
       }
     }
   }
   ```
2. **Validate MCP server availability** after agent spawn -- check that the agent can call at least one team tool.
3. **Consider using the `timeout` option** for MCP server initialization to prevent hangs if the server fails to start.
4. **Watch for MCP server process multiplication** -- each spawned agent starts its own MCP server subprocess. With 5 agents, that's 5 MCP server processes, each with their own state. This is a coordination problem: agents need to share the SAME MCP server state.

**Critical sub-pitfall: Shared vs. per-agent MCP servers.**
The current architecture has a single MCP server instance that all agents connect to. But if each spawned OpenCode instance starts its own MCP server via the `command` config, they'll each have **separate** team state. Messages sent to one server won't appear in another.

**Real solution:** Either:
- (a) Run one MCP server in `remote` mode and have all agents connect to it via URL, or
- (b) Ensure all MCP server instances share the same filesystem state (which they do if they all use `~/.claude/` -- the current design). But they must all use the same `base_dir`.

**Detection:** Spawn two agents on the same team and verify they can message each other. If messages don't arrive, the MCP servers are isolated.

**Phase:** Phase 1 (MCP configuration strategy). This is an architectural decision.

**Confidence:** MEDIUM-HIGH -- MCP config format confirmed via official docs. The shared-state question needs empirical testing.

**Sources:**
- [MCP servers docs](https://opencode.ai/docs/mcp-servers/)

---

### Pitfall 10: `opencode run` Non-Interactive Mode Is Not Truly Non-Interactive

**What goes wrong:** The `opencode run` command is marketed as "non-interactive" but can still prompt for user input in several scenarios: permission approval, model selection on first run, authentication setup. A feature request for a true `--non-interactive` flag exists but is unresolved (#10411). There is also no `--dangerously-skip-permissions` flag yet (#8463).

**Prevention:**
1. **Pre-configure everything** so no interactive prompts are needed: auth tokens, model selection, all permissions set to "allow".
2. **Run `opencode auth login` once** on the host machine before spawning agents.
3. **Test the full spawn flow end-to-end** in a fresh environment to catch any unexpected prompts.
4. **Wrap with `timeout`** as defense-in-depth against unexpected hangs from prompts.

**Detection:** If agent process is alive but idle within 10 seconds of spawn, it may be waiting for an interactive prompt.

**Phase:** Phase 1 (spawn flow design).

**Confidence:** HIGH -- confirmed via issues #10411 and #8463.

**Sources:**
- [Add non-interactive mode to opencode run (#10411)](https://github.com/anomalyco/opencode/issues/10411)
- [Add --dangerously-skip-permissions (#8463)](https://github.com/anomalyco/opencode/issues/8463)

---

### Pitfall 11: Subagent Sessions Are Enclosed -- Cannot Resume or Re-enter

**What goes wrong:** OpenCode's native subagent system creates isolated sessions that close after task completion. The parent cannot re-instruct the subagent, resume its session, or access its full output (only a summary is returned). This is relevant because we might accidentally design our team coordination to rely on OpenCode's native subagent system, which has these limitations.

**Prevention:**
1. **Do NOT use OpenCode's native subagent/task system** for team coordination. Our spawned agents should be independent `opencode run` instances, not subagents of a parent OpenCode process.
2. **Use our MCP-based messaging system** (inbox, tasks) instead of OpenCode's built-in task tool.
3. **Disable or restrict the native `task` tool** in spawned agent configs to prevent confusion between OpenCode's native task system and our MCP-based task system.
4. **Make this distinction explicit in agent system prompts:** "Use the `team_*` MCP tools for coordination. Do NOT use the built-in task tool."

**Detection:** If agents are spawning subagents of their own instead of using MCP messaging, the architecture is wrong.

**Phase:** Phase 1 (agent config and prompt design).

**Confidence:** HIGH -- confirmed via issue #11012 and official docs.

**Sources:**
- [SubAgents are enclosed (#11012)](https://github.com/anomalyco/opencode/issues/11012)

---

### Pitfall 12: Environment Variable Inheritance and API Key Management

**What goes wrong:** OpenCode needs API keys for the configured provider (e.g., `NOVITA_API_KEY` for Kimi K2.5 via Novita AI). When spawning via tmux, the subprocess inherits the parent's environment. If the API key isn't in the parent environment, the spawned agent can't authenticate. If it IS in the parent environment, all agents share the same key and hit the same rate limits.

**Prevention:**
1. **Set API keys in the tmux spawn command** using explicit env var exports:
   ```bash
   NOVITA_API_KEY=xxx opencode run --agent team-worker "Your task..."
   ```
2. **Consider rate limiting:** With multiple agents sharing one API key, rate limits are hit N times faster. Budget for this.
3. **Do NOT write API keys to config files** (see Pitfall 7).
4. **Use environment variables for auth**, not `opencode auth login` interactive flow.
5. **Test what happens when rate-limited:** Does the agent retry? Hang? Crash? (Likely hangs, per Pitfall 1.)

**Detection:** Agents failing with auth errors or 429 rate limits shortly after spawn.

**Phase:** Phase 1 (spawn command construction).

**Confidence:** MEDIUM -- API key passing via env vars is standard practice; rate limiting behavior under multi-agent load needs empirical testing.

---

## Minor Pitfalls

Issues that cause confusion or minor bugs but are easily fixed.

---

### Pitfall 13: Agent Markdown File Naming Becomes Agent ID

**What goes wrong:** In OpenCode, the markdown filename becomes the agent identifier: `worker-1.md` creates agent `worker-1`. If our dynamic config generator creates files with names that conflict with existing agents (e.g., `build.md`, `plan.md`, `general.md`, `explore.md`), the built-in agents are overridden.

**Prevention:**
1. Prefix generated agent filenames with a namespace: `team-<teamname>-<agentname>.md`.
2. Never use reserved names: `build`, `plan`, `general`, `explore`.
3. Validate agent names against a blocklist before generating config files.

**Phase:** Phase 1 (agent config generation).

**Confidence:** HIGH -- confirmed via official agent docs.

---

### Pitfall 14: `fcntl` File Locking Not Available on Windows

**What goes wrong:** The existing codebase uses `fcntl.flock()` for inbox and task file locking. This is Unix-only. If we're targeting Windows users (even via WSL), this will fail.

**Prevention:**
1. Switch to `filelock` library for cross-platform file locking, OR
2. Accept Unix-only constraint and document it clearly.
3. Since OpenCode itself has Windows compatibility issues (Pitfall 8), this may be acceptable.

**Phase:** Phase 3 (if Windows support becomes a goal).

**Confidence:** HIGH -- already documented in existing CONCERNS.md.

---

### Pitfall 15: Tmux Pane ID Tracking Across OpenCode Process Restarts

**What goes wrong:** The current spawner stores tmux pane IDs in team config. If OpenCode crashes and restarts in the same pane, the pane ID remains valid but the process inside is different. Our liveness checks based on pane ID will show "alive" when the original agent is actually dead.

**Prevention:**
1. Track both pane ID and the PID of the OpenCode process inside the pane.
2. Use `tmux list-panes -F "#{pane_id} #{pane_pid}"` to verify the process inside the pane is still the one we spawned.
3. Consider storing the agent's session ID (from `opencode run` output) for more reliable tracking.

**Phase:** Phase 2 (lifecycle management).

**Confidence:** MEDIUM -- tmux behavior is well-documented; OpenCode session tracking needs empirical testing.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Agent config generation | Schema validation crash (P3), permission hang (P2), naming collision (P13) | Use validated templates with string permissions, namespace agent names |
| Spawn command construction | Process hang (P1), non-interactive mode limitations (P10) | Timeout wrapper, pre-configure all auth and permissions |
| MCP server connectivity | Isolated state per agent (P9) | Shared filesystem state OR single remote MCP server |
| Model configuration | Wrong model used (P5), model switching bug | Pin model per-agent, include provider config in agent config |
| Config strategy | Merge precedence bugs (P6), secret exposure (P7) | Self-contained per-agent configs via OPENCODE_CONFIG env var |
| Team context injection | LLM ignores team instructions (P4) | Explicit prompt engineering, test with Kimi K2.5, disable native task tool (P11) |
| Process lifecycle | Hung processes (P1), unreliable exit codes | Timeout + heartbeat + tmux pane monitoring |
| Environment/auth | Rate limiting (P12), API key management | Env var injection, rate limit budgeting |

---

## Summary: The Five Things Most Likely to Burn You

1. **Permission prompts silently hang headless agents** (P2) -- Set all to "allow", never "ask". This is the most common reason OpenCode automation fails.

2. **`opencode run` hangs on errors instead of exiting** (P1) -- Always use timeout wrappers. There is no fix in OpenCode itself yet.

3. **MCP server state isolation** (P9) -- If each agent starts its own MCP server, they can't communicate. Ensure shared filesystem state or single server instance.

4. **Config schema errors crash OpenCode silently** (P3) -- Validate generated configs before spawning. One bad field kills the agent.

5. **No native team awareness** (P4) -- Everything depends on the system prompt and the LLM following it. Test extensively with Kimi K2.5, not just Claude.

---

## Sources

### Official Documentation
- [OpenCode CLI docs](https://opencode.ai/docs/cli/)
- [OpenCode Agents docs](https://opencode.ai/docs/agents/)
- [OpenCode Config docs](https://opencode.ai/docs/config/)
- [OpenCode Permissions docs](https://opencode.ai/docs/permissions/)
- [OpenCode MCP servers docs](https://opencode.ai/docs/mcp-servers/)

### GitHub Issues (Confirmed Bugs)
- [opencode run hangs forever on API errors (#8203)](https://github.com/anomalyco/opencode/issues/8203)
- [opencode run and TUI exits hang (#3213)](https://github.com/anomalyco/opencode/issues/3213)
- [exit code is not non-zero (#2489)](https://github.com/sst/opencode/issues/2489)
- [Tools with ask permission hang (#3332)](https://github.com/anomalyco/opencode/issues/3332)
- [Add non-interactive mode (#10411)](https://github.com/anomalyco/opencode/issues/10411)
- [Permission true/false crashes OpenCode (#7810)](https://github.com/anomalyco/opencode/issues/7810)
- [Config variable overwriting (#9086)](https://github.com/anomalyco/opencode/issues/9086)
- [SubAgents are enclosed (#11012)](https://github.com/anomalyco/opencode/issues/11012)
- [Local agent settings don't override global (#4217)](https://github.com/anomalyco/opencode/issues/4217)
- [Primary agent model switches to subagent model (#8946)](https://github.com/anomalyco/opencode/issues/8946)
- [opencode cannot run in Git Bash tmux (#10129)](https://github.com/anomalyco/opencode/issues/10129)
- [Add --dangerously-skip-permissions (#8463)](https://github.com/anomalyco/opencode/issues/8463)
- [Always allow approvals override restrictions (#9554)](https://github.com/anomalyco/opencode/issues/9554)

### Community Resources
- [OpenCode + Kimi K2.5 Config Gist](https://gist.github.com/OmerFarukOruc/26262e9c883b3c2310c507fdf12142f4)
- [swarm-tools (reference multi-agent architecture)](https://github.com/joelhooks/swarm-tools)

---

*Pitfalls analysis: 2026-02-07*
