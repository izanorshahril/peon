# Peon

Peon is a minimal, modular Python agent core.

Its center is deliberately small: accept a task, keep compact context, call a model, execute registered tools when requested, and return the final response. The design follows Tau and Minion's minimal-loop bias and borrows Pi's extension-oriented architecture.

The target package shape follows Tau's names while keeping Peon's surface smaller:

```text
src/peon/
├── ai/          provider and model adapters
├── agent/       portable runtime, messages, tools, events, and harness
├── app/         shell, CLI, TUI, configuration, and presentation policy
└── extensions/  extension API, registry, discovery, and loading
```

## Direction

Peon owns:

- The agent loop and compact context.
- A normalized provider surface.
- Tool registration and tool-call dispatch.
- A small extension boundary for tools, skills, and later integrations.

Peon does not own Excel report generation, workbook schemas, image evidence handling, dashboards, UI, autonomous coding, or self-improvement. Those capabilities belong in separate applications or extensions.

The existing report-building application is the intended future source for Excel tooling. Its read/write component can later be wrapped as a Peon tool, skill, or extension. Peon should not duplicate that application inside the core.

## Workflow

```text
task
  -> compact context
  -> provider turn
  -> final response
       or
     tool call -> registered extension -> tool result -> provider continuation
```

Provider-specific authentication and transport stay behind adapters. The loop should not branch on whether the provider is OpenAI-compatible or GitHub Copilot.

The dependency direction is:

```text
app -> extensions -> agent
app -> ai --------> agent
```

`agent` stays portable and imports neither `app` nor `extensions`. `ai` contains concrete provider adapters and implements the provider interface consumed by `agent`; `extensions` composes agent tools and hooks without putting domain behavior into the runtime. Keep `core` as a conceptual term, not a top-level package name: `agent` says what the module does and matches Tau's `tau_agent` and Pi's `agent` packages.

Extensions currently use an in-process registry:

```python
from peon.extensions import ExtensionRegistry

registry = ExtensionRegistry()
registry.register_tool(
  name="lookup",
  description="Look up a value.",
  parameters={"type": "object"},
  handler=lambda arguments: "value",
)
```

Skills can register related tools through `register_skill`, and integrations can subscribe to named lifecycle events with `on`. Discovery, packaging, and persistence are deliberately deferred; an external application owns how it constructs and supplies the registry.

### External integration

An application wraps its own capability by registering a provider-neutral handler
on an application-owned registry, then passes that registry to the agent loop:

```python
from peon.agent import run_task
from peon.ai import OpenAICompatibleProvider
from peon.extensions import ExtensionRegistry

registry = ExtensionRegistry()
registry.register_tool(
  name="lookup_customer",
  description="Look up a customer in the application's data store.",
  parameters={
    "type": "object",
    "required": ["customer_id"],
    "properties": {"customer_id": {"type": "string"}},
  },
  handler=lookup_customer,
)

response = run_task(
  "Summarize customer C-42.",
  provider,
  executor=registry,
)
```

The handler and its dependencies stay in the external application. A group of
related handlers can be packaged as a skill with `register_skill`; a single
capability can be registered directly as a tool. The registry supplies tool
definitions to the provider and executes requested calls during continuation.

The existing report-building application's Excel reader/writer is a future
integration candidate. A separate application can wrap that capability as a
tool or skill using the same contract, but Peon's core must not import the
report application, workbook schemas, image-processing code, or its dependencies.

For a runnable, domain-neutral example, register the built-in sample tool:

```python
from peon.extensions import ExtensionRegistry, register_sample_tools

registry = ExtensionRegistry()
register_sample_tools(registry)
```

## Project Structure

```text
peon/
├── src/peon/                 # Target minimal agent package
│   ├── ai/                   # Provider/model adapters
│   ├── agent/                # Portable runtime and harness
│   ├── app/                  # CLI/TUI/application shell
│   └── extensions/           # Extension API and loading
├── tests/                    # Current prototype tests; core tests will follow the target seams
├── .scratch/peon-spec/
│   ├── map.md                # Current direction and resolved decisions
│   ├── spec.md               # Buildable Peon specification
│   └── issues/               # Dependency-ordered implementation tickets
├── reference.txt             # Reference projects and inspiration
├── pyproject.toml            # Python and uv project metadata
└── uv.lock                   # Locked dependency resolution
```

The next implementation phase should fill `src/peon/agent` first, then add `ai`, `extensions`, and `app` around it. The existing report prototype should be moved behind an extension boundary later rather than extended as Peon's runtime.

## Development

```powershell
uv sync
uv run pytest
uv run mypy src/peon
```

The `peon` command lives under `src/peon/app` and accepts a task plus an injected provider configuration.

## Interaction levels

Peon exposes four interaction levels through `--mode`:

| Level | Mode | Availability | Behavior |
| --- | --- | --- | --- |
| 1 | `non-interactive` | Available | Run one task for scripts and automation. |
| 2 | `minimal` | Available | Run a small interactive terminal session. |
| 3 | `fullscreen` | Reserved | Not implemented yet. |
| 4 | `webapp` | Reserved | Not implemented yet. |

The default is level 1 when a task is supplied and level 2 when no task is
supplied. `--tui` remains an alias for `--mode minimal`. Levels 3 and 4
currently report that the requested mode is unavailable.

## Minimal interactive mode

Run `peon` without a task, or pass `--tui`, to configure a provider inside an
interactive terminal session:

```powershell
uv run peon
```

The session presents providers as a numbered selection. It then discovers
OpenAI-compatible models through `GET /models`; one detected model is selected
automatically, while multiple models are shown as a numbered list and require
one default selection. The complete detected model list is saved for later
switching. API keys and tokens are requested without echoing them.
OpenAI-compatible API keys are optional, so local unauthenticated endpoints are
supported. Multiple prompts share one compact in-memory conversation context,
and the application-owned sample tool is available to the agent.

After a provider is configured successfully, Peon saves the provider, endpoint,
model, and credential in a user-local JSON profile and reuses it on the next
run. Use `/provider` to configure a replacement; the new profile is saved after
successful setup. Set `PEON_CONFIG_FILE` to choose a different profile path.
Treat this file as sensitive because it can contain an API key or Copilot token.

Level 2 uses a minimal Textual terminal renderer shaped like the vanilla
Pi-agent interaction. Startup guidance is plain text, the conversation is the
main scrollable surface, and the composer stays at the bottom without a
fullscreen header or footer chrome. Conversation text is selectable for
copying with either the normal selection shortcut or right-click. Selection is
line-based and can span multiple requests and responses. New output is
anchored immediately above the composer and the transcript scrolls upward as
it grows. User messages use a gray block background without a left symbol or
italic styling; thinking and system text is muted and italic, while assistant
responses have no additional prefix and are rendered as Markdown. The header
title is light blue. While a request is running, an animated spinner shows
`Work...work!`; the status text is configurable. User blocks support
configurable blank lines above and below user requests and assistant responses
plus configurable visual left padding for user and assistant text; the
defaults match Pi-like spacing. Assistant spacer bars use the current black
theme background.
The TUI flags `--user-top-blank-lines`, `--user-bottom-blank-lines`, and
`--message-left-padding` adjust those values. `/settings` also persists message
spacing, left padding, application and chat backgrounds, user and assistant
colors, and normal/bold/italic text formatting. Font family and font size remain
terminal-emulator settings because Textual cannot control them reliably. If focus is anywhere outside the composer, typing automatically
returns focus to it and preserves the first character typed. Successful
session commands such as `/new` leave a light-blue checkmark confirmation
in the transcript. Slash-command suggestions appear above the composer as
soon as a command prefix is typed; the first matching command is highlighted
as the candidate that will run. Press `Esc` while a provider, model, or logout
picker is open to cancel the selection and return to the composer.

`Ctrl+C` asks for confirmation before exiting, so an accidental keypress does
not interrupt an active chat or discard a draft prompt. `Ctrl+D` and `/quit`
remain direct exit commands. Switching models updates the compact status line
without adding provider or model trace text to the conversation.

Peon can retain more than one provider profile. Startup reuses the last active
profile without prompting. `/provider` adds a profile, `/model` lists and
switches models from every saved profile, and compatibility `/models` remains
hidden from suggestions. The model command can change model and provider
without clearing conversation context. `/logout` removes only the selected
provider. If the active provider is removed, Peon switches to another saved
profile or starts provider setup when none remain.

`/settings` opens a retained hierarchy: `UI`, `Saved provider`, or `Add
provider`. Saved providers are grouped by adapter type and profile name. An
OpenAI-compatible profile exposes its name and config; a custom profile also
exposes request- and response-field mappings. Request rows use canonical
OpenAI names such as `reasoning_effort` and `max_completion_tokens` on the left
and the configured corporate field name on the right. In Textual, Left/Right
changes reasoning, booleans, token counts, temperature, spacing, and text
format in place; Enter cycles choices or toggles booleans. Values that require
typing return to the same list after they are saved.

The footer currently shows the working directory, provider, model, context
message count, and `n/a` for effort and token usage. The provider-neutral
`ModelResponse` contract does not expose usage metadata yet. Session context is
discarded when Peon exits. A filesystem/read tool and persistent session
history are not included yet.

Interactive commands:

```text
/help      show available and reserved commands
/new       start a clean conversation
/model     list and switch model and provider
/provider  configure another provider profile
/settings  configure UI and saved provider profiles
/tools     list registered tools
/logout    remove one saved provider
/quit      exit Peon

Provider-field commands remain available as hidden compatibility aliases and
are managed through `/settings`. Reserved future commands appear in `/help`
with honest unavailable feedback.
```

One-shot requests remain available for scripts and automation:

```powershell
uv run peon "Summarize the repository." `
  --provider openai-compatible `
  --base-url "https://api.openai.com/v1" `
  --api-key $env:OPENAI_API_KEY `
  --model "gpt-4o-mini"
```

For a local OpenAI-compatible endpoint, omit `--api-key`:

```powershell
uv run peon "Summarize the repository." `
  --provider openai-compatible `
  --base-url "http://localhost:11434/v1" `
  --model "local-model"
```
