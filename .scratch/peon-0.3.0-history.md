# Peon 0.3.0 History: Headless Runtime and Thin Hosts

Status: archived implementation record; not a current specification
Prepared: 2026-07-22
Baseline: `peon-v0.2.0-working` at `840d8aea760af53e423864b25390a3e793a23611`
Reviewed head: `3f20f31`
Successor: `peon-0.3.1-spec.md`

## Purpose

This file is the only 0.3.0 planning and implementation record. It replaces:

- `peon-0.3.0-spec.md`;
- `.scratch/peon-0.3.0/issues/01` through `18`;
- repeated 0.3.0 ticket summaries in `project-history.md`.

It records original intent, architectural decisions, ticket outcomes, commit
evidence, validation claims, and post-implementation review. Ticket checkboxes
were implementation-time claims. The verified status below wins where those
claims disagree with current source.

## Original Problem

Peon 0.2 already had a provider-neutral agent loop, `CodingSession`, print and
JSONL modes, Textual and prompt-toolkit hosts, sessions, tools, resources,
provider adapters, traces, and an embedded Python adapter. Application behavior
was nevertheless split across callbacks and hosts:

- Runtime events covered turn and message facts, while live tool output used a
  separate callback.
- Provider responses were complete-message only.
- Commands, provider setup, session transitions, settings, capability policy,
  and resource actions were duplicated in interactive hosts.
- Textual was both presentation and application controller.
- Prompt-toolkit duplicated a second interactive host.
- Hosted modes disagreed about default tools.
- Unattended runs lacked explicit limits and precise stop reasons.
- Conversation state, runtime events, journals, traces, and logs lacked one
  documented separation of purpose.
- Base installation pulled terminal UI dependencies into headless consumers.

## Original Target

0.3.0 aimed to introduce one host-neutral application seam above
`CodingSession`. Hosts would dispatch typed intents and consume ordered typed
runtime events. Stable adapters would serialize those events without making
dictionaries the internal model.

Target shape:

```text
Textual / CLI / JSONL / Embedded / future RPC
                    |
          SessionController intents
                    |
               CodingSession
                    |
          provider-neutral agent loop
             /                 \
  provider adapter          tool executor
                    |
          typed runtime events
             /                 \
       host adapters      schema serializers
```

## Architectural Decisions

### Package ownership

- `agent`: provider-neutral messages, complete and streaming provider
  contracts, tool execution contracts, turn orchestration, and runtime facts.
  It never imports application or presentation modules.
- `ai`: authentication, transport, SSE parsing, provider-specific assembly,
  retry policy, timeout, and normalization.
- `app`: controller, command effects, sessions, resources, capability policy,
  limits, persistence composition, event correlation, serialization, and host
  selection.
- `extensions`: concrete tools, skills, hooks, and registration.
- Textual: widgets, rendering, focus, key bindings, layout, animation,
  scheduling, and presentation mapping only.

### Interfaces and compatibility

- `SessionController` was selected as highest application seam.
- `CodingSession.prompt()` remained lower-level headless turn seam.
- Direct `run_task`, complete-response providers, embedded submit, typed
  callbacks, 0.2 session files, and JSON event schema version 1 were retained.
- Prompt-toolkit was the only planned runtime removal; old explicit selection
  should fail with actionable guidance.
- Provider streaming was optional capability, never provider-name branching in
  agent loop.
- Provider-specific fragments belonged in `ai`, not `agent` or hosts.
- Conversation sessions would persist canonical messages only.
- Runtime journals would be opt-in schema version 2 outputs.
- Performance traces would stay metadata-only and separate from journals.
- Standard logging would carry diagnostics, not event or latency schemas.

### Runtime event contract

Original contract required immutable events with:

- schema identity and event type;
- session, run, turn, message, tool operation, and provider call correlation as
  applicable;
- injected timestamp and run-scoped monotonic sequence;
- turn start and exactly one terminal turn event;
- canonical message events;
- text and thinking deltas with stable message identity;
- tool start, bounded output, finish, failure, and cancellation;
- command outcomes, selection requests, state changes, cancellation, and
  terminal errors;
- final canonical messages after deltas, without duplicated persistence.

Schema version 1 would remain CLI default. Schema version 2 would serialize the
complete public event vocabulary through one pure serializer used by JSONL,
embedded dictionary iteration, journals, and future adapters.

### Delivery and safety

- Callback delivery remained canonical push interface.
- Sync and async iterators would run each prompt once and expose terminal
  result.
- Buffers would be finite. Delta chunks could coalesce; canonical messages,
  tool completion, failures, cancellation, and terminal events could not drop.
- Unrecoverable overflow would produce typed consumer failure.
- Raw dictionary histories would be validated before provider execution.
- Continuation tokens would be scoped, single-use, and mutation-free on invalid
  or replayed input.
- Event handler failures would be isolated and logged.

### Capability and limit policy

Profiles were defined as:

- `none`: no tools;
- `read-only`: read, list, find, grep;
- `coding`: read, write, edit, bash;
- `custom`: exact selected registered tools.

CLI task, print, JSONL, and Textual modes would default consistently to
`coding`; embedded use would default to no tools. Disabled or forged tool calls
would fail.

Optional limits covered provider calls, tool calls, elapsed time, input tokens,
output tokens, total tokens, and cost plus currency. Missing usage would remain
unknown, mixed currencies would not be combined, and terminal results would
carry precise stop reasons.

### Packaging and browser adapter

- Base install: no Textual, prompt-toolkit, or textual-serve.
- `tui` extra: supported Textual range.
- `serve` extra: Textual plus textual-serve.
- Browser serving: local deployment adapter only, not native browser UI,
  production authentication, tenancy, scaling, or public hosting.
- Python 3.13 remained floor.

## Ticket Ledger

### 01 - Freeze 0.2.0 baseline and contracts

Intent: validate and protect 0.2 before migration, create safety tag and backup
worktree, isolate feature work, and characterize external behavior.

Recorded outcome: completed. `peon-v0.2.0-working` identifies baseline.
Characterization covered coding-session event order, schema version 1,
persistence, embedded frontend-free imports, Textual behavior, and
cancellation. This historical setup work is not carried into 0.3.1.

### 02 - Publish complete-turn runtime events

Intent: ordered immutable complete-turn events, deterministic metadata, one
shared serializer, schema version 1 compatibility, and schema version 2
lifecycle.

Implemented: `TurnStartedEvent`, `MessageEvent`, `StreamDeltaEvent`, and
`TurnFinishedEvent` around `CodingSession` callbacks.

Verified status: partial. Public events do not carry required schema identity,
timestamp, or sequence. CLI schema version 1 still uses private translation.
Schema version 2 serializer does not represent original complete vocabulary.

### 03 - Expose headless event iterators and validated history

Intent: callback, sync iterator, async iterator, typed or dictionary events,
validated typed/dictionary history, bounded buffering, terminal result access,
and no frontend imports.

Implemented: typed callback plus `EmbeddedSession.iter_events()` and
`aiter_events()`.

Verified status: partial. No external history input/validator, dictionary event
mode, iterator terminal-result interface, or typed overflow error. Queue
semantics can silently end async iteration on timeout.

### 04 - Unify tool lifecycle events

Intent: tool start, bounded output, finish, failure, and cancellation through
same typed stream, while canonical tool messages remain persistence state.

Implemented: existing canonical tool messages and separate live-output
callback retained.

Verified status: missing. No public typed tool lifecycle event classes or
schema version 2 lifecycle serialization exist.

### 05 - Dispatch prompts through SessionController

Intent: introduce controller prompt intent and route one-shot, print, JSONL,
embedded, and Textual prompt paths through it.

Implemented in `0bbd170` with later integration changes. `SessionController`
wraps `CodingSession`; prompt dispatch, cancellation, resources, persistence,
usage, and direct lower-level interfaces remain available.

Verified status: complete for prompt dispatch. Later event-contract repairs
must preserve this behavior.

### 06 - Move informational commands behind controller

Intent: `/help`, `/tools`, `/skills`, `/session`, and `/reasoning` through typed
controller intents and outcomes.

Implemented in `6e43d99`, refined by `79eecad` and `c22ce09`.

Verified status: complete for listed informational commands.

### 07 - Move session transitions behind controller

Intent: `/new`, `/resume`, and `/fork` through typed intents, semantic resume
options, and single-use continuation tokens.

Implemented in `8a3a3c8`.

Verified status: complete for listed transitions and continuation-token use.

### 08 - Move provider and settings flows behind controller

Intent: complete model, provider setup, settings, and logout behavior behind
controller; Textual would only render options/forms.

Implemented in `838df0c`: intent/outcome types, initial provider setup, model
selection, logout, and continuation-token machinery.

Verified status: partial. `dispatch_settings()` is a placeholder error;
provider setup is incomplete; controller imports CLI-layer symbols; Textual
still owns provider, model, settings, and logout effects.

### 09 - Move bang-shell behavior behind controller

Intent: visible and hidden shell commands through controller with validation,
tool lifecycle events, cancellation, bounded output, and optional context
injection.

Implemented in `100261b`: `ShellIntent`, result/error outcomes, and controller
execution used by hosts.

Verified status: partial. Shell dispatch exists, but its progress and terminal
facts are outcomes/separate callbacks rather than unified runtime tool events.

### 10 - Apply explicit capability profiles across hosts

Intent: consistent `none`, `read-only`, `coding`, and `custom` profiles across
task, print, JSONL, and Textual; embedded remains opt-in.

Implemented in `292a6a5`: profile constants, active profile detection, setting,
and filtered executor.

Verified status: partial. Hosted composition is inconsistent, production CLI
still registers sample tools, profile options/reporting are incomplete, and
the same policy is not proven across all hosts.

### 11 - Enforce run limits and stop reasons

Intent: optional provider/tool/elapsed/token/cost limits with exact stop
reasons, unknown-accounting policy, and CLI/embedded configuration.

Implemented in `14a1828`: `RunLimits`, `LimitExceededError`, `StopReason`, and
selected checks across loop, session, controller, and embedded adapter.

Verified status: partial. Cost and several accounting semantics are not fully
enforced; error classification is incomplete; CLI limit controls and complete
schema version 2 representation are absent.

### 12 - Complete thin Textual migration

Intent: all application effects through controller, all known typed events
through explicit Textual router handlers, and no legacy live-output bridge.

Implemented in `fdb112d`: `TextualEventRouter` for current event classes and
controller routing for selected workflows.

Verified status: partial. Textual still owns provider/settings/model/logout and
some transition logic. Router only covers incomplete event vocabulary. Legacy
tool-output callback remains. `textual_tui.py` remains a broad application and
presentation module.

### 13 - Retire prompt-toolkit host

Intent: remove implementation, dependency, duplicate tests, and availability;
retain actionable error for explicit old selection.

Implemented in `d636610` and packaging cleanup `a0ac4a0`: implementation and
tests removed; dependency removed.

Verified status: mostly complete. Host catalog still retains prompt-toolkit as
an unavailable compatibility entry. 0.3.1 must decide whether this satisfies
actionable compatibility or violates “no discovery” acceptance, then lock one
behavior with tests.

### 14 - Stream OpenAI-compatible responses end to end

Intent: optional normalized streaming with SSE parsing, text/thinking deltas,
tool-call assembly, usage, final canonical response, cancellation, configurable
timeout, safe retry, Textual rendering, and non-stream fallback.

Implemented in `c87f4a6`: `StreamingModelProvider`, `ModelStreamChunk`,
`ToolCallDelta`, SSE parsing, loop consumption, and Textual delta rendering.

Verified status: partial. Event metadata/tool lifecycle prerequisites are
missing; request timeout is hard-coded; no explicit active transport close hook
exists; retry and cancellation guarantees are not fully proven.

### 15 - Bound streaming iterator delivery

Intent: finite deterministic buffers, safe coalescing, no loss of canonical or
terminal events, typed consumer overflow, cancellation, and worker cleanup.

Implemented in `f85ce35`: `BoundedEventQueue`, sync/async iterators, worker
thread, and turn-level callback.

Verified status: defective. Full queue blocks producer rather than applying
declared overflow policy. `get()` catches every exception and returns the same
`None` sentinel used for completion. Async iteration polls with a 50 ms timeout,
so a slow provider can terminate iteration before later events arrive.

### 16 - Add optional redacted event journal

Intent: explicit schema version 2 audit/replay journal, content warning,
redaction, safe append policy, strict/non-strict failure, and separation from
sessions/traces.

Implemented in `a422f23`: sink protocol, file sink, serializer, redaction hook,
strict flag, and session/controller emission.

Verified status: partial. No CLI opt-in or help/documentation surface exists;
serializer lacks full vocabulary; append recovery policy is not established;
strict failures are not mapped to complete declared terminal semantics.

### 17 - Split headless, TUI, and serve packaging

Intent: empty core dependencies, `tui` extra with Textual, `serve` extra with
Textual plus textual-serve, actionable startup errors, and clean-install smoke
tests.

Implemented in `d087593` and `a0ac4a0`: base dependencies empty, Textual moved
to extras, and missing-TUI guidance added.

Verified status: partial. `serve` omits `textual-serve`; clean core/TUI/serve
wheel smoke evidence is incomplete.

### 18 - Validate browser adapter and release 0.3.0

Intent: textual-serve smoke test, complete and streaming provider smoke tests,
legacy sessions, both event schemas, clean wheel installs, 0.2 behavior
comparison, full gates, final version, release notes, and history.

Recorded status remained `ready-for-agent`; all acceptance boxes were open.
HEAD commit `3f20f31` claimed all tickets complete, but no implementation or
validation closed this ticket. Package version is `0.3.0a0`, correctly showing
that final 0.3.0 was not released.

## Commit Chronology

```text
9635673  combined initial work for tickets 01-04
0bbd170  dispatch prompts through SessionController (05)
6e43d99  informational commands behind controller (06)
79eecad  refine informational dispatch
c22ce09  full-suite informational command fixes
8a3a3c8  session transitions behind controller (07)
838df0c  provider and settings flow scaffolding (08)
100261b  bang-shell through controller (09)
292a6a5  capability profile scaffolding (10)
14a1828  run limits and stop reasons (11)
fdb112d  Textual event router and migration work (12)
d636610  remove prompt-toolkit implementation (13)
c87f4a6  OpenAI-compatible streaming (14)
f85ce35  bounded iterator implementation (15)
a422f23  optional event journal (16)
d087593  packaging split (17)
a0ac4a0  packaging cleanup
3f20f31  claim all 0.3.0 tickets complete
```

Merge commits in range: `0586e86`, `67226a4`, `d77ecf0`.

## Validation Record

Implementation notes recorded focused suite growth from 316 through 343 tests,
then 302-310 after prompt-toolkit test removal. Individual commits recorded
passing focused tests, full `tests/` suite, and mypy.

Post-review validation on 2026-07-22:

- `uv run mypy src/peon`: pass, 28 source files.
- `uv build`: pass, producing `peon-0.3.0a0` sdist and wheel.
- `uv run pytest`: fails during collection because vendored
  `reference/mini-swe-agent` tests import missing `dotenv`.
- `uv run pytest -q tests`: maintained Peon tests progressed without observed
  failures, but terminal capture did not provide a trustworthy final summary;
  0.3.1 baseline ticket must rerun and record exact exit evidence.

The repository’s documented canonical full-test command is therefore not a
green release gate at archived head.

## Verified Outcome

0.3.0 established useful implementation scaffolding:

- `SessionController` and typed prompt/command/session intents;
- controller-backed prompt paths and selected command/session workflows;
- provider-neutral streaming primitives and OpenAI-compatible SSE parsing;
- partial run-limit, capability-profile, iterator, journal, and packaging work;
- prompt-toolkit implementation removal;
- Textual event router for current event classes;
- headless base dependency metadata.

It did not satisfy original release criteria. Verified complete ticket slices
are 01 and 05-07. Tickets 02-04 are foundationally incomplete; 08-17 are mostly
partial; 18 is unimplemented. 0.3.1 is a completion release, not a new feature
expansion.

## Carry-Forward Rules

0.3.1 work must preserve:

- provider neutrality and direct complete-response support;
- `agent` independence from `app` and concrete integrations;
- canonical-message-only session persistence and 0.2 session compatibility;
- schema version 1 CLI compatibility;
- controller-backed prompt and completed informational/session workflows;
- embedded default of no implicit tools/resources;
- Textual ownership of presentation and scheduling;
- no LiteLLM, generic environment framework, heavy observability stack,
  arbitrary backend widget requests, or first-party production web app.

0.3.1 must not trust old completed checkboxes. Each successor ticket closes only
after its acceptance behavior exists in source and passes focused plus full
validation.

## Original Out of Scope

- LiteLLM or another universal provider dependency.
- Arbitrary dictionaries as internal runtime model.
- Persisting deltas, tool chunks, animations, or selections in sessions.
- OpenTelemetry or a metrics server.
- Generic dynamic widget plugins or presentation-specific backend events.
- Multi-agent scheduling, dashboards, office/report workflows, RAG, or
  fine-tuning.
- Native browser widgets, production authentication, tenancy, scaling, or
  public deployment.
- Fullscreen TUI, context compaction, undo/redo, export/share, or unrelated Pi
  parity.
- Built-in Docker, Podman, remote, or generic sandbox environment framework.
- Session-format migration, raw provider payload persistence, or Python floor
  reduction.
- Streaming for unverified provider contracts.

## Sources Retained

- Pi coding agent documents and source under `reference/pi-windows-x64`.
- Tau architecture links in `project-history.md`.
- Mini-swe-agent comparison in `peon-vs-mini-swe-agent.md`.
- Current source and tests, which override historical claims.
