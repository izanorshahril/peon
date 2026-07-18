# Peon: Minimal Extensible Agent Core

> **Status: completed foundational spec.** Issues 01–15 record delivered core,
> provider, extension, persistence, and TUI work. Current work is defined by
> [Peon Slash Command System](slash-command-spec.md) and
> [Slash Command Inventory](command-inventory.md). Do not use this completed
> spec to create new implementation tasks.

## Problem Statement

Peon needs to be a minimal agent core, not another report-building application. The current direction accidentally made Excel reading, image evidence, justification, and workbook writeback the product boundary even though those capabilities already belong to another application and should be reusable as an external integration.

Peon should instead capture the small, reusable center of Tau and Minion: receive a task, maintain compact context, call a model, execute requested tools, and return a result. It should borrow Pi's modular architecture so tools, skills, providers, and later extensions can be added without rewriting the loop.

## Solution

Build Peon as a small Python package with four responsibilities:

- An agent loop that coordinates task input, context, model turns, and tool calls.
- A normalized provider interface with provider-specific authentication and transport hidden behind adapters.
- A compact context representation that can append model and tool messages without owning a domain workflow.
- A tool/extension registry that lets external capabilities register schemas, handlers, skills, and optional lifecycle hooks.

The core must not know about Excel, image evidence, report schemas, dashboards, coding workspaces, or UI surfaces. The existing report-building application can later expose its Excel component through a Peon extension. That integration should be a consumer of the extension contract, not a reason to widen the core.

The target package layout is:

```text
src/peon/
├── ai/          provider and model adapters
├── agent/       portable runtime, messages, tools, events, and harness
├── app/         shell, CLI, TUI, configuration, and presentation policy
└── extensions/  extension API, registry, discovery, and loading
```

The dependency direction is `app -> extensions -> agent` and `app -> ai -> agent`. The `agent` package must remain independent of application policy, UI, extension discovery, and concrete provider transports. `agent` is preferred over `core` as the package name because it describes the reusable module and aligns with Tau's `tau_agent` and Pi's `agent` layers.

## User Stories

1. As an operator, I want to submit a task to a small agent loop, so that Peon can complete a model-backed task without a domain-specific application around it.
2. As an operator, I want to choose an OpenAI-compatible endpoint or GitHub Copilot login without changing the loop, so that provider details do not leak into task execution.
3. As an operator, I want the agent to return a final model response, so that a simple task works without tools or extensions.
4. As an extension author, I want to register a tool with a name, description, input schema, and handler, so that the model can request domain capabilities.
5. As an extension author, I want to package related tools and skills together, so that an external application can add a capability without modifying the core.
6. As an operator, I want tool calls to execute and feed their results back into the next model turn, so that the agent can complete multi-step tasks.
7. As a maintainer, I want context to remain compact and explicit, so that the loop stays understandable and does not accumulate framework behavior prematurely.
8. As a maintainer, I want provider and tool failures to become clear agent errors, so that failures are observable rather than silently swallowed.
9. As a maintainer, I want public-seam tests for the loop, provider, and extension registry, so that implementation details can change safely.
10. As an integration author, I want the existing report-building application's Excel component to be usable as a later tool or extension, so that Peon does not duplicate that application.
11. As a maintainer, I want Python and `uv` to remain the first implementation stack, so that the core stays portable and user-space friendly.
12. As a maintainer, I want UI, dashboards, autonomous coding, and self-improvement to remain outside the first core, so that Peon stays minimal.

## Implementation Decisions

- Use one small agent loop as the stable core: task input, context, provider turn, tool dispatch, and final response.
- Use one normalized provider shape by default; keep OpenAI-compatible base URLs and GitHub Copilot login behind adapters unless compatibility makes a second surface necessary.
- Keep tools and skills behind an explicit extension boundary with a small registry. Extensions own domain schemas, side effects, and integration-specific errors.
- Keep context as an explicit message collection with only the operations needed by the loop. Defer sophisticated memory, persistence, and compaction policies until real usage requires them.
- Build the first cut in Python and manage it with `uv`.
- Treat the existing report-building application as the future owner of Excel read/write behavior. Peon may later call it through an extension, but it must not duplicate or absorb that workflow.
- Follow Pi's composable extension direction without importing Pi's full surface area; follow Tau and Minion's minimal loop and compact context bias.
- Use `ai`, `agent`, `app`, and `extensions` as the first package names. Keep TUI code inside `app` until it earns a separate package through real size or reuse.

## Testing Decisions

- Test the agent loop through a public seam with a fake provider: a task should produce a final response without requiring a real model.
- Test the normalized provider surface with transport fakes, including provider-specific configuration and response failures.
- Test the extension registry through a public tool registration and invocation path, not private handler lookup.
- Test one multi-turn tool-call flow: model requests a registered tool, the tool result is appended to context, and the model receives a continuation turn.
- Test clear failures for unknown tools, invalid tool input, provider failures, and exhausted tool-call limits.
- Keep tests independent of private module structure, exact adapter arrangement, and domain-specific integrations.
- Add Excel integration tests only in the external report-building application or its extension package; they do not belong in Peon's core suite.

## Out of Scope

- Excel report generation, workbook schemas, image evidence, and justification writeback in the core.
- Dashboard analytics and visualization.
- Animated visuals and interactive presentation layers.
- TUI and web app surfaces for the first cut.
- Self-improvement loops, fine-tuning, autonomous code editing, and multi-agent infrastructure.
- General RAG, long-term memory, background daemons, and broad reader frameworks.
- A second provider surface unless a provider cannot map cleanly onto the normalized shape.
- A framework-heavy extension marketplace or plugin distribution system.

## Further Notes

- The resolved decision set now points to a small agent kernel, normalized provider adapters, compact context, and an extension registry.
- The first useful workflow is task -> model -> optional tool call -> model continuation -> final response.
- The Excel report-building application remains a separate product. Its read/write component is a candidate extension, not a reason to define Peon's core around spreadsheets.
- The earlier report-generation prototype was removed from Peon. Future Excel tooling should be rehomed behind the extension boundary.
