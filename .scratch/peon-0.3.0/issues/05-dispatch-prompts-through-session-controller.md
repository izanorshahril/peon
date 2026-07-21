# 05 — Dispatch prompts through SessionController

**What to build:** Introduce the host-neutral session controller seam and make one complete prompt work through it in every current host. One-shot, print, JSONL, embedded, and Textual callers dispatch a typed prompt intent and observe the same events, result, persistence, cancellation, resources, and tool behavior.

**Blocked by:** 03 — Expose headless event iterators and validated history; 04 — Unify tool lifecycle events.

**Status:** ready-for-agent

- [ ] The controller accepts one typed prompt intent and exposes immutable current session state, runtime events, a terminal result, and cancellation.
- [ ] The controller composes the existing coding-session seam rather than duplicating the agent loop.
- [ ] One-shot, print, JSONL, embedded, and Textual prompt paths use the controller.
- [ ] All hosts produce equivalent canonical conversation history for the same fake provider and tool sequence.
- [ ] Resource prompts remain provider-visible, excluded from persisted conversation history, and applied once.
- [ ] Cancellation, persistence retry/error behavior, usage aggregation, and traces remain compatible.
- [ ] Schema version 1 JSON output and ordinary print output remain unchanged.
- [ ] Textual still owns worker scheduling and presentation state while prompt effects come from controller events.
- [ ] Existing direct agent-loop, coding-session, and embedded submit interfaces remain supported.
- [ ] Focused controller, host compatibility, full pytest, static typing, and diff validation pass.
