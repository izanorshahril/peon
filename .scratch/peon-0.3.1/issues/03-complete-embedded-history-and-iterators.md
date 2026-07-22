# 03 - Complete embedded history and iterator interfaces

**What to build:** Give embedded callers validated history plus reliable typed
or dictionary callbacks and iterators over one prompt execution.

**Blocked by:** 02 - Complete runtime events and shared serializers.

**Status:** completed

- [x] Embedded construction or load accepts typed messages and serialized
  history without terminal imports.
- [x] Validator covers roles, content, thinking, tool calls/results, usage, and
  field types before provider request or state mutation.
- [x] Invalid or unknown history returns actionable validation error.
- [x] Callback, sync iterator, and async iterator support typed or schema-selected
  dictionary events from same serializer.
- [x] Iterator consumer can retrieve final `TurnResult` without duplicate run.
- [x] Empty queue polling and terminal completion use distinct signals.
- [x] Async caller cancellation reaches active turn and worker cleanup is
  deterministic.
- [x] Buffer size validation and complete-response overflow behavior are
  explicit; no event disappears silently.
- [x] Embedded imports remain frontend-free with base installation.
- [x] Focused history/iterator/cancellation tests, full pytest, mypy, and diff
  validation pass.

## Evidence

Validated 2026-07-22:

- Focused embedded tests: 28 passed, 1 strict xfailed (ticket 04).
- Canonical full suite: 340 tests, 0 failures, 0 errors, 1 strict expected
  failure, exit 0.
- `uv run mypy src/peon`: success across 28 source files.
- `git diff --check`: clean.
- `BoundedEventQueue` rejects non-positive maxsize; empty `get(timeout)` returns
  `None`; `_DONE` sentinel is distinct from `None` and signals completion.
- `validate_history()` accepts typed `AgentMessage` or dict sequences; rejects
  unknown roles, missing content, invalid types, malformed tool calls with
  `HistoryValidationError`.
- `EmbeddedSession.load_history()` validates before context mutation; invalid
  input raises without side effects.
- `iter_events(schema_version=2)` and `aiter_events(schema_version=2)` yield
  dict events with `event_type` keys via shared serializer.
- `SyncEventIterator.result` and `AsyncEventIterator.result` expose final
  `TurnFinishedEvent` after iteration; no second run needed.
- Async iteration uses blocking `queue.get()` in executor; delayed providers do
  not trigger early termination.
- `CancelledError` cancels sub-session and joins worker deterministically.
- No Textual or prompt-toolkit module loads on `from peon.embedded import ...`.
