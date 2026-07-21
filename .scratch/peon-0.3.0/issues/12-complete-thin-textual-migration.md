# 12 — Complete thin Textual migration

**What to build:** Finish moving application effects out of Textual. The sole interactive presentation host dispatches controller intents and renders typed events through explicit handlers while retaining its current transcript, keyboard, picker, settings, session, resource, and tool experience.

**Blocked by:** 07 — Move session transitions behind controller; 08 — Move provider and settings flows behind controller; 09 — Move bang-shell behavior behind controller; 10 — Apply explicit capability profiles across hosts; 11 — Enforce run limits and stop reasons.

**Status:** ready-for-agent

- [ ] Textual dispatches prompt, command, continuation, session, shell, and cancellation intents rather than executing application effects directly.
- [ ] A Textual-owned router registers explicit handlers for every known typed runtime event class.
- [ ] Unsupported events follow a safe fallback and diagnostic without dynamic imports or app crashes.
- [ ] Widgets, focus, key bindings, layout, animation, worker scheduling, picker rendering, and transcript interaction remain Textual-owned.
- [ ] Provider/tool policy, command effects, session mutation, resource application, and message persistence are controller-owned.
- [ ] Current transcript ordering, styling, thinking visibility, live tool output, usage, errors, and processing state render from typed events.
- [ ] Existing keyboard, mouse selection, right-click copy, nested settings, session rows, resource display, and direct shell UX remain compatible.
- [ ] Legacy session-event and live-tool callback bridges are removed after every consumer uses the typed event path.
- [ ] No generic widget-plugin framework or presentation-specific backend event is introduced.
- [ ] Focused Textual/controller tests, full Textual suite, full pytest, static typing, and diff validation pass.
