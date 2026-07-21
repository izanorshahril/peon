# Peon vs Mini-SWE-Agent Gap Review

Reviewed: 2026-07-21

## Scope and verdict

This is a current-worktree architecture and capability review, not a commit
diff. It compares Peon's portable runtime and headless paths with the vendored
mini-SWE-agent v2 reference under `reference/mini-swe-agent`.

**Verdict:** Peon already covers mini-SWE-agent's essential headless loop and
is stronger for provider independence, typed contracts, optional rich tools,
embedding, lifecycle events, persistence, cancellation, and multiple hosts.
It does not yet match mini-SWE-agent's install minimalism, explicit execution-
environment implementations, automation limits, or self-contained trajectory
artifact. Alternate hosts can reuse Peon's conversation/session runtime and
command vocabulary, but not yet one shared command-execution service.

Peon should remain a Pi-like conversational coding agent. Learn from mini's
small replaceable execution boundary and unattended-run guardrails; do not
adopt its LiteLLM dependency, bash-only product model, untyped message extras,
benchmark-specific completion sentinel, or import-time configuration effects.

## Capability comparison

| Concern | Peon | mini-SWE-agent | Assessment |
| --- | --- | --- | --- |
| Core loop | Typed `run_task`; injected provider and executor; bounded tool continuations | Small `query`/`execute_actions` loop; injected model and environment | Covered |
| Headless CLI | One-shot, print, piped input, and JSONL events | Task/yolo CLI and batch-oriented runners | Covered; Peon has more output modes |
| Python embedding | `EmbeddedSession` with structured result, events, persistence, cancellation, and optional resources/tools | Direct `DefaultAgent(model, env).run(task)` | Covered; Peon is richer |
| Conversation history | Provider-neutral linear `AgentContext`; append-only session messages | Linear message list equals trajectory conversation | Covered at conversation level |
| Providers | Direct standard-library OpenAI-compatible, Copilot, and custom adapters | Default model stack depends on LiteLLM; other provider wrappers available | Peon better fits constrained corporate environments |
| Tools | Typed registry; no executor means no advertised tools; filesystem/bash tools injectable | Bash is sole action interface | Covered with larger optional surface |
| Skills/context | Optional `ResourceInventory`; CLI discovery can be disabled; selected skill bodies load progressively | Prompt/config templates, not Peon-style discoverable skills | Peon exceeds reference |
| Execution target | Generic `ToolExecutor` permits replacement; built-ins execute on local workspace | Explicit local, Docker, Singularity, and other environment implementations | Contract covered; built-in isolation gap |
| Run limits | Maximum tool-call count; per-bash timeout and output bound | Step, cost, wall-time, format-error, and environment timeout limits | Partial |
| Failure recovery | Structured errors; tool/provider errors stop turn; no provider retry policy | Retry helper and model-format correction loop | Partial |
| Run artifact | Linear session JSONL plus optional metadata-only trace and JSON events | One serialized trajectory includes messages, raw responses, config, cost, environment, and exit status | Partial for reproducible automation |
| Install footprint | Provider transport uses standard library, but base package installs Textual and prompt-toolkit and requires Python 3.13 | Core is conceptually small, but vendored v2 imports LiteLLM, Pydantic, Jinja, Rich, Typer, YAML, dotenv, and platformdirs | Different tradeoff; Peon provider path is leaner, package path is not |
| Host reuse | Shared `CodingSession`, host catalog, command catalog, and config data | Interactive subclass extends core agent directly | Runtime covered; command behavior partial |

## Standards

Documented boundaries are mostly upheld: `agent` remains provider-neutral,
provider quirks remain in `ai`, resources and sessions remain in `app`, and
executable capabilities remain in `extensions`.

Findings:

- **Partial minimal/headless packaging:** `pyproject.toml` makes Textual and
  prompt-toolkit mandatory even for library-only use. `peon.embedded` does not
  import either frontend at runtime, as its import-smoke test verifies, but a
  consumer still installs both. This weakens the documented "minimal modular"
  and frontend-free embedded intent; move presentation dependencies to an
  optional extra or split distribution only when packaging tests prove the
  default CLI remains usable.
- **Possible Duplicated Code / Shotgun Surgery:** built-in registry assembly is
  repeated in CLI and TUI composition. A new default tool or policy can require
  edits in multiple hosts. One app-owned registry factory would keep defaults
  consistent without moving extension behavior into `agent`.
- **Possible Repeated Switches:** command definitions and resolution are shared,
  but command execution remains separately branched in prompt-toolkit and
  Textual hosts. This is the main architectural limit on web/alternate-host
  reuse. Keep picker/rendering behavior host-owned; move command effects and
  typed outcomes into one app service.
- `EmbeddedSession` delegating to app-owned `CodingSession` is intentional, not
  a boundary violation. Lazy `peon.app` exports keep frontend modules unloaded.
- `run_task` is a justified orchestration boundary, not needless middle-man
  code: it owns provider/tool continuation while `CodingSession` owns lifecycle,
  resources, persistence, events, and structured outcomes.

## Spec

Requested behavior already present:

- Minimal/headless execution works through direct `run_task`, default one-shot
  CLI, print mode, JSONL event mode, and `EmbeddedSession`.
- A caller can inject any `ModelProvider` and avoid LiteLLM. Built-in OpenAI-
  compatible transport uses the Python standard library and permits local
  endpoints without an API key.
- Tools are optional in direct and embedded use: omit `ToolExecutor` to send no
  tool definitions. An unexpected provider tool call becomes a returned
  `ToolCall` at loop level and a structured configuration error at session
  level, rather than executing anything.
- Skills are optional application resources, not agent-core dependencies.
  Embedded callers opt in with `ResourceInventory`; CLI callers can disable
  discovered skills and context independently.
- Conversation execution is already independent of Textual. Print, JSONL,
  prompt-toolkit, Textual, and embedded paths share `CodingSession` semantics.

Missing or partial behavior:

- **Reusable slash-command behavior:** alternate hosts can reuse catalog search
  and parsing, but must still reimplement command effects, dialogs, and state
  transitions. Settings also combine reusable provider/tool policy with
  presentation-only colors, spacing, rendering, and shortcuts in `UiConfig`.
- **Explicit headless capability profile:** ordinary one-shot CLI currently has
  no executor, while print/JSONL composition registers default tools. Python
  callers are explicit, but CLI behavior depends on selected mode. Add one
  explicit policy for `none`, safe defaults, or selected tools/resources.
- **Automation budgets:** Peon lacks maximum provider-call, wall-time, token,
  and cost policies. `max_tool_calls` prevents infinite tool continuation, but
  unattended runs need typed limits and terminal reasons. Cost limits must be
  optional because compatible endpoints may not report cost.
- **Provider resilience:** request timeout is fixed in the standard-library
  transport, active cancellation cannot interrupt a blocking provider request,
  and no retry/backoff policy exists. These are automation gaps; mini's wall
  check also does not interrupt an already-blocked model request, so copy the
  goal rather than its exact implementation.
- **Execution isolation:** `ToolExecutor` is sufficient as an injection seam,
  but Peon ships only local workspace implementations. A sandbox integration
  must replace the complete tool set coherently; built-in container/remote
  backends do not exist.
- **Reproducible trajectory:** session records intentionally persist
  conversation messages, while traces intentionally omit content. Automation
  lacks one optional artifact containing effective run policy, provider/model
  identity, resource/tool manifest, usage, terminal status, and messages.
- **Embedding compatibility:** Python 3.13 and mandatory TUI dependencies make
  inclusion in existing corporate projects harder than the runtime design
  itself. Lower Python support requires a tested compatibility decision, not a
  metadata-only change.

Scope to reject from mini-SWE-agent:

- Do not add LiteLLM to core or make provider breadth dependent on it. Keep
  direct OpenAI-compatible transport and injected adapters.
- Do not reduce Peon to bash-only operation. Rich tools and skills remain
  optional, typed extensions; a minimal profile may choose only bash or none.
- Do not use `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` as general completion.
  Final model text is correct for conversation and embedding; explicit terminal
  outcomes belong in automation policy.
- Do not persist raw provider payloads by default or weaken typed messages into
  `dict` plus an overloaded `extra` field. Any trajectory export must be
  explicit and apply content/security policy.
- Do not copy import-time config-directory creation, environment loading, or
  startup printing from mini's package root. Library imports stay side-effect
  free.

## External reviewer questions

### 1. Headless core and Python event stream

**Verdict: valid goal; current support is partial; proposed `yield dict`
contract is too specific.**

Current state:

- `peon.agent.run_task` takes Python values (`str`, `AgentContext`, an injected
  `ModelProvider`, and optional `ToolExecutor`) and has no UI imports.
- Tool execution is provider-neutral and UI-free. Skills, resources, and slash
  commands are not agent-core logic: resource policy and command vocabulary
  live in `app`, while executable tools and registered skills live in
  `extensions`. None requires Textual.
- `EmbeddedSession` runs fully headless and accepts an existing typed history
  through `AgentContext`. Print and JSONL modes are also headless.
- `CodingSession` emits typed dataclass callbacks for turn start, complete
  messages, and turn finish. Tool calls and results appear inside
  `MessageEvent`; live bash chunks use a separate callback.
- Peon does **not** stream model text. `ModelProvider.complete` is synchronous,
  `run_task` returns only after a complete response, and no public generator or
  async iterator yields text deltas.
- The JSONL CLI serializes typed session events into ordinary dictionaries, but
  that serializer is a CLI adapter rather than the Python runtime contract.

Recommendation:

- Keep typed domain events as the canonical internal API. Add a stable,
  versioned dictionary serializer for JSONL, RPC, subprocess, and web clients.
  Making unvalidated dictionaries the core API would weaken type checks and
  make compatibility harder.
- Add streaming only after provider adapters expose a real streaming contract.
  Then model explicit events such as `TextDeltaEvent`, `ToolStartedEvent`,
  `ToolOutputEvent`, `ToolFinishedEvent`, and `TurnFinishedEvent`.
- Offer an iterator or async-iterator facade for callers that prefer `for` or
  `async for`, while retaining callback/subscription support for GUIs and
  cancellation. Do not force the loop itself to be a Python generator.
- Accept raw dictionary history only at a validated serialization boundary;
  keep `AgentContext`/`AgentMessage` canonical inside the process.

So: fully headless is already true. A standard serialized event stream is a
good next requirement. Text-delta streaming is a separate provider/runtime
feature, not evidence required to call the current engine headless.

### 2. Durable JSONL, logging, and observability

**Verdict: separation is good; "append every event" and "JSONL is memory and
tracing" are not good requirements.**

Current state:

- Durable `JsonlSessionStore` appends canonical conversation messages, not all
  lifecycle events. `MemorySessionStore` supports ephemeral and embedded use.
- Message persistence occurs before `CodingSession` publishes its
  `MessageEvent`; persistence failure turns the turn into a structured error.
- Session JSONL is conversation state. Runtime JSON events are an output
  protocol. Metadata-only performance traces are a third, opt-in JSONL stream.
- No heavy observability framework is used. Peon uses standard-library
  `logging`, but currently only for event-handler and trace-export failures.
- Explicit trace records, not log parsing, measure provider, tool, resource,
  persistence, hook, and whole-turn durations. They are disabled by default
  and contain correlation IDs without conversation content.

Recommendation:

- Preserve three contracts:
  1. session store for canonical resumable state;
  2. runtime event stream for live consumers;
  3. trace/log output for diagnosis and performance.
- Do not append every text delta, animation state, processing indicator, or live
  shell chunk to normal sessions. This would inflate files, couple storage to
  presentation cadence, and make replay depend on transient transport events.
- If exact run replay or audit becomes necessary, add a separate opt-in event
  journal with a versioned schema, retention policy, redaction, and explicit
  backpressure. Do not silently redefine session files as event logs.
- Continue standard `logging` for runtime errors, warnings, and operator
  diagnostics. Keep measured latency in the existing trace contract; ordinary
  log text is a poor metrics schema.
- Core should depend on `SessionStore` and `TraceSink` protocols, never on
  JSONL itself. JSONL remains one lightweight app-owned implementation.

### 3. Textual as exclusive TUI and a dumb screen

**Verdict: Textual-only interactive UI is a reasonable product choice;
"pure dumb screen" is neither current truth nor the right boundary.**

Current state:

- Textual is the primary UI, but not exclusive: `prompt-toolkit` remains an
  available fallback host with tests and duplicated command handling.
- Textual consumes `MessageEvent` for completed user/assistant/tool messages,
  but live bash output arrives through a separate callback.
- `TextualPeonApp` also constructs sessions, schedules workers, invokes direct
  shell commands, handles cancellation, mutates provider/settings/session
  state, loads skills, and implements slash-command effects. It is a thick
  application controller, not a passive renderer.
- `textual-serve` can launch each Textual app in a subprocess and expose it in
  a browser over its custom WebSocket protocol. This reuses the Textual app; it
  does not create a native web frontend or remove multi-user, authentication,
  deployment, and process-isolation concerns.

Recommendation:

- If "exclusive" means one maintained interactive terminal UI, retire the
  prompt-toolkit host after its useful fallback behavior is either migrated or
  explicitly rejected. Keep print, JSONL, embedded, and future RPC modes; they
  are not competing TUIs.
- Make Textual a **thin host**, not a dumb screen. It should own widgets, focus,
  keyboard input, pickers, layout, animation, and scheduling. It should not own
  provider policy, command effects, session transitions, or tool policy.
- Extract a host-neutral application/session controller that accepts typed
  intents (`SubmitPrompt`, `RunCommand`, `CancelTurn`, `SelectSession`) and
  emits typed outcomes/events. This is the missing layer for command reuse.
- Treat `textual-serve` as a deployment adapter to validate separately. Do not
  let it define the core event or persistence architecture.

### 4. Dynamic TUI event router and unknown UI events

**Verdict: handler registration may help later; unknown UI events emitted by
agent core are misaligned and premature.**

Current state:

- Peon has no generic event router or widget-plugin registry.
- `CodingSession` exposes a closed typed event union. Textual currently reacts
  only to `MessageEvent`; other lifecycle state comes from worker completion or
  direct callbacks.
- The extension registry supports tools, skills, and lifecycle hooks, not
  frontend widget plugins.
- Kanban/dashboard behavior and subagents are outside current core scope.
  Animations are presentation reactions and need no core event type.

Recommendation:

- Core emits known domain/runtime facts, never presentation requests such as
  `{"type": "kanban"}`. A backend may report task/subagent state; a host decides
  whether that becomes a board, list, notification, or no UI at all.
- First unify current lifecycle, message, tool, live-output, and eventual text-
  delta events under typed, versioned contracts. Add exhaustive host handling
  plus a safe fallback for unsupported serialized event versions/types.
- If a concrete extension later needs custom UI, define a namespaced extension
  event envelope and a frontend-owned registry mapping event type to handler or
  widget factory. Registration, validation, teardown, permissions, and failure
  isolation must be explicit.
- Unknown events should be ignored or rendered as a generic diagnostic by
  policy; they must not dynamically import arbitrary widgets or require agent
  core changes.
- Do not build a generic widget-plugin framework now. Kanban, subagents, and
  animations have different state, security, and lifecycle needs; grouping
  them behind one arbitrary dictionary event hides rather than removes design.

### Pre-spec decisions

Accept these reviewer goals:

- Complete headless execution and embedding.
- One host-neutral, versioned event vocabulary.
- Streaming text/tool progress when providers support it.
- Thin Textual host and shared command/session behavior.
- Lightweight protocol-based persistence and observability.

Reject or rewrite these prescriptions:

- Replace "core yields standard dictionaries" with "core emits typed events;
  adapters serialize a stable dictionary schema."
- Replace "persist every yielded event" with "persist canonical resumable
  state; optionally journal runtime events for audit/replay."
- Replace "logging tracks all latency" with "logging reports diagnostics;
  trace sinks record structured latency."
- Replace "dumb screen" with "thin host owning presentation and input only."
- Replace "core emits unknown UI events" with "core emits known domain events;
  extension UI events are namespaced and frontend-owned when concrete need
  exists."

## Recommended order

1. Define typed runtime events and one versioned dictionary serializer. Include
   existing lifecycle/messages/tools first; do not claim text deltas until a
   provider streaming contract exists.
2. Extract host-neutral command/session intents and outcomes so Textual becomes
   a thin host. Decide whether to retire prompt-toolkit as separate cleanup.
3. Add typed `RunLimits`/terminal reasons for provider calls, elapsed time,
   tokens, and optional cost; preserve existing `run_task` defaults.
4. Make headless tool/resource selection explicit and consistent across
   one-shot, print, JSONL, and embedded composition.
5. Add provider streaming and cancellation, then expose callback plus iterator/
   async-iterator event adapters.
6. Make TUI dependencies optional for library consumers; test clean core and
   full CLI installs. Evaluate a lower Python floor with CI before changing it.
7. Define one execution-backend contract for local and isolated workspaces,
   then add a single container adapter only when a concrete automation use case
   needs it.
8. Add opt-in trajectory/event-journal export with redaction and stable schema;
   keep normal session persistence and metadata-only traces separate.

Axis summary: Standards has 3 judgement-call findings, worst being duplicated
host command/default-tool policy; Spec has 6 partial gaps, worst being missing
automation budgets and explicit headless capability policy.
