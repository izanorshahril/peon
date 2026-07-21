# 04 — Unify tool lifecycle events

**What to build:** Report model-requested tool work through the same typed runtime event stream used for turns. Headless, JSONL version 2, embedded, and Textual consumers can observe tool start, bounded live output, finish, failure, and cancellation while canonical tool messages remain the only persisted tool state.

**Blocked by:** 02 — Publish complete-turn runtime events.

**Status:** ready-for-agent

- [ ] A tool call emits a start event before execution and a finish event after its canonical result is known.
- [ ] Live tool output emits bounded events with operation ID, provider call ID when available, stream name, and deterministic ordering.
- [ ] Tool success, error, and cancellation produce distinct typed outcomes and exactly one tool finish event.
- [ ] Canonical assistant tool-call and tool-result messages remain provider-compatible and persist once.
- [ ] Schema version 2 serializes the full tool lifecycle; schema version 1 remains compatible.
- [ ] Embedded typed and dictionary consumers receive tool lifecycle events.
- [ ] Textual renders the new tool events with current compact, expandable output behavior.
- [ ] The legacy live-output callback remains as a compatibility adapter until all hosts migrate.
- [ ] Slow or failing event handlers follow the declared isolation policy and do not duplicate tool execution.
- [ ] Focused tool, embedded, JSONL, Textual, cancellation, full pytest, static typing, and diff validation pass.
