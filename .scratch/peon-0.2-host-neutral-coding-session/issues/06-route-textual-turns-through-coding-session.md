# 06 — Route Textual turns through CodingSession

**What to build:** Make the canonical Textual frontend consume `CodingSession` for prompt preparation, execution, persistence, lifecycle events, and cancellation while retaining its current transcript rendering, keyboard controls, pickers, dialogs, live tool presentation, and worker policy.

**Blocked by:** 01 — Route print mode through CodingSession.

**Status:** completed

**Completed in:** working tree after Ticket 05

**Validation:** Focused Textual, resource, bash, and session tests passed,
followed by the full test suite and static type check.

- [x] Submitting a Textual prompt invokes the same `CodingSession` behavior used by print mode rather than a duplicate execution and persistence path.
- [x] User, thinking, assistant, tool-call, tool-result, live tool-output, error, and cancellation events render with current observable behavior.
- [x] Resource prompts are applied exactly once on new, resumed, and forked conversations and are not persisted as conversation messages.
- [x] Session create, resume, switch, fork, durable-exit, and ephemeral behavior remains compatible.
- [x] Escape and other current cancellation gestures cancel active session or tool work idempotently without reaching into provider or tool implementations from widgets.
- [x] Rendering, keyboard handling, layout, dialogs, provider/model pickers, and worker scheduling remain owned by the Textual host.
- [x] Shared execution assertions move to `CodingSession` tests while focused Textual pilot tests continue to verify widget-to-session translation and presentation.
- [x] Focused Textual session, resource, bash, and cancellation tests pass, followed by the full test suite and static type check.