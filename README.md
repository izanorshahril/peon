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
├── src/report_harness/       # Legacy report-generation prototype; not the Peon core
├── tests/                    # Current prototype tests; core tests will follow the target seams
├── .scratch/report-generation-harness/
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
uv run mypy src/peon src/report_harness
```

The current `report-harness` command still belongs to the legacy prototype. The `peon` command now lives under `src/peon/app` and accepts a task plus an injected provider configuration; concrete provider adapters will follow in the AI layer.
