# 17 — Split headless, TUI, and serve packaging

**What to build:** Let corporate and embedded consumers install Peon's headless runtime without terminal frameworks. Textual and browser serving become explicit optional extras, while interactive startup without them returns actionable installation guidance.

**Blocked by:** 13 — Retire prompt-toolkit host.

**Status:** completed

- [x] Base installation contains no Textual, prompt-toolkit, or textual-serve dependency.
- [x] A TUI extra installs the supported Textual range and starts interactive mode.
- [x] A serve extra installs Textual and textual-serve without making serving a core dependency.
- [x] Interactive startup without the TUI extra returns a concise actionable install command and no traceback.
- [x] Headless CLI, AI adapters, agent loop, coding session, controller, and embedded adapters import and run in a clean base environment.
- [x] Embedded import does not load any terminal frontend module.
- [x] Development dependency setup installs everything required for full tests and static typing.
- [x] Wheel metadata exposes correct core, TUI, serve, and development dependency groups.
- [x] Python 3.13 remains the declared floor.
- [x] Clean core, TUI, and serve install smoke tests, full pytest, static typing, build, and diff validation pass.
