# 03 — Expose headless event iterators and validated history

**What to build:** Give embedded and automation callers callback, synchronous iterator, and asynchronous iterator access to typed or serialized complete-turn events. Callers may provide typed history or validated dictionary history, and no terminal framework is imported.

**Blocked by:** 02 — Publish complete-turn runtime events.

**Status:** completed

- [x] Embedded callers can subscribe to typed runtime events and receive the same ordered lifecycle as the coding-session seam.
- [x] Embedded callers can choose versioned standard Python dictionaries produced by the shared serializer.
- [x] A synchronous iterator exposes events through normal Python iteration and makes the terminal result available without duplicate execution.
- [x] An asynchronous iterator keeps blocking provider work off the caller's event loop and propagates cancellation.
- [x] Complete-turn buffering is bounded and reports an explicit consumer error rather than silently dropping canonical or terminal events.
- [x] Dictionary history validates roles, content, thinking, tool calls, tool results, usage, and field types before any provider request.
- [x] Invalid or unknown history values fail with actionable errors and do not mutate session state.
- [x] Existing typed history and embedded submit/cancel interfaces remain compatible.
- [x] Import smoke tests prove callback and iterator use do not load Textual or prompt-toolkit.
- [x] Focused embedded, iterator, history-validation, full pytest, static typing, and diff validation pass.
