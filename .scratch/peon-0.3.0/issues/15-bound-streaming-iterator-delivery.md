# 15 — Bound streaming iterator delivery

**What to build:** Make synchronous and asynchronous headless iterators safe for live streaming. Slow consumers get bounded, deterministic behavior; text and tool-output chunks may coalesce, but canonical messages, failures, cancellation, and terminal events are never silently lost.

**Blocked by:** 03 — Expose headless event iterators and validated history; 14 — Stream OpenAI-compatible responses end to end.

**Status:** ready-for-agent

- [ ] Synchronous iterators expose live text, thinking, tool, message, and terminal events without duplicate execution.
- [ ] Async iterators keep provider/tool work off the caller's event loop and propagate caller cancellation to the active turn.
- [ ] Event buffering has an explicit finite bound and documented overflow policy.
- [ ] Adjacent text/thinking/tool-output chunks may coalesce without changing final content, ordering across event families, or correlation.
- [ ] Canonical messages, tool completion, errors, cancellation, and terminal turn events are never dropped.
- [ ] Unrecoverable overflow yields a typed consumer stop reason and does not corrupt persisted canonical history.
- [ ] Iterator closure performs deterministic cleanup and leaves no worker/thread running.
- [ ] Typed and dictionary iterators remain schema-consistent and frontend-free.
- [ ] Complete-response iterator behavior remains compatible.
- [ ] Focused sync/async/backpressure/cancellation, full pytest, static typing, and diff validation pass.
