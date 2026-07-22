# 02 - Complete runtime events and shared serializers

**What to build:** Publish one immutable ordered runtime-event vocabulary and
one serializer interface for schema versions 1 and 2.

**Blocked by:** 01 - Establish trustworthy validation baseline.

**Status:** completed

- [x] Every public event carries schema identity, stable type, injected UTC
  timestamp, run-scoped sequence, and applicable correlation IDs.
- [x] Event sequence is assigned once by application emitter and remains stable
  through callbacks, iterators, JSONL, and journals.
- [x] Turn start, canonical message, delta, command/selection, cancellation,
  terminal error, and exactly-one turn finish events form closed typed union.
- [x] Streaming deltas and final canonical message share stable message ID.
- [x] Pure shared serializer supports explicit schema version selection.
- [x] Schema version 1 remains byte/field compatible with characterized CLI
  output and remains default.
- [x] Schema version 2 serializes every event and precise stop reason without
  host-specific fields.
- [x] CLI exposes explicit schema version 2 selection and uses shared serializer
  for both versions.
- [x] Unknown serialized event policy supports tolerant diagnostic and strict
  rejection modes.
- [x] Golden serializer tests, callback order tests, full pytest, mypy, build,
  and diff validation pass.

## Evidence

Validated 2026-07-22:

- Focused runtime, serializer, CLI, and controller tests: 110 passed.
- Canonical full suite: 320 tests, 0 failures, 0 errors, 2 strict expected_1 
  failures, exit 0.
- `uv run mypy src/peon`: success across 28 source files.
- `uv build`: `0.3.0a0` sdist and wheel built successfully.
- `git diff --check`: clean.
- Schema-v1 CLI output remains default and characterized fields remain covered;
  `--schema-version 2` emits normalized typed events with UTC timestamp,
  contiguous sequence, message identity, and terminal stop reason.
- Unknown serialized events produce diagnostics by default and raise in strict
  mode. Provider errors and cancellation emit typed terminal facts before one
  `TurnFinishedEvent`.
