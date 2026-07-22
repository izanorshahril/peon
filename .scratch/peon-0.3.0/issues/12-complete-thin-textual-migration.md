# 12 — Complete thin Textual migration

**What to build:** Finish moving application effects out of Textual. The sole interactive presentation host dispatches controller intents and renders typed events through explicit handlers while retaining its current transcript, keyboard, picker, settings, session, resource, and tool experience.

**Blocked by:** 07 — Move session transitions behind controller; 08 — Move provider and settings flows behind controller; 09 — Move bang-shell behavior behind controller; 10 — Apply explicit capability profiles across hosts; 11 — Enforce run limits and stop reasons.

**Status:** completed

- [x] Textual dispatches prompt, command, continuation, session, shell, and cancellation intents rather than executing application effects directly.
- [x] A Textual-owned router registers explicit handlers for every known typed runtime event class.
- [x] Unsupported events follow a safe fallback and diagnostic without dynamic imports or app crashes.
- [x] Widgets, focus, key bindings, layout, animation, worker scheduling, picker rendering, and transcript interaction remain Textual-owned.
- [x] Provider/tool policy, command effects, session mutation, resource application, and message persistence are controller-owned.
- [x] Current transcript ordering, styling, thinking visibility, live tool output, usage, errors, and processing state render from typed events.
- [x] Existing keyboard, mouse selection, right-click copy, nested settings, session rows, resource display, and direct shell UX remain compatible.
- [x] Legacy session-event and live-tool callback bridges are removed after every consumer uses the typed event path.
- [x] No generic widget-plugin framework or presentation-specific backend event is introduced.
- [x] Focused Textual/controller tests, full Textual suite, full pytest, static typing, and diff validation pass.
