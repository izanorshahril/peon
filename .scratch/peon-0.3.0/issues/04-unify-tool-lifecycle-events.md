# 04 — Unify tool lifecycle events

**What to build:** Report model-requested tool work through the same typed runtime event stream used for turns. Headless, JSONL version 2, embedded, and Textual consumers can observe tool start, bounded live output, finish, failure, and cancellation while canonical tool messages remain the only persisted tool state.

**Blocked by:** 02 — Publish complete-turn runtime events.

**Status:** completed

- [x] A tool call emits a start event before execution and a finish event after its canonical result is known.
- [x] Live tool output emits bounded events with operation ID, provider call ID when available, stream name, and deterministic ordering.
- [x] Tool success, error, and cancellation produce distinct typed outcomes and exactly one tool finish event.
- [x] Canonical assistant tool-call and tool-result messages remain provider-compatible and persist once.
- [x] Schema version 2 serializes the full tool lifecycle; schema version 1 remains compatible.
- [x] Embedded typed and dictionary consumers receive tool lifecycle events.
- [x] Textual renders the new tool events with current compact, expandable output behavior.
- [x] The legacy live-output callback remains as a compatibility adapter until all hosts migrate.
- [x] Slow or failing event handlers follow the declared isolation policy and do not duplicate tool execution.
- [x] Focused tool, embedded, JSONL, Textual, cancellation, full pytest, static typing, and diff validation pass.
