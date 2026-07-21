# Peon Project History and Source of Truth

Updated: 2026-07-21

## Purpose

This is Peon's canonical product, architecture, implementation-history, and
handoff document. It replaces all earlier files under `.scratch`.

Update this file when a change alters package ownership, provider/tool
contracts, user-visible commands, current capabilities, or planned Pi parity.
Keep current truth separate from historical decisions. Verify implementation
claims against source and tests before changing status. Do not create another
scratch spec, ticket set, command inventory, or research note; add concise,
deduplicated findings here. The former host-neutral session ticket files were
consolidated into this document on 2026-07-21.

## Product Direction

Peon is a minimal modular Python coding agent. Product priority:

1. Match Pi's focused terminal coding-agent experience.
2. Use Tau's small typed layers as primary Python implementation reference.
3. Use Minion for compact-context and local-model resilience ideas.
4. Treat other agents as optional references, not reasons to expand core.

Conversation remains primary UI: transcript above, composer below, minimal
persistent chrome. Prefer keyboard-first startup, commands, model switching,
queued work, cancellation, sessions, and compact tool output. Keep interactive,
print, JSON event, RPC, and embedded use as distinct modes when adding them.

Peon does not own Excel/report generation, workbook schemas, image evidence,
dashboards, office workflows, RAG, fine-tuning, autonomous self-improvement, or
communication channels. Such capabilities belong in external applications or
extensions with concrete product need.

## Architecture Invariants

```text
src/peon/
  agent/       portable messages, loop, events, execution contracts
  ai/          provider auth, transport, serialization, normalization
  app/         CLI, TUI, config, sessions, resources, presentation policy
  extensions/  executable tools, skills, hooks, registration

app -> ai --------> agent
app -> extensions -> agent
```

- `agent` imports neither `app` nor concrete integrations.
- Provider quirks stay in `ai`; agent loop never branches by vendor.
- Application policy and filesystem resource discovery stay in `app`.
- Domain side effects stay in `extensions` or external applications.
- Prefer existing public contracts and narrow typed seams over frameworks.
- Use `agent`, not a vague top-level `core`, for portable runtime behavior.

### Provider compatibility

- Send `User-Agent: peon` on outbound provider requests.
- Prefer native provider tool calls when endpoint supports them.
- Otherwise append ai-bridge-compatible tool instructions after conversation,
  using configurable `developer` or `system` role.
- Fallback response uses compact JSON `tool_call`/`final` envelopes and is
  normalized into provider-neutral `ToolCall`/`ModelResponse` contracts.
- Keep wrapping replaceable; native fields, prompt bridges, and structured
  response modes may coexist.

## Current Implementation

### Runtime and providers

- `AgentContext`, `AgentMessage`, `ToolCall`, and `ModelResponse` are portable.
- `run_task` performs provider turns, bounded tool dispatch, result append, and
  continuation until final assistant output, while exposing optional provider
  usage observations without changing its return contract.
- `CodingSession` owns one host-neutral prompt lifecycle around `run_task`,
  including resource application, message persistence, typed start/message/
  finish events, structured outcomes, active tool cancellation, and normalized
  usage aggregation across provider continuations.
- Metadata-only tracing is disabled by default and can be enabled for print mode
  with `--trace PATH`; operation owners record provider, tool, resource,
  persistence, extension-hook, and turn durations as correlated JSONL without
  conversation content. Trace export failures are isolated from turn state.
- `peon.embedded.EmbeddedSession` is a direct text-only Python adapter over
  `CodingSession`; it exposes typed lifecycle events, structured turn results,
  cancellation, injected providers/tools/stores/clocks/IDs, and does not load
  Textual or prompt-toolkit. Application convenience exports are lazy so the
  neutral path remains frontend-free.
- `ToolExecutionContext` supports cancellation and live tool output callbacks.
- Adapters support OpenAI-compatible, GitHub Copilot, and configurable custom
  proxy profiles. Model discovery uses compatible `GET /models` endpoints.
- Provider profiles and UI settings persist in user-local JSON configuration.
- OpenAI-compatible API keys are optional for local endpoints.

### Modes and events

- Task argument: one non-interactive turn.
- No task or `--tui`: Textual minimal interactive mode.
- `-p`/`--print`: decoration-free final output; piped stdin supported.
- `--events`/`--jsonl`/`--json`: JSONL events for session start, user,
  thinking, tool call/result, assistant, turn end, error, and session end.
- Print mode now composes `CodingSession`; its undecorated output, session
  lifecycle, resource behavior, persistence, and JSON event translation remain
  compatible. JSON records use schema version 1 and carry session, run, and
  turn correlation where a turn exists; terminal turn records come from the
  typed session finish event and include normalized usage when available.
- The default non-interactive task path also uses an ephemeral
  `CodingSession`, keeping the direct CLI entry path aligned with print,
  embedded, Textual, and prompt-toolkit execution semantics.
- Built-in hosts resolve through stable `print`, `jsonl`, `textual`,
  `prompt-toolkit`, and `embedded` identifiers. Reserved `fullscreen` and
  `webapp` hosts fail before startup session work; CLI mode names remain
  compatible with the host identifiers.
- `fullscreen` and `webapp` modes are reserved and reject honestly.

### Sessions

- Append-only JSONL store defaults to `~/.peon/sessions`; override with
  `PEON_SESSION_DIR`.
- Interactive startup creates a fresh durable session by default.
- `--continue` loads newest valid session for current working directory.
- `--session` accepts ID, unique name, or explicit JSONL path.
- `--session-name` names a new session; `--no-session` is ephemeral.
- `/new`, `/session`, `/resume`, and `/fork [name]` preserve prior records and
  parent metadata. `/session` reports active-session details; `/resume` opens
  current-project history. Session rows show first prompt, user interaction
  count, and relative age; empty sessions are discarded on exit and new-session
  transitions. The `session-list-delimiter` setting switches dot delimiters to
  single spaces. Durable exit prints a resume command for non-empty sessions.
- Print mode is ephemeral unless durable session flags are explicit.

### Tools and extensions

- In-process `ExtensionRegistry` owns tool definitions/handlers, skill
  installers, and named lifecycle hooks.
- Registered cwd-bound tools: `read`, `write`, `edit`, `bash`, `ls`, `find`,
  `grep`. Only `read`, `write`, `edit`, and `bash` are enabled by default;
  enabled tool list is persistent UI configuration.
- Filesystem tools enforce cwd containment, sensitive/excluded targets,
  symlink mutation denial, bounded reads/searches, and output truncation.
- `edit` requires exact unique matches; `write` and `edit` reject unsafe
  mutation targets.
- `bash` has timeout, cancellation, bounded output, live callbacks, and
  Windows process-tree termination.
- `word_count` remains a domain-neutral sample integration.

### Resources and effective system prompt

- `ResourceLoader` discovers user/project skills, `AGENTS.md`/`CLAUDE.md`,
  `SYSTEM.md`, and `APPEND_SYSTEM.md` with deterministic precedence.
- Explicit skill/context/system/append paths and inline prompt overrides exist.
- Project trust and resource opt-outs do not disable explicit resources.
- Diagnostics distinguish missing, malformed, unreadable, duplicate, and
  intentionally disabled resources.
- Startup resource display follows Pi's compact layout: context filenames first,
  then comma-separated skill names; YAML folded skill descriptions and optional
  front-matter fields load without false malformed diagnostics.
- Startup headings use Pi-like section colors and spacing and are inserted as
  the first selectable transcript block, so later output pushes them upward;
  system text is normal by default with optional `system-text-format` styling.
  `Ctrl+C` clears the composer, while `!command` runs `bash` and sends output
  to the model and `!!command` keeps output out of model context.
- Effective prompt includes compact skill metadata, not every full body.
  `/skill:<name>` progressively injects a selected body once.
- Prompt assembly occurs at provider boundary; portable agent loop does not
  inspect filesystem. Generated resource prompts are excluded from persisted
  conversation history.

### Textual interaction

- Single selectable transcript, fixed composer, Pi-like low-chrome layout;
  right-click copy returns focus to the composer and transcript selection uses
  a high-contrast black-on-white highlight.
- Assistant Markdown, separate thinking blocks, role-aware colors/padding,
  collapsed tool output, optional tool Markdown, and restored-session blocks.
- Slash palette supports ranked search, aliases, keyboard selection, Tab
  completion, picker search, retained nested settings, and Escape backtracking.
- `Ctrl+C` confirms exit, `Ctrl+D` exits, `Ctrl+T` toggles thinking,
  `Shift+Tab` cycles reasoning, and `Ctrl+O` toggles tool output by default.
- Settings persist UI spacing/colors/text style, optional system text style,
  provider mappings, reasoning,
  thinking visibility, tool rendering/availability, and shortcuts.
- Footer shows cwd, provider/model, context count, and reasoning. Token usage is
  available through the host-neutral turn result and JSON event contract;
  interactive footer display remains `n/a` until a presentation ticket uses it.
- Prompt-toolkit shell remains a smaller fallback/test path; Textual owns full
  interaction parity.

### Commands

Available canonical commands:

```text
/help       available and reserved commands
/new        clean conversation (`/clear`, `/reset` aliases)
/model      switch model/provider (`/models` alias)
/provider   configure provider
/settings   UI, providers, general, shortcuts, tool availability
/reasoning  set/cycle effort
/tools      list tools
/skills     list skills
/logout     remove selected provider
/quit       exit (`/exit`, `/close`, `/q` aliases)
/session    show active session information
/resume     resume a saved current-project conversation
/fork       fork current conversation
```

Reserved with honest unavailable feedback: `/compact`, `/export`, `/share`,
`/copy`, `/status`, `/usage`, `/theme`, `/editor`, `/undo`, `/redo`, `/tree`,
`/extensions`, `/reload`, `/init`.

Provider-field commands remain hidden compatibility aliases managed through
settings. Search candidate names improve discovery but do not become direct
commands. Dynamic `/skill:<name>` entries are visible in Textual.

## Completed History

Status below is historical fact, not an active backlog.

### Foundation and command system

| ID | Outcome |
| --- | --- |
| 01 | Defined minimal task/context/provider/tool core boundary. |
| 02 | Kept workbook/evidence behavior in external report application. |
| 03 | Chose one normalized provider surface with adapter-owned quirks. |
| 04 | Chose Python 3.13 and `uv`; Go only if single binary dominates. |
| 05 | Stopped shared loop at orchestration; extension behavior stays external. |
| 06 | Added installable CLI, injected-provider task loop, fake-provider seam. |
| 07 | Added normalized OpenAI-compatible and Copilot adapters. |
| 08 | Added public tool/skill/hook registry contracts. |
| 09 | Added tool-call execution, context append, provider continuation. |
| 10 | Added extension guide pattern and runnable sample tool. |
| 11 | Added interactive TUI, shared multi-prompt context, provider setup. |
| 12 | Added model discovery, optional local API key, explicit mode levels. |
| 13 | Added persistent provider profiles and local config override. |
| 14 | Added Pi-style provider/model selection and selective logout. |
| 15 | Fixed transcript role backgrounds, spacing, and trailing render control. |
| 16 | Added shared command catalog, metadata, ranking, and typed resolution. |
| 17 | Added keyboard palette selection, completion, and picker navigation. |
| 18 | Reduced canonical command surface; retained hidden migration aliases. |
| 19 | Added explicit reserved-command contracts and unavailable feedback. |
| 20 | Reconciled Pi/Tau/OpenCode command research; no runtime change intended. |

### Session, tool, and resource parity

| Stream | Outcome |
| --- | --- |
| Session/tools 01 | Completed multi-tool turns and final assistant continuation. |
| Session/tools 02 | Persisted/restored conversations with JSONL records. |
| Session/tools 03 | Added safe cwd-bound paginated `read`. |
| Session/tools 04 | Added bounded `ls`, `find`, and `grep`. |
| Pi parity 01 | Made new/continue/exact/no-session lifecycle explicit. |
| Pi parity 02 | Added session selection, naming, resume, and fork metadata. |
| Pi parity 03 | Added print and JSONL event modes with stdin support. |
| Pi parity 04 | Added compact transcript, thinking/tool blocks, status toggles. |
| Pi parity 05 | Added guarded `write` and exact-match `edit`. |
| Pi parity 06 | Added cancellable bounded `bash`. |
| Pi parity 07 | Added resource discovery and effective system prompt assembly. |
| Pi parity 08 | Matched compact startup resource display and skill front-matter parsing. |
| Pi parity 09 | Added colored startup sections, Ctrl+C clearing, and bang shell commands. |

### Commit chronology

```text
c5d2c1f  initial report-generation harness (later removed from core direction)
3706085  reset toward minimal build
84aecc3  minimal agent loop
a80d00a  normalized provider adapters
25bdf50  extension registry
f2bc4b8  tool-call continuation
3baec78  integration sample
69ac5a4  interactive provider TUI
934842b  persistent provider profiles
d59662d  slash command catalog
ccab297  command UX and housekeeping
030ce9f  complete agent turns and sessions
52a968c  explicit session lifecycle
70072ba  tool-call output fixes
a9571bc  print and event modes
436813c  early session resume fix
0cc7a21  thinking visibility status
9eb8146  safe file mutations
4f5e920  cancellable bash
49fd17e  local resources/effective system prompt
d4806a0  thinking-toggle and inactive-logout regressions
```

## Remaining Pi Gaps

Use this as next-session feature discovery, then verify upstream behavior before
creating work:

- Context compaction and `/compact` workflow.
- Provider streaming through agent loop and live assistant rendering.
- Export/share/copy/status/theme/editor workflows.
- Undo/redo and navigable session tree beyond fork metadata.
- Extension discovery, packaging, reload, and management beyond in-process
  registry and local skill metadata.
- Project initialization and richer skill/extension lifecycle.
- Fullscreen/webapp and RPC APIs remain reserved until concrete need exists.
- Decide whether Pi-like navigation warrants enabling `ls`, `find`, and `grep`
  by default; they are registered but currently opt-in.
- Stronger shell sandboxing and security audit beyond current cwd/process/output
  guards.
- Live external-provider compatibility, long-session performance, and broad
  cross-platform behavior require real-environment validation.

Do not infer requirements from reserved names alone. Pi-first means matching
useful behavior and interaction quality, not copying every command.

## Validation and Development

Canonical commands:

```powershell
uv sync
uv run pytest
uv run mypy src/peon
```

Run focused tests beside each changed boundary before full suite. Dated
2026-07-20 evidence, not a permanent expected count: `uv run pytest
--collect-only -q` collected 240 tests; `uv run pytest
tests/test_textual_tui.py --collect-only -q` collected 44. Later UX validation
on 2026-07-21 passed `uv run pytest -q tests` with 302 tests and
`uv run mypy src/peon` with no issues.

### Durable renderer gotchas

- Rich `Style(bgcolor="default")` means terminal default, not inherited
  Textual widget background. Assistant and blank strips must use
  `self.styles.background.rich_color`.
- Rich `Text` slicing resets `Text.end` to `"\n"`. Reset it to `""` after
  slicing transcript lines; embedded `\n`/`\r` can move a real terminal cursor
  even when strip widths, background assertions, and SVG output look correct.
- Renderer tests must inspect every visible segment, including wrapper and
  trailing cells, at narrow width. Keep user gray rows explicit while assistant
  rows use transcript background.

## Superseded Claims

Earlier scratch docs are deleted because they duplicated or contradicted code.
These corrections are permanent unless implementation changes:

- TUI, providers, sessions, tools, commands, and resources are implemented;
  they are not a future "first phase".
- Startup creates a new session by default; auto-resume requires `--continue`.
- Default tools include mutation and bash tools, not only read-only tools.
- `/session`, `/reasoning`, and `/skills` are available in canonical catalog.
- `/models` is an alias of `/model`; candidate vocabulary is not always alias.
- Ticket 20 was research only and proves no runtime feature by itself.
- Remote/tracker blockers from old planning notes no longer apply.

### Ticket 01: print mode through `CodingSession`

- Routed a complete print-mode turn through the host-neutral session boundary,
  preserving task and piped-input output, resource application, tool execution,
  persistence modes, cancellation, and structured outcomes.
- Kept provider, tool, store, event, clock, and ID dependencies injectable;
  the provider-neutral agent loop remains independent of application hosts.
- Completed in `b4c4435`. Focused session/print compatibility tests and the
  subsequent full suite passed.

### Ticket 02: JSON events from session lifecycle

- Made JSON mode serialize the typed lifecycle events emitted by
  `CodingSession`, removing duplicate execution, resource, tool, and
  persistence orchestration while preserving event meaning and ordering.
- Added deterministic schema, session, run, turn, and tool-call correlation;
  every started turn ends with exactly one success, error, or cancellation
  outcome.
- Completed in `f7eda87` (`feat(cli): serialize events from session lifecycle`).
  Focused validation passed with `44` tests, the full suite passed with `260`
  tests, and mypy reported no issues in `24` source files.

### Ticket 03: normalized provider usage

- Added immutable provider-neutral `Usage` metadata to `ModelResponse`.
- OpenAI-compatible and custom adapters normalize prompt/completion tokens,
  cached prompt tokens, cost, and currency while preserving unavailable fields.
- `CodingSession.TurnResult` aggregates usage across tool continuations and
  leaves mixed-currency costs unavailable rather than adding incompatible units.
- JSON print events include usage on terminal turn records; ordinary print mode
  remains response-only.
- Focused validation: provider, agent, session, and CLI suites passed; edge
  coverage includes unsupported usage payloads and mixed currencies.

### Ticket 04: metadata-only performance traces

- Added provider-neutral trace contracts and an application-owned JSONL sink.
- Added opt-in tracing for provider requests, tool calls, resource loading,
  persistence appends, lifecycle hooks, and complete turns, with success,
  error, and cancellation outcomes.
- Trace records include schema version, UTC timestamp, monotonic duration,
  correlation IDs, and safe provider/model/tool/hook names only. Sink failures
  are logged and isolated from conversation and persistence behavior.
- Added `--trace PATH` for print mode while preserving ordinary print and JSON
  event output. Validation passed: `275` tests and `mypy src/peon` with no
  issues.

### Ticket 05: embedded Python adapter

- Added `peon.embedded.EmbeddedSession` as a direct caller-facing facade over
  `CodingSession`. It accepts text prompts, forwards injected provider,
  executor, resources, session store, clock, and turn ID factory dependencies,
  exposes typed event callbacks and structured `TurnResult` values, and
  delegates cancellation without exposing terminal state.
- Kept the request shape text-only. Moved `peon.app` convenience exports to
  lazy resolution so importing the embedded adapter does not import Textual or
  prompt-toolkit; existing CLI and TUI imports remain compatible.
- Focused validation passed: `5` embedded tests and `144` embedded/session/agent
  and host regression tests. Full pytest and mypy remain the final gate for
  this ticket.

### Ticket 06: Textual turns through CodingSession

- Routed normal Textual prompts and model-following shell turns through
  `CodingSession`, moving prompt preparation, execution, persistence,
  lifecycle events, and cancellation out of the widget orchestration path.
- Preserved Textual-owned transcript rendering, live tool output, shell-only
  execution, worker scheduling, keyboard controls, resource/session behavior,
  and existing picker and dialog interactions.
- Added the session-owned live tool-output callback required for the existing
  bash presentation, while keeping direct shell commands on their dedicated
  execution context.
- Focused Textual/resource/bash/session validation passed: `52` tests. Full
  validation passed: `281` tests and `mypy src/peon` with no issues.

### Ticket 07: prompt-toolkit turns through CodingSession

- Routed the prompt-toolkit fallback's normal prompts and model-following bang
  commands through `CodingSession`, preserving its smaller terminal
  presentation and command/session controls.
- Moved persistence failure retry into `CodingSession`, so failed appends are
  retried in order by later turns without reintroducing host-specific
  persistence or leaking unsaved messages into event streams.
- Removed the fallback's direct `run_task` and `_persist_new_messages` paths;
  resource application, tool execution, structured outcomes, and persistence
  now use the shared session boundary.
- Hardened retry behavior rejects context/store mismatches, preserves combined
  provider and persistence failures, keeps unsaved messages out of event
  streams, and traces retry appends like ordinary persistence.
- Focused fallback/session validation passed: `37` and `12` tests. Full
  validation passed: `286` tests and `mypy src/peon` with no issues.

### Ticket 08: centralized host selection

- Added a small immutable app-owned host catalog with stable identifiers,
  explicit roles, and actionable unavailable-host errors for unknown and
  reserved hosts.
- Routed CLI print/event/interactive mode composition and `run_tui` startup
  through the catalog. Textual and prompt-toolkit remain presentation hosts;
  embedded remains a direct Python entry path, with no frontend dependency in
  `CodingSession`.
- Reserved hosts are rejected before registry or session creation, while
  existing `--mode` behavior and injected TUI runners remain compatible.
- Focused host/CLI/fallback validation passed: `88` tests. Full validation
  passed: `295` tests and `mypy src/peon` with no issues.

### Ticket 09: contract verification and Peon 0.2

- Removed the remaining direct non-interactive CLI `run_task` orchestration;
  default tasks now use an in-memory `CodingSession` without durable session
  side effects or an implicit tool executor.
- Published the 0.2.0 version in package metadata and both interactive host
  banners. Current ownership, host roles, embedded usage, observability, and
  remaining Pi gaps are recorded here as project truth.
- Preserved the linear session format and existing conversation files; no
  migration is required for the 0.2.0 release.
- Final validation passed: `296` tests and `mypy src/peon` with no issues.

### Pi parity UX follow-up

- Split `/session` into active-session information and `/resume` into the
  saved-session picker. Session rows now show the first prompt, interaction
  count, relative age, configurable delimiters, and right-aligned metadata;
  empty sessions are removed on exit and new-session transitions.
- Moved version, commands, context, and skills from a pinned startup widget
  into the selectable transcript. Startup Rich colors and spacing are
  preserved, while system text is normal by default with optional formatting.
- Right-click copy and mouse-up after selection return focus to the composer.
  Transcript selection is rendered as a full-row black-on-white highlight,
  including blank selected rows, after role and padding styles are composed.
- Remaining minor flicker and highlight-tracing behavior is known and
  non-blocking; it is intentionally deferred for a later session.
- Latest validation: focused Textual interaction tests passed (`5` tests), the
  Textual/resource/bash suite passed (`53` tests), the full suite passed
  (`302` tests), mypy passed for `28` source files, and `git diff --check`
  reported no findings.

## Primary Upstream Sources

### Pi

- Project: https://github.com/earendil-works/pi/tree/main/packages/coding-agent
- Usage: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md
- Sessions: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sessions.md
- Session format: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md
- Session manager: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts
- Print mode: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/modes/print-mode.ts
- Interactive mode: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/modes/interactive/interactive-mode.ts
- Slash manifest: https://github.com/earendil-works/pi/blob/3da591ab74ab9ab407e72ed882600b2c851fae21/packages/coding-agent/src/core/slash-commands.ts
- Autocomplete: https://github.com/earendil-works/pi/blob/3da591ab74ab9ab407e72ed882600b2c851fae21/packages/tui/src/autocomplete.ts
- Resource loader: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/resource-loader.ts
- System prompt: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/system-prompt.ts
- Skills: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/skills.ts
- Read tool: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/read.ts

### Tau

- Project: https://github.com/huggingface/tau
- Agent loop: https://github.com/huggingface/tau/blob/main/src/tau_agent/loop.py
- Harness: https://github.com/huggingface/tau/blob/main/src/tau_agent/harness.py
- Session wrapper: https://github.com/huggingface/tau/blob/main/src/tau_coding/session.py
- Coding tools: https://github.com/huggingface/tau/blob/main/src/tau_coding/tools.py
- Commands: https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/src/tau_coding/commands.py
- Autocomplete: https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/src/tau_coding/tui/autocomplete.py
- Textual app: https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/src/tau_coding/tui/app.py

### Secondary references

- Minion: https://github.com/Sentdex/minion
- OpenCode: https://github.com/anomalyco/opencode
- Hermes Agent: https://github.com/NousResearch/hermes-agent
- OpenClaw: https://github.com/openclaw/openclaw
- Odysseus: https://github.com/odysseus-dev/odysseus
- Goose: https://github.com/aaif-goose/goose
- Zed: https://github.com/zed-industries/zed
