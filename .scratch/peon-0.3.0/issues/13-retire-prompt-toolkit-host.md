# 13 — Retire prompt-toolkit host

**What to build:** Make Textual the sole maintained interactive TUI after controller and Textual parity is proved. Remove prompt-toolkit runtime code, dependency, and duplicate tests while old explicit host selection fails with actionable guidance.

**Blocked by:** 12 — Complete thin Textual migration.

**Status:** ready-for-agent

- [ ] Controller and Textual tests prove retained prompt, command, provider, settings, session, resource, tool, shell, and cancellation behavior before removal.
- [ ] Prompt-toolkit implementation and host-specific orchestration are removed.
- [ ] Prompt-toolkit is removed from runtime dependencies and no source import references it.
- [ ] Host discovery no longer reports prompt-toolkit as available.
- [ ] Explicit old host selection returns an actionable unavailable-host error without traceback.
- [ ] Print, JSONL, embedded, and future adapter roles remain available and are not treated as competing TUIs.
- [ ] Textual remains the default interactive startup and retains characterized behavior.
- [ ] Obsolete duplicate tests are removed only after equivalent controller or Textual coverage exists.
- [ ] Import and package metadata checks prove prompt-toolkit is absent.
- [ ] Focused host/CLI/Textual, full pytest, static typing, and diff validation pass.
