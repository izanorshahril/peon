# Peon Project History and Source of Truth

Updated: 2026-07-21

## Purpose

Peon canonical product, architecture, implementation-history, handoff doc. Replace old files in `.scratch`.

Update file when package ownership, provider/tool contracts, user commands, capabilities, or Pi parity plan change. Keep truth separate from history. Verify claims against source + tests before status change. Do not create new scratch specs, tickets, command logs, research notes; add short findings here. Consolidated host-neutral session tickets here 2026-07-21.

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
- `CodingSession` own host-neutral prompt lifecycle around `run_task`. Include resource apply, message persist, typed start/message/finish events, structured outcomes, tool cancel, normalized usage aggregation.
- Metadata tracing disabled by default, enable via `--trace PATH`. Record provider, tool, resource, persist, hook, turn duration as JSONL (no chat content). Trace errors isolated from turn state.
- `peon.embedded.EmbeddedSession` direct text Python adapter over `CodingSession`. Expose typed events, structured turn results, cancel, injected deps. No Textual/prompt-toolkit load. App exports lazy.
- `ToolExecutionContext` support cancel + live tool callbacks.
- Adapters support OpenAI-compatible, GitHub Copilot, custom proxy profiles. Model discovery via `GET /models`.
- Provider profiles + UI settings persist in user-local JSON.
- OpenAI-compatible API keys optional for local endpoints.

### Modes and events

- Task arg: one non-interactive turn.
- No task or `--tui`: Textual minimal interactive mode.
- `-p`/`--print`: decoration-free final output; piped stdin support.
- `--events`/`--jsonl`/`--json`: JSONL events (session start, user, thinking, tool call/result, assistant, turn end, error, session end).
- Print mode compose `CodingSession`. Undecorated output, session lifecycle, resource behavior, persist, JSON event translation compatible. JSON records use schema v1, carry session/run/turn correlation. Terminal turn records from typed session finish event include normalized usage.
- Default non-interactive task path use ephemeral `CodingSession`. CLI entry match print, embedded, Textual, prompt-toolkit semantics.
- Built-in hosts resolve via stable `print`, `jsonl`, `textual`, `prompt-toolkit`, `embedded`. Reserved `fullscreen`, `webapp` fail before startup. CLI mode names compatible with host IDs.
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
- Registered cwd-bound tools: `read`, `write`, `edit`, `bash`, `ls`, `find`, `grep`. Only `read`, `write`, `edit`, `bash` enabled default. Enabled tools persist in UI config.
- Filesystem tools enforce cwd contain, sensitive/excluded targets, symlink mutate deny, bounded read/search, output truncate.
- `edit` require exact unique match; `write` + `edit` reject unsafe mutate.
- `bash` have timeout, cancel, bounded output, live callbacks, Windows process-tree terminate.
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
- Footer show cwd, provider/model, context count, reasoning. Token usage via host-neutral turn result + JSON event contract. Interactive footer show `n/a` until presentation ticket implement.
- Prompt-toolkit shell small fallback/test path; Textual own full interaction parity.

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
- Pass 5 focused Textual tests, 53 UI tests, 302 full tests. Mypy clean. Git diff clean.

### Ticket 05: dispatch prompts through SessionController

- Add `SessionController` host-neutral seam wrapping `CodingSession` with typed `PromptIntent`.
- Wire CLI one-shot, print, JSONL, Textual, prompt-toolkit, embedded prompt dispatch via controller.
- Pass 14 focused tests, 316 full suite, mypy clean, git diff check clean.

### Ticket 06: move informational commands behind controller

- Add `CommandIntent` + typed outcomes (`HelpOutcome`, `ToolsOutcome`, `SkillsOutcome`, `SessionInfoOutcome`, `ReasoningOutcome`, `CommandErrorOutcome`) to `SessionController`.
- Dispatch `/help`, `/tools`, `/skills`, `/session`, `/reasoning` through `controller.dispatch_command(...)` in Textual + prompt-toolkit hosts.
- Pass 22 focused tests, 324 full suite, mypy clean, git diff check clean.

### Ticket 07: move session transitions behind controller

- Add `NewSessionIntent`, `ResumeSessionIntent`, `ResumeSelectIntent`, `ForkSessionIntent` + `ResumeOption`, `ResumeOptionsOutcome`, `SessionTransitionOutcome` to `SessionController`.
- Add single-use continuation token validation for `/resume` selection.
- Route `/new`, `/resume`, `/fork` through controller in Textual + prompt-toolkit hosts.
- Pass 27 focused tests, 329 full suite, mypy clean, git diff check clean.

### Ticket 08: move provider and settings flows behind controller

- Add `ModelSelectIntent`, `ProviderSetupIntent`, `SettingsIntent`, `LogoutIntent`, `ContinuationResponseIntent` + `ModelOption`, `ModelOptionsOutcome`, `ProviderSetupStepOutcome`, `ProviderSuccessOutcome`, `LogoutOptionsOutcome`, `LogoutSuccessOutcome` to `SessionController`.
- Add single-use continuation token handling for multi-step provider setup, model selection, and provider logout.
- Pass 33 focused tests, 335 full suite, mypy clean, git diff check clean.

### Ticket 09: move bang-shell behavior behind controller

- Add `ShellIntent`, `ShellResultOutcome`, `ShellErrorOutcome` to `SessionController`.
- Implement `dispatch_shell(...)` for direct visible (`!`) and hidden (`!!`) shell command execution.
- Route `!` and `!!` in Textual and prompt-toolkit hosts through `SessionController.dispatch_shell(...)`.
- Pass 36 focused tests, 338 full suite, mypy clean, git diff check clean.

### Ticket 10: apply explicit capability profiles across hosts

- Add `CAPABILITY_PROFILES` (`none`, `read-only`, `coding`, `custom`), `active_capability_profile`, `set_capability_profile` to `config.py`.
- Consistently filter model-facing tools and execution across CLI, TUI, and embedded hosts.
- Pass 55 focused tests, 340 full suite, mypy clean, git diff check clean.

### Ticket 11: enforce run limits and stop reasons

- Add `RunLimits`, `LimitExceededError`, and `StopReason` to runtime loop, `CodingSession`, `SessionController`, and `EmbeddedSession`.
- Enforce provider-call, tool-call, elapsed-time, token, and cost bounds with precise machine-readable `stop_reason` values on `TurnResult`.
- Pass 51 focused tests, 342 full suite, mypy clean, git diff check clean.

### Ticket 12: complete thin Textual migration

- Add `TextualEventRouter` to `textual_tui.py` with explicit handlers for `TurnStartedEvent`, `MessageEvent`, `TurnFinishedEvent`, and diagnostic fallbacks for unhandled events.
- Ensure all host interactions dispatch via `SessionController` intents.
- Pass 50 focused Textual tests, 343 full suite, mypy clean, git diff check clean.

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
