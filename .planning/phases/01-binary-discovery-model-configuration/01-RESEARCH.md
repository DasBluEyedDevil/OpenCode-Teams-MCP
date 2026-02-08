# Phase 1: Binary Discovery & Model Configuration - Research

**Researched:** 2026-02-07
**Domain:** OpenCode CLI binary discovery, version validation, Kimi K2.5 model/provider translation
**Confidence:** MEDIUM-HIGH

## Summary

Phase 1 covers two distinct capabilities: (1) finding the OpenCode binary on PATH and validating it meets the minimum version requirement, and (2) translating abstract model names ("sonnet", "opus", "haiku") into the correct Kimi K2.5 `provider/model` format for multiple backends (Novita AI, Moonshot, OpenRouter). Both are pure Python logic with no external dependencies beyond the existing stack. No new Python packages are required.

The binary discovery is a straightforward `shutil.which("opencode")` swap from the existing `discover_claude_binary()` pattern. Version validation is new -- the current codebase does not validate the Claude binary version. OpenCode exposes `opencode --version` / `opencode -v` which outputs a semver string. The minimum version for Kimi K2.5 support is v1.1.52 (not v1.1.49 as originally stated in the roadmap -- the changelog shows v1.1.52 is where Kimi K2.5 fixes for image reading and thinking mode landed, though the base moonshot-ai provider registration likely appeared in an earlier version via PR #10835). The safer floor is v1.1.52 since it includes critical K2.5-specific fixes.

Model translation maps the existing `Literal["sonnet", "opus", "haiku"]` shorthand to `provider/model` format strings that OpenCode understands. All three aliases map to `kimi-k2.5` since this project uses a single model, but through different providers: `moonshot-ai/kimi-k2.5` (direct international), `moonshot-ai-china/kimi-k2.5` (direct China), `openrouter/moonshotai/kimi-k2.5` (via OpenRouter), or a custom provider like `kimi-for-coding/k2p5` (via Novita AI or self-hosted). Provider configuration must reference API keys via `{env:VAR_NAME}` syntax and never hardcode credentials.

**Primary recommendation:** Implement `discover_opencode_binary()` with version validation via `subprocess.run(["opencode", "--version"])`, and a `ModelTranslator` class that maps alias names to provider-specific model strings based on a configured backend.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `shutil` | 3.12+ | `shutil.which("opencode")` for binary discovery | Already used in existing `discover_claude_binary()` |
| Python stdlib `subprocess` | 3.12+ | `subprocess.run(["opencode", "--version"])` for version extraction | Already used in existing spawner for tmux commands |
| Python stdlib `re` | 3.12+ | Regex extraction of semver from version output | Lightest option for `v1.2.3` pattern extraction |
| Python stdlib `packaging.version` | 3.12+ | `Version("1.1.52")` for semver comparison | Part of Python stdlib/setuptools, handles comparison operators correctly |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pydantic (already installed) | v2 via FastMCP | Data models for provider config, model translation maps | For `ProviderConfig` and `ModelSpec` data classes |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `packaging.version` | `semver` PyPI package | `semver` is more strict and feature-rich but adds a dependency; `packaging.version` is sufficient for `>=` comparison and is already available |
| `re` for version parsing | String splitting (`output.split(".")`) | Regex handles edge cases like `v` prefix, build metadata; splitting is fragile |
| Hardcoded provider strings | Config file / env var for provider selection | Config is more flexible but adds complexity; start hardcoded, make configurable when needed |

**Installation:**
```bash
# No new dependencies needed -- all stdlib + existing Pydantic
```

## Architecture Patterns

### Recommended Project Structure
```
src/claude_teams/
  spawner.py          # MODIFY: replace discover_claude_binary with discover_opencode_binary + version check
  models.py           # MODIFY: update model field type, add provider config models
  server.py           # MODIFY: update lifespan to use new discovery, update model Literal
  config_gen.py       # NEW (Phase 2, but model translation is Phase 1 foundation)
```

### Pattern 1: Binary Discovery with Version Validation
**What:** Find the `opencode` binary on PATH, then run it with `--version` to extract and validate the version meets minimum requirements.
**When to use:** At server startup (in the `app_lifespan` function).
**Example:**
```python
# Source: Existing spawner.py pattern + OpenCode CLI docs (opencode.ai/docs/cli/)
import re
import shlex
import shutil
import subprocess
from packaging.version import Version

MINIMUM_OPENCODE_VERSION = Version("1.1.52")

def discover_opencode_binary() -> str:
    """Find opencode on PATH and validate its version."""
    path = shutil.which("opencode")
    if path is None:
        raise FileNotFoundError(
            "Could not find 'opencode' binary on PATH. "
            "Install OpenCode (https://opencode.ai) or ensure it is in your PATH."
        )
    return path

def validate_opencode_version(binary_path: str) -> str:
    """Run opencode --version and verify it meets minimum requirements.

    Returns the version string on success.
    Raises RuntimeError if version is too old or cannot be parsed.
    """
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Timed out running '{binary_path} --version'. "
            "OpenCode may be hung or misconfigured."
        )
    except FileNotFoundError:
        raise RuntimeError(f"Binary not found at '{binary_path}'")

    output = result.stdout.strip() or result.stderr.strip()
    # Extract semver from output like "1.1.52" or "v1.1.52" or "opencode v1.1.52"
    match = re.search(r"v?(\d+\.\d+\.\d+)", output)
    if not match:
        raise RuntimeError(
            f"Could not parse version from opencode output: {output!r}"
        )

    version_str = match.group(1)
    version = Version(version_str)

    if version < MINIMUM_OPENCODE_VERSION:
        raise RuntimeError(
            f"OpenCode version {version_str} is too old. "
            f"Minimum required: {MINIMUM_OPENCODE_VERSION}. "
            f"Update with: curl -fsSL https://opencode.ai/install | bash"
        )

    return version_str
```

### Pattern 2: Model Name Translation
**What:** Map abstract model aliases ("sonnet", "opus", "haiku") to concrete `provider/model` strings for the configured backend. Also accept raw `provider/model` strings passthrough for direct specification.
**When to use:** In `spawn_teammate_tool` when building spawn commands and agent configs.
**Example:**
```python
# Source: OpenCode config docs (opencode.ai/docs/config/), PR #10835, provider docs
from typing import Literal

# Provider-specific model ID formats for Kimi K2.5
PROVIDER_MODEL_MAP: dict[str, str] = {
    "moonshot-ai": "moonshot-ai/kimi-k2.5",
    "moonshot-ai-china": "moonshot-ai-china/kimi-k2.5",
    "openrouter": "openrouter/moonshotai/kimi-k2.5",
    "novita": "novita/moonshotai/kimi-k2.5",
}

# All Claude model aliases map to Kimi K2.5
MODEL_ALIASES: dict[str, str] = {
    "sonnet": "kimi-k2.5",
    "opus": "kimi-k2.5",
    "haiku": "kimi-k2.5",
}

DEFAULT_PROVIDER = "moonshot-ai"

def translate_model(
    model_alias: str,
    provider: str = DEFAULT_PROVIDER,
) -> str:
    """Translate a model alias to provider/model format.

    Accepts:
      - Claude aliases: "sonnet", "opus", "haiku" -> provider-specific kimi-k2.5 string
      - Direct provider/model: "moonshot-ai/kimi-k2.5" -> passthrough unchanged
      - Model name only: "kimi-k2.5" -> prepends default provider

    Returns: "provider/model" string for use in opencode --model flag and agent configs.
    """
    # Passthrough: already in provider/model format
    if "/" in model_alias:
        return model_alias

    # Translate Claude aliases
    model_name = MODEL_ALIASES.get(model_alias, model_alias)

    # Build provider/model string
    if provider in PROVIDER_MODEL_MAP:
        # Use the known format for this provider
        return PROVIDER_MODEL_MAP[provider]

    # Fallback: provider/model_name
    return f"{provider}/{model_name}"
```

### Pattern 3: Provider Credential Configuration
**What:** Generate the provider configuration block for `opencode.json` that references credentials via environment variables, never hardcoding actual keys.
**When to use:** When validating or generating project-level OpenCode configuration.
**Example:**
```python
# Source: OpenCode config docs (opencode.ai/docs/config/), provider docs

PROVIDER_CONFIGS: dict[str, dict] = {
    "moonshot-ai": {
        "options": {
            "apiKey": "{env:MOONSHOT_API_KEY}",
        },
    },
    "moonshot-ai-china": {
        "options": {
            "apiKey": "{env:MOONSHOT_API_KEY}",
        },
    },
    "openrouter": {
        "options": {
            "apiKey": "{env:OPENROUTER_API_KEY}",
        },
    },
    "novita": {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Novita AI",
        "options": {
            "baseURL": "https://api.novita.ai/openai",
            "apiKey": "{env:NOVITA_API_KEY}",
        },
        "models": {
            "moonshotai/kimi-k2.5": {
                "name": "Kimi K2.5",
                "reasoning": True,
                "limit": {
                    "context": 262144,
                    "output": 32768,
                },
            },
        },
    },
}

def get_provider_config(provider: str) -> dict:
    """Get the provider configuration block for opencode.json.

    Returns a dict that can be merged into the opencode.json provider section.
    Credentials use {env:VAR_NAME} syntax -- never actual values.
    """
    if provider not in PROVIDER_CONFIGS:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            f"Supported: {', '.join(PROVIDER_CONFIGS.keys())}"
        )
    return {provider: PROVIDER_CONFIGS[provider]}


def get_credential_env_var(provider: str) -> str:
    """Return the environment variable name needed for the given provider.

    Useful for validation: check that the env var is set before spawning.
    """
    env_vars = {
        "moonshot-ai": "MOONSHOT_API_KEY",
        "moonshot-ai-china": "MOONSHOT_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "novita": "NOVITA_API_KEY",
    }
    return env_vars.get(provider, f"{provider.upper().replace('-', '_')}_API_KEY")
```

### Anti-Patterns to Avoid

- **Hardcoding API keys in generated configs:** Use `{env:VAR_NAME}` syntax. OpenCode resolves these at runtime. Hardcoding creates security risks and breaks portability.
- **Validating version only by exit code:** `opencode --version` returns 0 regardless. Parse the actual output string for the version number.
- **Blocking on `opencode --version` without timeout:** If the binary hangs (misconfigured installation), the server startup blocks forever. Always use `timeout=10` on subprocess calls.
- **Assuming version output format is stable:** Different OpenCode versions may output `1.1.52`, `v1.1.52`, or `opencode v1.1.52`. Use regex that handles all variants.
- **Trying to use `packaging.version.Version` on pre-release strings without handling:** If OpenCode outputs `1.2.0-beta.1`, `packaging.version.Version` handles this but comparison semantics differ. Strip pre-release for simple `>=` checks.
- **Mapping all aliases to the same model without documenting why:** The mapping of "sonnet" -> kimi-k2.5, "opus" -> kimi-k2.5, "haiku" -> kimi-k2.5 may confuse users who expect different capability tiers. Document that Kimi K2.5 is the only supported model and all aliases are equivalent.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Semver parsing | Custom string splitting or tuple comparison | `packaging.version.Version` | Handles pre-release, build metadata, PEP 440 compatibility |
| Binary path discovery | Manual `os.path.exists` + PATH searching | `shutil.which()` | Cross-platform, handles PATHEXT on Windows, edge cases |
| JSON config merging | Dict update loops | Pydantic models with `model_dump()` | Type safety, validation, serialization consistency |
| Version output parsing | `output.split()[0]` | `re.search(r"v?(\d+\.\d+\.\d+)", output)` | Handles prefix, whitespace, multi-line output robustly |

**Key insight:** This phase is mostly stdlib Python with existing patterns from the codebase. The only "new" logic is version validation and model translation -- both are well-understood string processing problems that should be kept simple.

## Common Pitfalls

### Pitfall 1: opencode --version Output Format Uncertainty
**What goes wrong:** The exact output format of `opencode --version` is not formally documented. It could be `1.1.52`, `v1.1.52`, `opencode version 1.1.52`, or something else. Code that assumes one format breaks with updates.
**Why it happens:** CLI version output formats are not standardized and change between releases.
**How to avoid:** Use lenient regex `r"v?(\d+\.\d+\.\d+)"` that extracts the first semver-like string from any output. Test with multiple output format variations.
**Warning signs:** Version validation fails immediately on a valid OpenCode installation.

### Pitfall 2: Minimum Version Discrepancy
**What goes wrong:** The roadmap says v1.1.49+, but research shows Kimi K2.5 fixes landed in v1.1.52. Using the wrong minimum version means spawned agents hit K2.5-specific bugs.
**Why it happens:** The moonshot-ai provider was registered via PR #10835 (pre-v1.1.49), but critical fixes for K2.5 image reading and thinking mode appeared in v1.1.52. The provider existing does not mean it works correctly.
**How to avoid:** Set minimum to v1.1.52. Add a comment explaining why not v1.1.49. Consider logging a warning for versions between 1.1.49 and 1.1.51.
**Warning signs:** Kimi K2.5 agents fail with "reasoning_content" errors or image handling crashes.

### Pitfall 3: Provider-Specific Model ID Formats
**What goes wrong:** Each provider uses a different model ID format for the same Kimi K2.5 model. Using `moonshot-ai/kimi-k2.5` with OpenRouter fails because OpenRouter expects `moonshotai/kimi-k2.5` (no hyphen in `moonshotai`).
**Why it happens:** Different providers register models with different naming conventions. Moonshot's own provider uses `kimi-k2.5`; OpenRouter uses `moonshotai/kimi-k2.5`; the community gist uses `kimi-for-coding/k2p5`.
**How to avoid:** Maintain an explicit lookup table per provider rather than constructing model IDs programmatically.
**Warning signs:** "Model not found" errors that only happen with certain providers.

### Pitfall 4: Missing API Key Environment Variable
**What goes wrong:** Provider config references `{env:MOONSHOT_API_KEY}` but the variable is not set. OpenCode silently starts but fails on the first API call with a cryptic auth error. The spawned agent hangs (pitfall from prior research: opencode run hangs on API errors).
**Why it happens:** Environment variables are the user's responsibility, but there is no upfront validation.
**How to avoid:** At spawn time, check that the required env var for the configured provider is set. Fail fast with a clear error message naming the missing variable.
**Warning signs:** Agent spawns but immediately hangs or shows no output.

### Pitfall 5: packaging.version Not Installed
**What goes wrong:** `packaging` is typically available because it is a build dependency of pip/setuptools, but in some minimal environments it may not be importable. The import fails at server startup.
**Why it happens:** `packaging` is not part of Python's core stdlib -- it is a separate PyPI package that is usually bundled with pip.
**How to avoid:** Either add `packaging` as an explicit dependency in `pyproject.toml`, or use a simpler manual tuple comparison: `tuple(int(x) for x in version_str.split(".")) >= (1, 1, 52)`. The tuple approach has no dependency and works for the simple `>=` comparison needed here.
**Warning signs:** `ImportError: No module named 'packaging'` at startup.

### Pitfall 6: Kimi For Coding Custom Provider Complexity
**What goes wrong:** The community gist shows a complex custom provider config (`kimi-for-coding/k2p5`) with npm packages, interleaved reasoning fields, and custom baseURL. This is a valid alternative path but significantly more complex than using OpenCode's built-in `moonshot-ai` provider.
**Why it happens:** Before PR #10835 was merged, users had to create custom providers for Kimi K2.5. After the PR, `moonshot-ai/kimi-k2.5` is a registered model.
**How to avoid:** Default to the built-in `moonshot-ai` provider. Only support the custom provider path as an escape hatch for users who need it.
**Warning signs:** Users following outdated guides configure `kimi-for-coding/k2p5` when `moonshot-ai/kimi-k2.5` would work directly.

## Code Examples

Verified patterns from official sources:

### Binary Discovery (Existing Pattern to Adapt)
```python
# Source: Existing spawner.py, line 14-21
# Current code -- this is what we're replacing
def discover_claude_binary() -> str:
    path = shutil.which("claude")
    if path is None:
        raise FileNotFoundError(
            "Could not find 'claude' binary on PATH. "
            "Install Claude Code or ensure it is in your PATH."
        )
    return path

# New code -- same pattern, different binary + version check
def discover_opencode_binary() -> str:
    path = shutil.which("opencode")
    if path is None:
        raise FileNotFoundError(
            "Could not find 'opencode' binary on PATH. "
            "Install OpenCode (https://opencode.ai) or ensure it is in your PATH."
        )
    validate_opencode_version(path)
    return path
```

### Server Lifespan Update
```python
# Source: Existing server.py, lines 22-26
# Current code
@lifespan
async def app_lifespan(server):
    claude_binary = discover_claude_binary()
    session_id = str(uuid.uuid4())
    yield {"claude_binary": claude_binary, "session_id": session_id, "active_team": None}

# New code
@lifespan
async def app_lifespan(server):
    opencode_binary = discover_opencode_binary()
    session_id = str(uuid.uuid4())
    yield {"opencode_binary": opencode_binary, "session_id": session_id, "active_team": None}
```

### Model Parameter Update in spawn_teammate_tool
```python
# Source: Existing server.py, lines 72-78
# Current code
@mcp.tool(name="spawn_teammate")
def spawn_teammate_tool(
    ...
    model: Literal["sonnet", "opus", "haiku"] = "sonnet",
    ...
) -> dict:

# New code -- accept both aliases and direct provider/model strings
@mcp.tool(name="spawn_teammate")
def spawn_teammate_tool(
    ...
    model: str = "sonnet",  # Accepts: "sonnet", "opus", "haiku", or "provider/model"
    ...
) -> dict:
    ls = _get_lifespan(ctx)
    resolved_model = translate_model(model, provider=ls.get("provider", DEFAULT_PROVIDER))
    # ... pass resolved_model to spawn_teammate
```

### Version Comparison Without External Dependencies
```python
# Alternative if packaging is not available
def _parse_version_tuple(version_str: str) -> tuple[int, ...]:
    """Parse '1.1.52' to (1, 1, 52) for simple comparison."""
    return tuple(int(x) for x in version_str.split("."))

MIN_VERSION = (1, 1, 52)

def validate_opencode_version(binary_path: str) -> str:
    # ... subprocess.run to get version output ...
    version_tuple = _parse_version_tuple(version_str)
    if version_tuple < MIN_VERSION:
        raise RuntimeError(f"OpenCode {version_str} too old, need >= 1.1.52")
    return version_str
```

### Test Pattern for Binary Discovery
```python
# Source: Existing test_spawner.py, lines 50-61
# Adapted for OpenCode
class TestDiscoverOpencodeBinary:
    @patch("claude_teams.spawner.shutil.which")
    @patch("claude_teams.spawner.subprocess.run")
    def test_found_and_valid_version(self, mock_run, mock_which):
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value = MagicMock(stdout="1.1.52\n", stderr="", returncode=0)
        assert discover_opencode_binary() == "/usr/local/bin/opencode"
        mock_which.assert_called_once_with("opencode")

    @patch("claude_teams.spawner.shutil.which")
    def test_not_found(self, mock_which):
        mock_which.return_value = None
        with pytest.raises(FileNotFoundError, match="opencode"):
            discover_opencode_binary()

    @patch("claude_teams.spawner.shutil.which")
    @patch("claude_teams.spawner.subprocess.run")
    def test_version_too_old(self, mock_run, mock_which):
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value = MagicMock(stdout="1.1.40\n", stderr="", returncode=0)
        with pytest.raises(RuntimeError, match="too old"):
            discover_opencode_binary()

    @patch("claude_teams.spawner.shutil.which")
    @patch("claude_teams.spawner.subprocess.run")
    def test_version_with_v_prefix(self, mock_run, mock_which):
        mock_which.return_value = "/usr/local/bin/opencode"
        mock_run.return_value = MagicMock(stdout="v1.1.53\n", stderr="", returncode=0)
        assert discover_opencode_binary() == "/usr/local/bin/opencode"
```

### Test Pattern for Model Translation
```python
class TestTranslateModel:
    def test_sonnet_alias(self):
        result = translate_model("sonnet", provider="moonshot-ai")
        assert result == "moonshot-ai/kimi-k2.5"

    def test_opus_alias(self):
        result = translate_model("opus", provider="moonshot-ai")
        assert result == "moonshot-ai/kimi-k2.5"

    def test_haiku_alias(self):
        result = translate_model("haiku", provider="openrouter")
        assert result == "openrouter/moonshotai/kimi-k2.5"

    def test_passthrough_provider_model(self):
        result = translate_model("moonshot-ai/kimi-k2.5")
        assert result == "moonshot-ai/kimi-k2.5"

    def test_novita_provider(self):
        result = translate_model("sonnet", provider="novita")
        assert result == "novita/moonshotai/kimi-k2.5"

    def test_unknown_alias_treated_as_model_name(self):
        result = translate_model("kimi-k2.5", provider="moonshot-ai")
        assert result == "moonshot-ai/kimi-k2.5"
```

### Provider Config Generation Test
```python
class TestGetProviderConfig:
    def test_moonshot_ai(self):
        config = get_provider_config("moonshot-ai")
        assert "moonshot-ai" in config
        assert config["moonshot-ai"]["options"]["apiKey"] == "{env:MOONSHOT_API_KEY}"

    def test_openrouter(self):
        config = get_provider_config("openrouter")
        assert config["openrouter"]["options"]["apiKey"] == "{env:OPENROUTER_API_KEY}"

    def test_novita_has_base_url(self):
        config = get_provider_config("novita")
        assert config["novita"]["options"]["baseURL"] == "https://api.novita.ai/openai"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider_config("nonexistent")

    def test_no_hardcoded_keys(self):
        """No provider config should contain actual API key values."""
        for provider in PROVIDER_CONFIGS:
            config = get_provider_config(provider)
            config_str = str(config)
            assert "sk-" not in config_str
            assert "{env:" in config_str
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `shutil.which("claude")` | `shutil.which("opencode")` + version validation | Phase 1 (now) | Binary discovery becomes version-aware |
| `Literal["sonnet", "opus", "haiku"]` model type | `str` with translation layer | Phase 1 (now) | Accepts both aliases and provider/model strings |
| Claude Code CLI flags for identity | Agent config markdown files | Phase 1-2 | Team context via files not flags |
| No provider configuration | Multi-provider config with `{env:}` credentials | Phase 1 (now) | Supports Moonshot, OpenRouter, Novita backends |
| No version check at startup | Minimum version validation (v1.1.52+) | Phase 1 (now) | Prevents cryptic failures from old versions |

**Deprecated/outdated:**
- `discover_claude_binary()`: Replaced by `discover_opencode_binary()` with version validation
- `Literal["sonnet", "opus", "haiku"]` model constraint: All aliases now map to `kimi-k2.5`
- `CLAUDECODE=1` and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` env vars: Removed entirely
- `--agent-id`, `--team-name`, `--parent-session-id` CLI flags: Do not exist in OpenCode

## Open Questions

1. **Exact `opencode --version` output format**
   - What we know: The `--version` / `-v` flag exists and "prints version number" per official CLI docs
   - What's unclear: Whether the output is `1.1.52`, `v1.1.52`, `opencode v1.1.52`, or multi-line
   - Recommendation: Use lenient regex `r"v?(\d+\.\d+\.\d+)"` and test with the actual binary during integration. Add a specific test that runs the real `opencode --version` on the dev machine.

2. **Exact minimum version for Kimi K2.5**
   - What we know: PR #10835 added moonshot-ai provider registration pre-v1.1.49. v1.1.52 has K2.5-specific fixes (image reading, thinking mode default)
   - What's unclear: Whether v1.1.49-v1.1.51 actually work for text-only K2.5 usage (our use case)
   - Recommendation: Set minimum to v1.1.52 to be safe. Log a warning but do not block for v1.1.49-v1.1.51. This can be relaxed later if testing shows earlier versions work fine.

3. **Whether Novita AI is now a built-in provider**
   - What we know: One source says "Novita AI is now integrated directly into OpenCode as a supported provider." Official provider docs do not list Novita.
   - What's unclear: Is Novita a first-class provider like `moonshot-ai`, or does it require custom `@ai-sdk/openai-compatible` config?
   - Recommendation: Treat Novita as a custom provider requiring explicit baseURL config until verified. Support it but default to `moonshot-ai` which is confirmed built-in.

4. **Whether `packaging` is reliably importable**
   - What we know: `packaging` comes with pip/setuptools and is available in virtually all Python environments
   - What's unclear: Edge cases with minimal Docker images or unusual installations
   - Recommendation: Use simple tuple comparison `(1, 1, 52)` instead of `packaging.version.Version`. Zero dependency risk, sufficient for our needs.

## Sources

### Primary (HIGH confidence)
- [OpenCode CLI docs](https://opencode.ai/docs/cli/) -- `--version` flag exists, `run` subcommand with `--model provider/model` format, `--agent` flag
- [OpenCode Config docs](https://opencode.ai/docs/config/) -- Provider configuration with `{env:VAR_NAME}` syntax, baseURL, model options
- [OpenCode Providers docs](https://opencode.ai/docs/providers/) -- moonshot-ai (international), moonshot-ai-china, openrouter as built-in providers; custom provider pattern with `@ai-sdk/openai-compatible`
- [OpenCode Changelog](https://opencode.ai/changelog) -- v1.1.52 introduced Kimi K2.5 fixes, v1.1.53 is latest as of 2026-02-07
- [Kimi K2.5 PR #10835](https://github.com/anomalyco/opencode/pull/10835) -- Moonshot AI provider registration with kimi-k2.5 model

### Secondary (MEDIUM confidence)
- [OpenRouter Kimi K2.5 listing](https://openrouter.ai/moonshotai/kimi-k2.5) -- Model ID `moonshotai/kimi-k2.5`, context 262144 tokens, pricing
- [Kimi K2.5 OpenCode setup gist](https://gist.github.com/OmerFarukOruc/26262e9c883b3c2310c507fdf12142f4) -- Custom `kimi-for-coding/k2p5` provider config with interleaved reasoning
- [WenHaoFree Kimi K2.5 guide](https://blog.wenhaofree.com/en/posts/articles/opencode-kimi-k25-free-guide/) -- Per-provider config examples for moonshot-ai, openrouter, moonshot-ai-china
- [Novita AI LLM API docs](https://novita.ai/docs/guides/llm-api) -- baseURL `https://api.novita.ai/openai`, OpenAI-compatible endpoint
- [GitHub releases](https://github.com/anomalyco/opencode/releases) -- Version history, release dates

### Tertiary (LOW confidence)
- Novita AI as built-in provider claim -- single source (blog post), not confirmed in official provider docs
- `opencode --version` exact output format -- inferred from CLI docs, not directly observed

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all stdlib Python, no new dependencies, adapting existing patterns
- Architecture: HIGH -- minimal changes to existing structure, clear separation of concerns
- Binary discovery: HIGH -- `shutil.which` is proven pattern from existing codebase
- Version validation: MEDIUM -- `--version` flag documented but exact output format unconfirmed
- Model translation: MEDIUM-HIGH -- provider model IDs confirmed across multiple sources, but exact per-provider behavior needs runtime validation
- Provider configuration: MEDIUM -- built-in providers confirmed, Novita custom path needs validation
- Pitfalls: HIGH -- well-documented from prior research and GitHub issues

**Research date:** 2026-02-07
**Valid until:** 2026-02-21 (14 days -- OpenCode releases frequently, model IDs may change)
