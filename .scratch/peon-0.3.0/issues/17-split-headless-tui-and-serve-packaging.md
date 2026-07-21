# 17 — Split headless, TUI, and serve packaging

**What to build:** Let corporate and embedded consumers install Peon's headless runtime without terminal frameworks. Textual and browser serving become explicit optional extras, while interactive startup without them returns actionable installation guidance.

**Blocked by:** 13 — Retire prompt-toolkit host.

**Status:** ready-for-agent

- [ ] Base installation contains no Textual, prompt-toolkit, or textual-serve dependency.
- [ ] A TUI extra installs the supported Textual range and starts interactive mode.
- [ ] A serve extra installs Textual and textual-serve without making serving a core dependency.
- [ ] Interactive startup without the TUI extra returns a concise actionable install command and no traceback.
- [ ] Headless CLI, AI adapters, agent loop, coding session, controller, and embedded adapters import and run in a clean base environment.
- [ ] Embedded import does not load any terminal frontend module.
- [ ] Development dependency setup installs everything required for full tests and static typing.
- [ ] Wheel metadata exposes correct core, TUI, serve, and development dependency groups.
- [ ] Python 3.13 remains the declared floor.
- [ ] Clean core, TUI, and serve install smoke tests, full pytest, static typing, build, and diff validation pass.
