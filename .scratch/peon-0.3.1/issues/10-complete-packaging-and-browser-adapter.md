# 10 - Complete packaging and browser adapter

**What to build:** Prove core, TUI, and browser-serving installations are
correct while keeping browser serving an optional local adapter.

**Blocked by:** 06 - Finish thin Textual and host ownership; 09 - Complete event
journal interface.

**Status:** ready-for-agent

- [ ] Base dependencies exclude Textual, prompt-toolkit, and textual-serve.
- [ ] `tui` extra installs supported Textual and starts interactive mode.
- [ ] `serve` extra installs Textual and textual-serve.
- [ ] Development setup includes dependencies needed for full maintained tests,
  mypy, build, and browser smoke.
- [ ] Interactive startup without TUI extra returns actionable install command
  without traceback.
- [ ] Clean base wheel imports agent, AI, controller, embedded, and headless CLI
  without loading terminal frontend modules.
- [ ] Clean base, TUI, and serve wheel installations pass isolated smoke tests.
- [ ] Local textual-serve smoke reaches initial render and verifies prompt,
  streamed output, tool display, and cancellation.
- [ ] Release docs state textual-serve is not native browser UI or production
  authentication, tenancy, isolation, scaling, or public deployment.
- [ ] Python 3.13 remains declared floor and package metadata matches extras.
- [ ] Focused packaging/browser tests, full pytest, mypy, build, and diff
  validation pass.
