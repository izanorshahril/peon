# 10 - Complete packaging and browser adapter

**What to build:** Prove core, TUI, and browser-serving installations are
correct while keeping browser serving an optional local adapter.

**Blocked by:** 06 - Finish thin Textual and host ownership; 09 - Complete event
journal interface.

**Status:** completed

- [x] Base dependencies exclude Textual, prompt-toolkit, and textual-serve.
- [x] `tui` extra installs supported Textual and starts interactive mode.
- [x] `serve` extra installs Textual and textual-serve.
- [x] Development setup includes dependencies needed for full maintained tests,
  mypy, build, and browser smoke.
- [x] Interactive startup without TUI extra returns actionable install command
  without traceback.
- [x] Clean base wheel imports agent, AI, controller, embedded, and headless CLI
  without loading terminal frontend modules.
- [x] Clean base, TUI, and serve wheel installations pass isolated smoke tests.
- [x] Local textual-serve smoke reaches initial render and verifies prompt,
  streamed output, tool display, and cancellation.
- [x] Release docs state textual-serve is not native browser UI or production
  authentication, tenancy, isolation, scaling, or public deployment.
- [x] Python 3.13 remains declared floor and package metadata matches extras.
- [x] Focused packaging/browser tests, full pytest, mypy, build, and diff
  validation pass.
