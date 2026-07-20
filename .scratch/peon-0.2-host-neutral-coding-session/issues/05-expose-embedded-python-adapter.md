# 05 — Expose the embedded Python adapter

**What to build:** Provide a direct Python adapter that lets another application submit a text prompt, observe typed session events, cancel active work, and receive a structured result without launching or importing a terminal frontend.

**Blocked by:** 01 — Route print mode through CodingSession.

**Status:** completed

**Completed in:** working tree after Ticket 04 (`peon.embedded`)

- [x] A Python caller can create or receive a composed `CodingSession`, submit text, and obtain the same structured turn result used by built-in hosts.
- [x] A caller can observe typed lifecycle events and cancel active work without accessing private session or terminal state.
- [x] The adapter supports injected provider, tools, memory session storage, clock, and ID sources for deterministic integration tests.
- [x] Importing and using the embedded adapter does not import Textual or prompt-toolkit.
- [x] Resource application, tool execution, message persistence, failures, and cancellation match the primary `CodingSession` behavioral tests.
- [x] The public request shape implements text input only and does not invent unused multimodal fields; image input can extend the host-neutral interface later.
- [x] Focused embedded and import-isolation tests pass; full pytest and static type check are the remaining repository gate.