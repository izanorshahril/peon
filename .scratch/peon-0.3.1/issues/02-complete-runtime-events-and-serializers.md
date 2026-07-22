# 02 - Complete runtime events and shared serializers

**What to build:** Publish one immutable ordered runtime-event vocabulary and
one serializer interface for schema versions 1 and 2.

**Blocked by:** 01 - Establish trustworthy validation baseline.

**Status:** ready-for-agent

- [ ] Every public event carries schema identity, stable type, injected UTC
  timestamp, run-scoped sequence, and applicable correlation IDs.
- [ ] Event sequence is assigned once by application emitter and remains stable
  through callbacks, iterators, JSONL, and journals.
- [ ] Turn start, canonical message, delta, command/selection, cancellation,
  terminal error, and exactly-one turn finish events form closed typed union.
- [ ] Streaming deltas and final canonical message share stable message ID.
- [ ] Pure shared serializer supports explicit schema version selection.
- [ ] Schema version 1 remains byte/field compatible with characterized CLI
  output and remains default.
- [ ] Schema version 2 serializes every event and precise stop reason without
  host-specific fields.
- [ ] CLI exposes explicit schema version 2 selection and uses shared serializer
  for both versions.
- [ ] Unknown serialized event policy supports tolerant diagnostic and strict
  rejection modes.
- [ ] Golden serializer tests, callback order tests, full pytest, mypy, build,
  and diff validation pass.
