# Peon 0.3.1 Spec: Complete the Host-Neutral Runtime

Status: draft for implementation
Target release: 0.3.1
Prepared: 2026-07-22
Historical source: `peon-0.3.0-history.md`
Implementation tickets: `.scratch/peon-0.3.1/issues/`

## Purpose

Peon 0.3.1 completes contracts attempted during the unreleased `0.3.0a0`
migration. It is not a new feature train. It converts partial scaffolding into
one reliable host-neutral runtime, finishes thin-host ownership, and validates
the package for release.

The 0.3.0 history is authoritative for original decisions and implementation
evidence. This specification is authoritative for remaining work.

## Baseline

Current source provides:

- provider-neutral agent loop and complete-response providers;
- partial OpenAI-compatible streaming;
- `CodingSession` and `SessionController`;
- controller-backed prompt, informational command, and session-transition
  workflows;
- Textual presentation host and partial event router;
- embedded submit plus typed sync/async iterator scaffolding;
- partial capability profiles, run limits, event journal, and optional package
  extras;
- canonical JSONL conversation sessions compatible with 0.2;
- no prompt-toolkit implementation or dependency.

Current source does not yet satisfy the intended event, controller, iterator,
policy, streaming, journal, packaging, or release contracts. Package metadata
remains `0.3.0a0`.

## Problem

Several 0.3.0 tickets were marked complete after types or scaffolding landed,
without their observable acceptance behavior:

- Public runtime events lack common timestamp and sequence metadata.
- Schema version 1 and version 2 do not share one complete serializer path.
- Typed tool lifecycle events do not exist.
- Embedded callers cannot provide validated dictionary history or consume
  serialized event iterators.
- Async iterator timeout is indistinguishable from terminal completion.
- Provider/settings behavior remains split between controller, CLI, and
  Textual.
- Textual still owns application effects and a legacy tool-output path.
- Capability profiles and run limits are incomplete across hosted modes.
- Streaming timeout, active transport cancellation, retry safety, and
  backpressure are incomplete.
- Journal has no complete CLI/documentation contract.
- `serve` extra does not install textual-serve.
- Browser, clean-install, compatibility, and final release gates were never
  completed.
- Canonical `uv run pytest` collects vendored reference tests and fails before
  Peon tests run.

## Solution

Finish one deep application module around `SessionController` and
`CodingSession`:

```text
host adapter
    |
typed intent / immutable state / typed ordered event / terminal result
    |
SessionController
    |
CodingSession
    |
provider-neutral agent loop
    |                         |
provider adapter          tool executor
```

Callers learn one interface. Provider, tool, session, capability, limit, and
resource behavior stays behind it. Textual, CLI, JSONL, embedded, journal, and
browser-serving adapters map to or from that interface without owning duplicate
application policy.

## Release Criteria

0.3.1 is complete when all conditions hold:

1. `uv run pytest`, `uv run mypy src/peon`, `uv build`, and `git diff --check`
   pass from repository root.
2. Every public runtime event is immutable and carries schema identity, event
   type, injected timestamp, run-scoped sequence, and applicable correlation.
3. One serializer owns schema version 1 compatibility and schema version 2
   complete vocabulary.
4. CLI JSONL defaults to schema version 1 and offers explicit schema version 2.
5. Tool start, output, finish, failure, and cancellation use the same typed
   stream as turn/message/delta events.
6. Embedded callers can supply typed or validated dictionary history and
   consume typed or dictionary callbacks, sync iterators, and async iterators.
7. Iterator completion, timeout, overflow, cancellation, and terminal result
   are distinct; canonical and terminal events never silently drop.
8. Provider, model, settings, logout, session, resource, capability, limit, and
   shell effects execute behind controller without CLI or Textual imports.
9. Textual contains presentation and scheduling behavior only and handles every
   public event through explicit router handlers or safe fallback.
10. Hosted CLI task, print, JSONL, and Textual runs use one explicit capability
    policy; embedded remains no-tools unless caller opts in.
11. Provider/tool/elapsed/token/cost limits and unavailable accounting produce
    precise terminal stop reasons.
12. Complete and streaming provider paths produce equivalent final canonical
    history for equivalent responses.
13. Streaming cancellation closes active transport where supported; configured
    timeout bounds transport; retry never duplicates visible output or effects.
14. Event journal is explicit, documented, schema version 2, redaction-aware,
    recoverable, and separate from sessions and metadata traces.
15. Base, `tui`, and `serve` wheel installs pass clean smoke tests; `serve`
    installs Textual and textual-serve.
16. Local textual-serve smoke test reaches initial render and verifies prompt,
    streaming, tool display, and cancellation without implying production web
    guarantees.
17. Existing 0.2 sessions and schema version 1 consumers work without migration.
18. Version changes from `0.3.0a0` to final `0.3.1` only after every preceding
    gate passes.

## Runtime Event Interface

### Common metadata

Every event carries:

- `schema_version` for typed contract identity;
- stable `event_type`;
- UTC timestamp from injected clock;
- non-negative sequence increasing within one run;
- `session_id`, `run_id`, and applicable `turn_id`;
- stable `message_id`, `operation_id`, and provider `call_id` where relevant.

Sequence assignment belongs to one application-owned emitter. Hosts and sinks
must not generate or rewrite sequence values independently.

### Event families

Closed built-in union for 0.3.1:

- session start/state/close facts where emitted publicly;
- turn start and exactly one turn finish;
- canonical user, assistant, and tool messages;
- assistant text and thinking deltas;
- tool start, bounded output, and finish with success/error/cancelled outcome;
- command outcome and selection/input request;
- cancellation and terminal adapter/consumer error facts.

Tool output includes stream name and bounded chunk. Tool finish includes
canonical result entering provider history. Final assistant message uses same
message identity as its deltas.

### Failure policy

- Event-handler failures are logged and isolated unless caller explicitly
  selects strict consumer policy.
- A started turn always has exactly one terminal result.
- Strict journal or unrecoverable consumer failure maps to declared stop reason.
- Serialization errors terminate adapter output without mutating canonical
  conversation state.

## Serialization Interface

- Pure serializer maps typed events to standard Python dictionaries.
- Schema version 1 preserves existing CLI event names and fields.
- Schema version 2 covers every public event and stop reason.
- CLI, embedded dictionaries, journal, and future RPC call same serializer.
- Unknown serialized events are ignored with diagnostic by default or rejected
  in strict mode.
- Raw history validation rejects unknown roles, invalid field types, malformed
  tool calls/results, and invalid usage before provider request or state change.

## Embedded and Iterator Interface

- Existing `submit(text)` remains supported.
- Construction or explicit load accepts typed messages or validated serialized
  history without importing terminal frameworks.
- Callback, sync iterator, and async iterator each support typed or serialized
  events from one execution.
- Iterator interface exposes final `TurnResult` without rerunning prompt.
- Queue capacity is finite and validated as positive.
- Empty polling is not completion. Completion uses distinct internal signal.
- Adjacent deltas may coalesce while preserving final content and cross-family
  order.
- Canonical messages, tool finish, error, cancellation, and terminal turn event
  cannot drop.
- Unrecoverable overflow produces consumer-error stop reason and deterministic
  worker cleanup.

## Controller and Host Ownership

`SessionController` owns:

- prompt and shell dispatch;
- command resolution and effects;
- provider/model setup and persistence;
- settings and logout effects;
- session new/resume/fork transitions;
- resource application;
- capability profile and exact executable tool policy;
- run limits and cancellation;
- event ordering and terminal outcomes.

Controller implementation may depend on app-owned config/session modules, but
not CLI rendering functions or Textual classes.

Textual owns:

- widgets, styles, transcript layout, focus, key bindings, mouse behavior;
- animation and worker scheduling;
- picker/form rendering and secret-input controls;
- presentation mapping from typed events/outcomes.

Textual must not persist config/messages, select provider policy, execute tools,
or mutate session/controller state outside intent dispatch. Existing controller
prompt, informational-command, and session-transition behavior stays compatible.

## Capability and Limit Policy

Application-owned profiles remain:

- `none`: no model-callable tools;
- `read-only`: read, list, find, grep;
- `coding`: read, write, edit, bash;
- `custom`: exact selected registered names.

Sample tools never enter production defaults. Definitions sent to provider and
names executable by registry must match. Disabled or stale calls fail before
side effects.

Limits remain opt-in and immutable:

- provider calls;
- tool calls;
- elapsed wall time;
- input, output, and total tokens;
- cost plus currency.

Checks occur before work and after usage updates. Missing usage remains unknown.
Mixed currencies remain incomparable. Direct callers without limits preserve
current behavior.

## Streaming Contract

- Complete response remains required provider interface.
- Optional streaming is discovered structurally, not by provider name.
- AI adapter owns SSE parsing, fragment validation, tool-call assembly, timeout,
  retry, and transport-close behavior.
- Agent loop sees normalized chunks only.
- Retry is allowed only before visible delta or side effect.
- Cancellation closes response when adapter supports it and always stops later
  loop/tool work cooperatively.
- Text/thinking deltas reconcile into one canonical assistant message.
- Equivalent complete and streaming responses produce equivalent canonical
  messages and usage.

## Journal, Session, Trace, and Logging Separation

- Session: canonical provider-ready conversation messages only.
- Journal: opt-in schema version 2 runtime timeline; may contain sensitive
  content; redaction and strictness explicit.
- Trace: metadata-only operation timing, disabled by default.
- Logging: warnings, failures, and diagnostics.

Journal appends define trailing-record recovery. CLI help and README warn that
prompts, assistant content, tool arguments/output, paths, and secrets may be
written.

## Packaging and Browser Adapter

- Base wheel imports agent, AI, controller, embedded, and headless CLI without
  Textual, prompt-toolkit, or textual-serve.
- `tui` installs supported Textual range.
- `serve` installs `tui` requirements plus textual-serve.
- Missing interactive dependency returns actionable command without traceback.
- Prompt-toolkit is not advertised as available; explicit legacy selection may
  return migration guidance.
- textual-serve remains deployment adapter, not first-party browser interface.
- Release notes explicitly reject claims of authentication, tenancy, scaling,
  isolation, or secure public deployment.

## Ticket Order

1. Establish trustworthy 0.3.1 validation baseline.
2. Complete runtime event model and shared serializers.
3. Complete embedded history and iterator interfaces.
4. Unify model tool and direct shell lifecycle events.
5. Complete provider, model, settings, and logout controller flows.
6. Finish thin Textual and host ownership.
7. Enforce capability profiles, run limits, and stop reasons.
8. Complete streaming cancellation, timeout, retry, and backpressure.
9. Complete event journal operational interface.
10. Complete package extras and browser adapter validation.
11. Validate compatibility and release 0.3.1.

No ticket may mark itself complete because types or methods exist. Acceptance
requires observable behavior and executable evidence.

## Validation Policy

Every implementation ticket runs:

1. focused tests at changed public seam;
2. all tests for touched modules/hosts;
3. `uv run pytest`;
4. `uv run mypy src/peon`;
5. `git diff --check`.

Source changes also update `project-history.md` only after checks pass. Release
ticket additionally builds wheel, installs all extras in clean environments,
runs browser adapter smoke, checks both schemas, and verifies legacy sessions.

## Out of Scope

- New Pi parity features such as compaction, undo/redo, export/share, theme,
  editor, extension marketplace, RPC, or first-party webapp.
- LiteLLM, generic provider router, or provider-name branches in agent loop.
- New built-in sandbox/container/remote execution framework.
- Multi-agent orchestration, autonomous planning, RAG, fine-tuning, dashboards,
  office/report workflows, or communication integrations.
- Arbitrary backend-driven widgets or presentation-specific runtime events.
- OpenTelemetry or heavy observability frameworks.
- Session-format migration, raw provider payload persistence, or Python floor
  reduction.
- Production browser authentication, authorization, tenancy, isolation,
  scaling, or public deployment.

## Release Rule

0.3.1 is released only when ticket 11 records dated evidence for every release
criterion. Until then package version remains prerelease and history describes
work as partial, regardless of commit message or ticket checkbox.
