# Peon Project History and Source of Truth

Updated: 2026-07-22

## Purpose

Peon canonical product, architecture, current implementation, and handoff doc.

Release-specific records:

- `peon-0.3.0-history.md`: sole archive for 0.3.0 spec, tickets, commits,
  validation claims, verified outcome, and carry-forward decisions.
- `peon-0.3.1-spec.md`: active completion specification.
- `peon-0.3.1/issues/`: active dependency-ordered implementation tickets.

Update this file when package ownership, provider/tool contracts, user commands,
capabilities, or Pi parity plan change. Keep current truth separate from release
history. Verify claims against source and tests before status change. Do not
create extra scratch specs, tickets, command logs, or research notes outside the
release records listed above.

## Product Direction

Peon minimal modular Python coding agent. Priority:

1. Match Pi focused terminal coding-agent UX.
2. Use Tau small typed layers as Python implementation ref.
3. Use Minion for compact-context + local-model resilience.
4. Other agents optional ref, not reason to expand core.

Conversation primary UI: transcript top, composer bottom, minimal chrome. Prefer keyboard startup, commands, model switch, queued work, cancel, sessions, compact tool output. Keep interactive, print, JSON event, RPC, embedded modes distinct.

Peon avoid Excel/report gen, workbook schemas, image evidence, dashboards, office workflows, RAG, fine-tuning, autonomous self-improve, comm channels. Put these in external apps/extensions when needed.

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

- `agent` import no `app` or concrete integrations.
- Provider quirks stay in `ai`; agent loop never branch by vendor.
- App policy + file resource discovery stay in `app`.
- Domain side effects stay in `extensions` or external apps.
- Prefer public contracts + narrow typed seams, not frameworks.
- Use `agent`, not vague `core`, for portable runtime.

### Provider compatibility

- Send `User-Agent: peon` on outbound requests.
- Prefer native tool calls if endpoint support.
- Else append ai-bridge-compatible tool instructions after conversation via configurable `developer` or `system` role.
- Fallback response use compact JSON `tool_call`/`final` envelopes, normalize to provider-neutral `ToolCall`/`ModelResponse`.
- Keep wrapping replaceable; native fields, prompt bridges, structured modes coexist.

## Current Implementation

### Runtime and providers

- `AgentContext`, `AgentMessage`, `ToolCall`, `ModelResponse` portable.
- `run_task` execute provider turns, bounded tool dispatch, result append, continuation to final assistant output. Expose optional provider usage.
- `CodingSession` owns host-neutral prompt lifecycle around `run_task`. Runtime
  events carry immutable schema, timestamp, sequence, and correlation metadata;
  schema-v1/v2 serialization is shared. Typed tool lifecycle remains ticket 04.
- Metadata tracing disabled by default, enable via `--trace PATH`. Record provider, tool, resource, persist, hook, turn duration as JSONL (no chat content). Trace errors isolated from turn state.
- Optional event-journal sink and schema version 2 serializer use the shared
  runtime-event contract. Journal recovery and operational CLI policy remain
  ticket 09.
- `peon.embedded.EmbeddedSession` direct text Python adapter over
  `SessionController`. Exposes submit, typed callbacks, sync/async iterators
  with `.result` access to final `TurnFinishedEvent`, typed or dictionary event
  mode via `schema_version`, validated history loading (`load_history`),
  cancellation, and injected deps. `validate_history()` and
  `HistoryValidationError` are public. No Textual/prompt-toolkit load.
  Typed tool lifecycle events remain ticket 04.
- `ToolExecutionContext` support cancel + live tool callbacks.
- Adapters support OpenAI-compatible, GitHub Copilot, custom proxy profiles. Model discovery via `GET /models`.
- Provider profiles + UI settings persist in user-local JSON.
- OpenAI-compatible API keys optional for local endpoints.

### Modes and events

- Task arg: one non-interactive turn.
- No task or `--tui`: Textual minimal interactive mode.
- `-p`/`--print`: decoration-free final output; piped stdin support.
- `--events`/`--jsonl`/`--json`: schema-v1 JSONL by default; explicit
  `--schema-version 2` emits normalized typed runtime events.
- Print mode composes controller/session behavior. Undecorated output, session
  lifecycle, resources, persistence, and schema-v1 JSON events remain
  compatible. Schema-v2 selection uses shared serialization.
- Default non-interactive task path uses ephemeral controller/session behavior.
  CLI entry matches print, embedded, and Textual semantics where applicable.
- Built-in hosts resolve via stable `print`, `jsonl`, `textual`, and `embedded`.
  Prompt-toolkit implementation/dependency are removed; legacy explicit host
  selection retains unavailable guidance. Reserved `fullscreen`, `webapp` fail
  before startup.
- `fullscreen` + `webapp` modes reserved, reject honestly.

### Sessions

- Append-only JSONL store default `~/.peon/sessions`; override via `PEON_SESSION_DIR`.
- Interactive startup create fresh durable session default.
- `--continue` load newest valid session for cwd.
- `--session` accept ID, name, or JSONL path.
- `--session-name` name new session; `--no-session` ephemeral.
- `/new`, `/session`, `/resume`, `/fork [name]` preserve prior records + parent metadata. `/session` show active-session detail; `/resume` open cwd history. Session rows show first prompt, user interaction count, relative age. Empty sessions discard on exit/transition. `session-list-delimiter` switch dot to space. Durable exit print resume command for non-empty.
- Print mode ephemeral unless durable flags explicit.

### Tools and extensions

- In-process `ExtensionRegistry` own tool definitions/handlers, skill installers, named lifecycle hooks.
- Registered cwd-bound tools: `read`, `write`, `edit`, `bash`, `ls`, `find`, `grep`. Capability-profile helpers exist, but consistent task/print/JSONL/Textual composition and sample-tool exclusion remain 0.3.1 work.
- Filesystem tools enforce cwd contain, sensitive/excluded targets, symlink mutate deny, bounded read/search, output truncate.
- `edit` require exact unique match; `write` + `edit` reject unsafe mutate.
- `bash` has timeout, cancel, bounded output, live callbacks, and Windows
  process-tree termination. Unified typed tool/shell lifecycle remains 0.3.1
  work.
- `word_count` domain-neutral sample integration.

### Resources and effective system prompt

- `ResourceLoader` discover user/project skills, `AGENTS.md`/`CLAUDE.md`, `SYSTEM.md`, `APPEND_SYSTEM.md` with strict precedence.
- Explicit skill/context/system/append paths + inline prompt overrides work.
- Project trust + resource opt-out not disable explicit resources.
- Diagnostics distinguish missing, malformed, unreadable, duplicate, disabled resources.
- Startup resource display use Pi compact layout: context files first, then comma-separated skills. YAML folded skill descriptions + optional front-matter load without malformed diagnostics.
- Startup headings use Pi colors + space, insert as first selectable transcript block. System text normal default, optional `system-text-format` style. `Ctrl+C` clear composer. `!command` run `bash` send output to model. `!!command` keep output hidden from model.
- Effective prompt include compact skill metadata, not full body. `/skill:<name>` inject selected body once.
- Prompt assembly at provider boundary; loop avoid filesystem. Generated resource prompts excluded from persisted history.

### Textual interaction

- Single selectable transcript, fixed composer, Pi low-chrome layout. Right-click copy return focus to composer. Transcript selection high-contrast black-on-white.
- Assistant Markdown, separate thinking blocks, role-aware colors/padding, collapsed tool output, optional tool Markdown, restored-session blocks.
- Slash palette support ranked search, aliases, keyboard select, Tab complete, picker search, nested settings, Escape backtrack.
- `Ctrl+C` confirm exit, `Ctrl+D` exit, `Ctrl+T` toggle thinking, `Shift+Tab` cycle reasoning, `Ctrl+O` toggle tool output.
- Settings persist UI spacing/colors/style, system text style, provider maps, reasoning, thinking visibility, tool render/availability, shortcuts.
- `TextualEventRouter` handles current turn/message/delta/finish events. Prompt,
  informational command, session-transition, and shell paths use controller.
  Provider/model/settings/logout effects and legacy tool-output rendering remain
  host-local pending thin-host completion.
- Footer show cwd, provider/model, context count, reasoning. Token usage via host-neutral turn result + JSON event contract. Interactive footer show `n/a` until presentation ticket implement.
- Textual is sole maintained interactive TUI.

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

Provider-field commands hidden aliases via settings. Search candidate names improve discovery but no direct commands. Dynamic `/skill:<name>` entries visible in Textual.

## Completed History

Status below historical fact, not active backlog.

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

## Active 0.3.1 Completion

0.3.0 remained unreleased at `0.3.0a0`. Post-implementation review found only
the baseline, prompt dispatch, informational commands, and session transitions
fully matched their 0.3.0 tickets. Active completion work is defined only in
`peon-0.3.1-spec.md` and its 11 tickets:

- trustworthy root validation;
- complete ordered runtime events and shared schema serializers;
- validated embedded history and safe typed/dictionary iterators;
- unified tool and shell lifecycle events;
- complete provider/model/settings/logout controller flows;
- thin Textual ownership;
- consistent capability profiles, run limits, and stop reasons;
- streaming timeout, cancellation, retry, and backpressure;
- journal operational surface;
- package extras, textual-serve smoke, compatibility, and release gates.

Do not start unrelated Pi parity work until 0.3.1 ticket 11 closes.

### 0.3.1 Ticket 01: trustworthy validation baseline

Completed 2026-07-22:

- Pytest discovery is rooted at `tests/`; canonical `uv run pytest` no longer
  collects vendored mini-swe-agent tests.
- Collection baseline is 312 maintained tests. Full suite: 312 tests, 0
  failures, 0 errors, 2 strict expected failures, 25.366 seconds, exit 0. Expected
  failures characterize async iterator premature completion and missing typed
  tool lifecycle events.
- Existing schema version 1 CLI and version 1 legacy-session tests remain public
  compatibility checks.
- Package baseline is `0.3.0a0`, empty core dependencies, `tui` and `serve`
  extras each containing Textual only. `serve` still lacks textual-serve.
- Importing `peon.embedded` loads Peon agent contracts/runtime, application
  controller/session/resources, embedded adapter, and extension registry/tool
  modules. It loads no Textual or prompt-toolkit module.
- `uv run mypy src/peon` passes across 28 files; `uv build` creates the
  `0.3.0a0` sdist and wheel; `git diff --check` passes.
- No runtime behavior changed; only pytest discovery and characterization tests
  changed.

### 0.3.1 Ticket 02: runtime events and serializers

Completed 2026-07-22:

- Added immutable runtime event metadata: schema identity, stable event type,
  injected UTC timestamp, run sequence, and correlation IDs.
- Added typed command, selection, cancellation, and terminal-error event
  families; provider failure, cancellation, and persistence failure emit typed
  terminal facts before exactly one turn finish.
- Added shared schema-v1/v2 serializer with tolerant diagnostics and strict
  unknown-event rejection. Schema-v1 remains default CLI output; `--schema-version
  2` emits normalized typed events with terminal stop reasons.
- Streaming deltas and final assistant messages share message identity. Session
  transitions preserve event clock and sequence state.
- Evidence: focused 112 passed; full 320 tests with 0 failures, 0 errors, and 2
  strict expected failures; mypy clean across 28 files; build and diff check
  passed.

### 0.3.1 Ticket 03: embedded history and iterator interfaces

Completed 2026-07-22:

- `BoundedEventQueue` now validates `maxsize > 0`, uses a typed `_DONE`
  sentinel distinct from `None`, and correctly separates empty-poll timeout
  (returns `None`) from completion (returns sentinel). Delta events may be
  dropped silently under backpressure; all other canonical events block until
  space is available and are never lost.
- `validate_history()` public function validates a sequence of typed
  `AgentMessage` objects or raw dicts before any provider request or context
  mutation. Rejects unknown roles, missing/invalid content, malformed tool
  calls/results, and non-mapping inputs with actionable `HistoryValidationError`
  messages.
- `EmbeddedSession.load_history()` accepts typed or dict messages, validates via
  `validate_history()`, and injects them into the conversation context atomically
  (no mutation on failure). No terminal imports are loaded.
- `iter_events()` and `aiter_events()` both accept a `schema_version` parameter
  (1 or 2); when set, they yield serialized dicts via the shared serializer
  instead of typed events, from the same single execution.
- `SyncEventIterator` and `AsyncEventIterator` wrapper objects expose a `.result`
  property returning the final `TurnFinishedEvent` after iteration completes,
  without requiring a second run.
- Async iteration uses blocking `queue.get()` in a thread-pool executor instead
  of a 50 ms poll timeout. Completion is only signalled by the `_DONE` sentinel,
  so a slow provider can no longer terminate iteration prematurely.
- `CancelledError` from the async caller propagates `cancel()` to the active
  sub-session and joins the worker thread within 2 seconds.
- `validate_history` and `HistoryValidationError` added to `embedded.py`
  `__all__`; no Textual or prompt-toolkit import occurs.
- Evidence: 28 focused tests passed (7 queue/validation/history/dict-mode/
  result/cancellation groups); full 340 tests with 0 failures, 0 errors, 1
  strict expected failure (ticket 04 tool lifecycle); mypy clean across 28
  files; `git diff --check` clean.

### 0.3.1 Ticket 04: unify tool and shell lifecycle events

Completed 2026-07-22:

- Added `ToolStartedEvent`, `ToolOutputEvent`, and `ToolFinishedEvent` to the
  session event system in `coding_session.py`.
- Model-requested tool calls emit `ToolStartedEvent` before execution,
  `ToolOutputEvent` on live stream chunks, and `ToolFinishedEvent` on completion
  (reporting success, error, or cancellation with output/error facts).
- Direct shell commands dispatched via `SessionController.dispatch_shell()` emit
  identical tool lifecycle events with `source="shell"` without creating fake
  provider message history.
- Schema version 1 and 2 serializers support all new tool lifecycle events in
  `observability.py`.
- Legacy `on_tool_output` callback is preserved as a compatibility shim over
  `ToolOutputEvent`.
- `ToolStartedEvent`, `ToolOutputEvent`, `ToolFinishedEvent` exported in
  `peon.embedded.__all__`.
- Evidence: 345 total tests passing in full pytest suite (0 failures, 0 errors,
  0 xfailed); `uv run mypy src/peon` clean across 28 files; `git diff --check`
  clean.

### 0.3.1 Ticket 05: complete controller provider and settings flows

Completed 2026-07-22:

- Moved `ProviderConfig`, `SavedModel`, `saved_model_choices`, `select_saved_model`,
  `reasoning_effort_choices`, `cycle_reasoning_effort`, `ProviderSettingSpec`,
  `PROFILE_SETTING_SPECS`, `CONFIG_SETTING_SPECS` into `peon.app.config`.
- Removed all imports from `peon.app.cli` inside `SessionController`, ensuring strict host-neutral boundary separation.
- Fully implemented multi-step `/provider` setup, `/model` selection, `/settings` inspection/update, and `/logout` behind typed controller intents, outcomes (`ProviderSetupStepOutcome`, `ProviderSuccessOutcome`, `SettingsOptionsOutcome`, `SettingsUpdatedOutcome`, `LogoutOptionsOutcome`, `LogoutSuccessOutcome`), and single-use continuation tokens.
- Secret inputs (API keys, Copilot tokens) flag `is_secret=True` and are masked in all outcomes and logs.
- Added `tests/test_controller_provider_settings.py` headless unit test suite verifying all provider, model, settings, logout, and token single-use workflows.
- Evidence: 352 total tests passing in full pytest suite (0 failures, 0 errors); `uv run mypy src/peon` clean across 28 files; `git diff --check` clean.

### 0.3.1 Ticket 06: finish thin Textual and host ownership

Completed 2026-07-22:

- Marked `Host("prompt-toolkit", ...)` as `available=False` in `src/peon/app/hosts.py` while preserving actionable migration guidance.
- Updated `TextualEventRouter` to handle all 11 typed runtime events (`TurnStartedEvent`, `MessageEvent`, `StreamDeltaEvent`, `TurnFinishedEvent`, `CommandOutcomeEvent`, `SelectionRequestEvent`, `CancellationEvent`, `TerminalErrorEvent`, `ToolStartedEvent`, `ToolOutputEvent`, `ToolFinishedEvent`).
- Introduced thread-aware dispatching (`_call_host`) in `TextualEventRouter` to invoke host handlers on the main app thread when appropriate and `call_from_thread` when called from worker threads.
- Handled `CommandOutcomeEvent`, `SelectionRequestEvent`, `CancellationEvent`, `TerminalErrorEvent`, `ToolStartedEvent`, `ToolOutputEvent`, `ToolFinishedEvent` cleanly in `TextualPeonApp`.
- Updated `SetupStep` type annotations for `selection`, `settings`, and `logout`.
- Evidence: 352 total tests passing in full pytest suite (0 failures, 0 errors); `uv run mypy src/peon` clean across 28 files; `git diff --check` clean.

## Remaining Pi Gaps

Use as feature discovery, verify upstream before work:

- Context compaction + `/compact` workflow.
- Provider streaming via agent loop + live assistant render.
- Export/share/copy/status/theme/editor workflows.
- Undo/redo + navigable session tree beyond fork metadata.
- Extension discovery, package, reload, manage beyond in-process registry.
- Project init + richer skill/extension lifecycle.
- Fullscreen/webapp + RPC APIs reserved until concrete need.
- Decide if Pi navigation warrant `ls`, `find`, `grep` default enabled.
- Strong shell sandbox + security audit beyond cwd/process/output guards.
- Live external-provider compat, long-session perf, cross-platform validation.

Do not infer reqs from reserved names alone. Pi-first mean match useful behavior + UX, not copy all commands.

## Validation and Development

Canonical commands:

```powershell
uv sync
uv run pytest
uv run mypy src/peon
```

Run focused tests beside changed boundary before full suite. 2026-07-20 evidence: `uv run pytest --collect-only -q` collect 240 tests; `uv run pytest tests/test_textual_tui.py --collect-only -q` collect 44. 2026-07-21 UX validation pass `uv run pytest -q tests` (302 tests), `uv run mypy src/peon` pass clean.

### Durable renderer gotchas

- Rich `Style(bgcolor="default")` mean terminal default, not Textual widget background. Assistant + blank strips use `self.styles.background.rich_color`.
- Rich `Text` slice reset `Text.end` to `"\n"`. Reset to `""` after slice transcript lines. Embedded `\n`/`\r` move real terminal cursor even if widths + SVG look correct.
- Renderer tests inspect all visible segments (wrapper + trailing cells) at narrow width. User gray rows explicit; assistant rows use transcript background.

## Superseded Claims

Old scratch docs deleted (duplicate/contradict code). Permanent corrections unless code change:

- TUI, providers, sessions, tools, commands, resources implemented; not future "first phase".
- Startup create new session default; auto-resume require `--continue`.
- Default tools include mutate + bash tools, not just read-only.
- `/session`, `/reasoning`, `/skills` available in canonical catalog.
- `/models` alias of `/model`; candidate vocab not always alias.
- Ticket 20 research only, no runtime feature.
- Remote/tracker blockers from old notes gone.

### Ticket 01: print mode through `CodingSession`

- Route full print-mode turn via host-neutral session boundary. Preserve task/piped-input output, resource apply, tool execute, persist modes, cancel, structured outcomes.
- Keep provider, tool, store, event, clock, ID deps injectable. Agent loop independent of app hosts.
- Complete in `b4c4435`. Focused + full test suites pass.

### Ticket 02: JSON events from session lifecycle

- JSON mode serialize typed lifecycle events from `CodingSession`. Remove duplicate execution/resource/tool/persist orchestration; preserve event meaning/order.
- Add deterministic schema, session/run/turn/tool correlation. Started turn end with exactly one success, error, or cancel.
- Complete in `f7eda87`. Pass 44 focused tests, 260 full suite, 24 file mypy clean.

### Ticket 03: normalized provider usage

- Add immutable provider-neutral `Usage` metadata to `ModelResponse`.
- Adapters normalize prompt/completion tokens, cached prompt tokens, cost, currency. Preserve unavailable fields.
- `CodingSession.TurnResult` aggregate usage across tool continuations. Mixed-currency cost stay unavailable.
- JSON print events include usage on terminal turn records. Normal print mode response-only.
- Pass focused validation. Edge coverage include unsupported usage + mixed currencies.

### Ticket 04: metadata-only performance traces

- Add provider-neutral trace contracts + app-owned JSONL sink.
- Add opt-in tracing for provider requests, tools, resources, persist appends, hooks, full turns (success/error/cancel).
- Trace records include schema v1, UTC timestamp, monotonic duration, correlation IDs, safe names. Sink errors isolated.
- Add `--trace PATH` for print mode. Pass 275 tests + mypy clean.

### Ticket 05: embedded Python adapter

- Add `peon.embedded.EmbeddedSession` direct caller facade over `CodingSession`. Accept text prompts, forward injected deps, expose typed callbacks + structured `TurnResult`, delegate cancel. No terminal state exposed.
- Keep request shape text-only. Lazy-load `peon.app` exports to skip Textual/prompt-toolkit imports.
- Pass 5 embedded tests + 144 regression tests. Full pytest/mypy final gate.

### Ticket 06: Textual turns through CodingSession

- Route Textual prompts + model shell turns via `CodingSession`. Move prompt prep, execute, persist, lifecycle events, cancel out of widget orchestration.
- Preserve Textual transcript render, live tool output, shell-only execute, worker schedule, keyboard controls, session select, picker UI.
- Add session-owned live tool callback for bash presentation. Direct shell commands stay on dedicated execution context.
- Pass 52 focused tests. Full pass 281 tests + mypy clean.

### Ticket 07: prompt-toolkit turns through CodingSession

- Route prompt-toolkit fallback prompts + bang commands via `CodingSession`. Preserve small terminal UI + session controls.
- Move persist fail retry to `CodingSession`. Later turns retry failed appends in order without host logic leak.
- Remove fallback direct `run_task` + `_persist_new_messages`. Resource apply, tool execute, structured outcomes, persist use shared session.
- Harden retry: reject context/store mismatch, preserve combined fail, trace retries.
- Pass 37 + 12 focused tests. Full pass 286 tests + mypy clean.

### Ticket 08: centralized host selection

- Add immutable app host catalog with stable IDs, explicit roles, actionable unavailable errors.
- Route CLI print/event/interactive mode + `run_tui` startup via catalog. Textual + prompt-toolkit remain presentation hosts. Embedded direct Python entry.
- Reserved hosts reject before registry/session create. `--mode` + TUI runners compatible.
- Pass 88 focused tests. Full pass 295 tests + mypy clean.

### Ticket 09: contract verification and Peon 0.2

- Remove direct non-interactive CLI `run_task`. Default tasks use in-memory `CodingSession` without durable side effects.
- Publish 0.2.0. Record ownership, host roles, embedded usage, observability, Pi gaps.
- Preserve linear session format + convo files. No migration for 0.2.0.
- Pass 296 tests + mypy clean.

### Pi parity UX follow-up

- Split `/session` (active info) + `/resume` (saved picker). Session rows show first prompt, interaction count, relative age, config delimiters, right-align metadata. Empty sessions remove on exit.
- Move version, commands, context, skills from pinned widget to selectable transcript. Preserve colors/spacing. System text normal default.
- Right-click copy return focus to composer. Transcript selection high-contrast black-on-white (include blank rows).
- Minor flicker + highlight trace deferred.
### Ticket 11 compatibility validation and release 0.3.1 (2026-07-23)

- Executed full release gates:
  - `uv run pytest`: 368 passed in 35.07s.
  - `uv run mypy src/peon`: 0 issues found across 28 source files.
  - `cmd /c "git diff --check"`: 0 whitespace or formatting errors.
  - `uv build`: Successfully built `dist/peon-0.3.1.tar.gz` and `dist/peon-0.3.1-py3-none-any.whl`.
- Updated package version to final `0.3.1`.
- Verified 0.2 session compatibility, schema version 1 CLI default preservation, schema version 2 event journaling, and optional extras isolation (`tui`, `serve`).

### 0.3.0 host-neutral migration

All 0.3.0 ticket intent, implementation evidence, validation claims, review
findings, and carry-forward rules now live only in
`peon-0.3.0-history.md`. Do not reconstruct status from old commit messages or
completed checkboxes.

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
