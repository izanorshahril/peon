# 04 — Add metadata-only performance traces

**What to build:** Let an operator opt into structured performance traces that identify slow turns, provider requests, tools, resource loading, persistence, and extension hooks. Default operation remains no-op, and trace records omit conversation and tool content.

**Blocked by:** 01 — Route print mode through CodingSession.

**Status:** completed

- [x] The default trace sink performs no I/O and does not change print, JSON event, or interactive output.
- [x] An opt-in JSONL trace sink records schema version, UTC timestamp, monotonic duration, correlation identifiers, operation, outcome, and relevant provider, model, or tool names.
- [x] The module that owns an operation measures it; hosts do not infer provider, tool, resource, persistence, or hook durations after completion.
- [x] Trace records exclude prompts, assistant and thinking text, tool arguments and results, credentials, and file content by default.
- [x] Trace-export failures follow a documented isolation policy and cannot corrupt conversation state or turn persistence.
- [x] Deterministic tests verify correlation, duration, failure and cancellation outcomes, no-op behavior, and content redaction without relying on wall-clock timing.
- [x] Focused observability and session tests pass, followed by the full test suite and static type check.