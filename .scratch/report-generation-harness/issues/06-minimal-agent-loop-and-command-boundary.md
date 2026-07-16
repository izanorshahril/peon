# 06 — Minimal agent loop and command boundary

**What to build:** An installable Python agent core with a small command boundary that accepts a task, runs one normalized provider turn, and returns the final response through an injected provider.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The project can be installed and invoked through the chosen `uv` workflow in a fresh user-space environment.
- [ ] The command boundary accepts a task and provider configuration without domain-specific workflow arguments.
- [ ] The agent loop can receive a provider dependency and compact initial context without provider-specific branching in the core.
- [ ] Invalid command input produces a clear operator-facing error instead of a traceback-only failure.
- [ ] A fake provider can complete a task through the public command and orchestration seams.
